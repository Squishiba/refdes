"""The thread-view projection: one per-thread view of a whole project.

docs/design/living-notes.md §5 (the five binding rules as *output structure*)
and §6 (one query service every surface reads, so a client "must not
reconstruct the chain itself"); plan phase H7a builds this projection and the
index `threads` key, and H7b/H7c (the `refdes thread` / `refdes work`
commands) and the task-pane client (thread-workbench.md §7a) are consumers of
this one function — none of them computes its own fold. Since H7c this module
also hosts the whole-project work query itself — `project_derived` and
`work_projection`, §5's "Generated worklist" rows and the payload `refdes
work` renders — sharing the per-item row builder and the one `_KIND_ORDER`
with the per-thread block, so the two commands can never answer differently
about the same gap.

The shape carries §5's decisions, not a rendering of them:

* two structurally separate groups — authored task lists live per tip in
  ``branches[].tasks`` (the `chains.fold_tasks` rows, *copied*: open rows gain
  ``open_since``, malformed rows are dropped with the count reported as
  ``tasks.malformed``), derived rows
  live in a thread-level ``derived`` list whose rows carry no task-row ``id``,
  so they can never sort into the authors' numbering and nothing writes them
  back;
* derived rows are computed from the build state the lifecycle gate rules
  already consult (coverage, checks, blocked chains, citations), so they
  self-close: fix the gap, re-read, the row is gone — there is no state to
  tick;
* every open task carries the entry that declared it and that entry's
  authored ``date:`` as ``open_since``, absolute. This module imports no
  clock (a test greps the source), so two runs on different wall clocks
  produce identical bytes; relative spans are only what H7b's ``--as-of``
  will add on top;
* a verdict is never alone: each branch's folded ``status`` sits in the same
  object as that tip's task block, with ``concluding`` answering the
  ``satisfying_statuses``/``verifying_statuses`` question
  ``blocked._is_settled`` already asks, pointed at the thread's own tip. A
  verdict is ``null`` only when nothing on the branch ever declared a
  ``status:``; a fold that *refused* between differing equal-distance
  declarations gets its own explicit ``state: "conflicting"`` (the task
  fold's ambiguity posture, via ``chains.fold_field_at_tip``), never
  collapsed into the no-verdict null; a fold that concluded is
  ``state: "resolved"``;
* a fork is never collapsed: there is no thread-level status anywhere, and
  each open tip gets its own branch (its own ``fold_tasks`` list, its own
  branch-local verdict via ``chains.fold_at_tip``);
* the store's capture fact travels with the thread it captures: ``captured``
  names each member with a live capture event in the history store, with the
  event's kind and its ``occurred_at`` when the store holds one (a
  ``followed`` or ``followed-corrected`` edge deliberately carries none —
  §2: display metadata, never ordered or gated on), so H7b's capture line
  reads it instead of opening the store itself.

Nothing here writes — the same tree-hash guarantee every read surface carries.
"""

from __future__ import annotations

from . import blocked as blocked_mod
from . import chains as chains_mod
from . import history as history_mod
from . import lifecycle as lifecycle_mod
from .model import Item, Project

# The derived rows' ONE order, spelled once here for BOTH commands (owner
# decision, 2026-10-11): coverage < verdict < blocked < check < citation <
# fork — the order §5's worklist table lists the kinds in. The per-thread
# block simply never carries a `verdict` or `fork` row; `refdes work`'s
# whole-project block carries all six. Both producers sort by this and both
# renderers group by it, so the two commands can never reorder differently,
# and the block never reorders itself between builds.
_KIND_ORDER = {
    "coverage": 0,
    "verdict": 1,
    "blocked": 2,
    "check": 3,
    "citation": 4,
    "fork": 5,
}

#: The verdict discriminator's two non-null states (owner wording, 2026-10-11
#: fix round: `declared`/`ambiguous` read as the task fold's own postures,
#: which they are not — a verdict either *concluded* something or two
#: equal-distance declarations *conflict*). A null verdict is the third
#: posture and needs no name: nothing on the branch ever declared a status.
#: `refdes work` (H7c) renders these same strings, so they live here once.
VERDICT_RESOLVED = "resolved"
VERDICT_CONFLICTING = "conflicting"

#: The surface wording every thread view shares, spelled once here (the same
#: reason VERDICT_RESOLVED lives here): `refdes thread` (cli.cmd_thread)
#: renders through these, and so does the task pane
#: (docs/design/thread-workbench.md §7a, W5a) — the pane "shows the same
#: facts and wording as that command" by rendering these same strings, not
#: a second spelling that can drift.
TASK_GLYPHS = {"open": "[ ]", "done": "[x]", "dropped": "[-]"}
TASK_GLYPH_UNKNOWN = "[?]"

#: The derived block's heading, without the CLI's trailing colon: `refdes
#: thread` prints `DERIVED_HEADING + ":"`, the pane's <summary> is the bare
#: heading (the task's owner string, 2026-10-11).
DERIVED_HEADING = "Derived (auto clears when fixed)"

#: The derived block's ONE kind order and its per-kind group headings (the
#: owner's words). `refdes work` (#194, `living-notes-h7c-work-cli`, open
#: when W5a was written) adds the same grouping to the CLI and will align
#: these constants with its own; until it merges, this is the one place.
#: A thread's own derived block simply never carries a `verdict` or `fork`
#: row — those kinds belong to a whole-project worklist — but the order
#: names all six so the grouping and the order are spelled once.
DERIVED_GROUP_ORDER = ("coverage", "verdict", "blocked", "check", "citation", "fork")
DERIVED_GROUP_HEADINGS = {
    "coverage": "Coverage",
    "verdict": "Verdicts",
    "blocked": "Blocked",
    "check": "Failing checks",
    "citation": "Citations",
    "fork": "Forks",
}


def verdict_open_suffix(verdict: dict, open_count: int) -> str:
    """§5 rule 4's "never alone" as a suffix on the verdict line: a
    concluding verdict with open tasks at its tip says how many remain
    below, in the owner's wording. Empty for a non-concluding verdict or
    a tip with no open tasks (the verdict then prints alone because there
    is nothing to conclude *against*)."""
    if not verdict["concluding"] or not open_count:
        return ""
    return (
        f", {open_count} open task" + ("" if open_count == 1 else "s")
        + " remaining below"
    )


def entry_label(item: Item) -> str:
    """How every view names an entry: display id, or key when it has none
    (threads.md §2's permanently id-less continuation). Public: `cli.py`'s
    `refdes thread` resolves the requested ref's label with it, so the label
    rule is spelled once (PR #191 review nit)."""
    return item.id or item.key or item.slug


def _date(item: Item) -> str:
    """An entry's own authored date, absolute — or "" when it declared none.
    Read from `fields`, never a clock."""
    value = item.fields.get("date")
    return "" if value is None else str(value)


def _summary(item: Item) -> str:
    # Same posture as render.thread_view's timeline rows.
    return item.fields.get("summary") or (
        "" if item.id else f"entry {item.key}"
    )


def capture_facts(project: Project) -> tuple[dict, str | None]:
    """One read of `history.capture_index` for a whole command run: the
    index, plus — when the store refused to be read — the plain sentence
    naming why the capture lines are missing.

    The failure belongs to the *surface*, not the projection: the
    projection stays silent by design (it must not grow a diagnostics
    shape, and `render.items_json` shares one read with it), so the
    command that renders capture lines owes the reader this sentence
    itself — `cmd_thread` prints it on stderr in text mode and into the
    `--json` payload's `diagnostics` array (the index payload's shape).
    The projection takes the index through its `captures=` parameter, so
    a command that already read it — or `items_json`, which needs the
    same index for its per-item `captured` keys — never parses the event
    store twice in one build.
    """
    try:
        return history_mod.capture_index(project), None
    except (history_mod.HistoryError, OSError) as exc:
        return {}, f"the history store could not be read ({exc})"


def threads_projection(
    project: Project,
    *,
    graph: chains_mod.ChainGraph | None = None,
    captures: dict | None = None,
) -> list[dict]:
    """Every thread in the project, ordered by each thread's root ref, as
    JSON-serialisable dicts — §6's query service, whole-project form.

    The *list* order is the root's label, sort order (§5/§6 order entries
    *within* a thread — `thread_entries`' oldest-first — and mandate nothing
    about ordering threads; the sorted ref is the deterministic choice).

    A thread is a connected component of the `follows:` graph with at least
    one edge in either direction (`chains.is_threaded`'s question): a lone
    entry with no `follows:` either way is not its own thread here, which is
    what keeps a non-threaded project's index payload byte-identical (no
    threads -> no `threads` key at all). `graph` reuses a build-wide
    `chains.build_graph` so repeated projections in one build don't re-parse
    edges.

    Derived rows are read from already-computed build state
    (`project.coverage`, `item.checks`, `project.blocked_chains`,
    `item.citations`), so a caller that has not run the build sees an empty
    derived block — the truth, not a recomputation.

    `captures` is the build's one `capture_facts`/`history.capture_index`
    read, passed down by a caller that needs the same index for its own
    keys (`render.items_json`) so a whole `index` run parses the event
    store once, not twice; by default the projection reads it itself.
    """
    graph = graph if graph is not None else chains_mod.build_graph(project)
    nodes = set(graph.predecessors) | set(graph.successors)
    if not nodes:
        return []
    problems = _derived_problems(project)
    captures = capture_facts(project)[0] if captures is None else captures
    views: list[dict] = []
    seen: set[int] = set()
    for handle in sorted(nodes):
        item = project.items[handle]
        if id(item) in seen:
            continue
        members = chains_mod.thread_entries(project, item, graph=graph)
        seen.update(id(member) for member in members)
        views.append(_thread_view(project, members, graph, problems, captures))
    views.sort(key=lambda view: view["ref"])
    return views


def _captured(members: list[Item], captures: dict) -> list[dict]:
    """Which of a thread's members the history store holds a live capture
    for (§6's capture line, and §2's "a fork captures the predecessor
    snapshot once for each branch event" — the store keeps one event per
    edge, `capture_index` picks the representative per item).

    `kind` is the event's own kind (`followed`, `followed-corrected`, or an
    explicit `captured`); `occurred_at` is null exactly when the event
    carries no clock — which is every `followed` and `followed-corrected`
    edge (`capture_followed` writes both without one, by H2's decision that
    a wall-clock stamp would give one fact different bytes in two checkouts;
    §2: display metadata, never ordered or gated on). Null here means "the
    store does not record when", not "uncaptured"."""
    rows: list[dict] = []
    for member in members:
        hit = captures.get(member.key) if member.key else None
        if hit is None:
            continue
        event, _edited = hit
        rows.append(
            {
                "entry": entry_label(member),
                "kind": str(event["kind"]),
                "occurred_at": event.get("occurred_at"),
            }
        )
    return rows


def _thread_view(
    project: Project,
    members: list[Item],
    graph: chains_mod.ChainGraph,
    problems: dict,
    captures: dict,
) -> dict:
    root = members[0]
    tips = chains_mod.thread_tips(project, root, graph=graph)
    folds = {
        id(tip_tasks.tip): tip_tasks
        for tip_tasks in chains_mod.fold_tasks(project, root, graph=graph)
    }
    branches = [
        {
            "tip": entry_label(tip),
            "date": _date(tip),
            "summary": _summary(tip),
            "verdict": _verdict(project, tip, graph),
            "tasks": _tasks(folds.get(id(tip))),
        }
        for tip in tips
    ]
    return {
        "ref": entry_label(root),
        "entries": [entry_label(member) for member in members],
        "tips": [branch["tip"] for branch in branches],
        "forked": len(branches) != 1,
        "captured": _captured(members, captures),
        "branches": branches,
        "derived": _derived(project, members, problems),
    }


def _tasks(tip_tasks: chains_mod.TipTasks | None) -> dict:
    """One tip's authored task block, keeping fold_tasks' distinct states
    distinct (§5 rule 1: this is *the authors' list*, never merged with the
    derived rows).

    `declared` / `cleared` (an explicit `tasks: []`) / `undeclared` (never
    declared) / `ambiguous` ("task reconciliation required" — no single list
    may be shown) are the fold's own postures; `rows` is null for the latter
    two because there is no list to show, not an empty one. Each open row
    carries `open_since`: the entry whose declaration won and that entry's
    authored date — §5 rule 3, absolute only. A declared list with malformed
    rows stays `declared` and gains `malformed` (the dropped-row count,
    absent when zero): zero *valid* rows is not the author's empty list.
    """
    if tip_tasks is None:
        return {"state": "undeclared", "declared_by": None, "declared_on": None, "rows": None}
    source = tip_tasks.source
    declared_by = entry_label(source) if source is not None else None
    declared_on = _date(source) if source is not None else None
    if tip_tasks.rows is None:
        return {
            "state": "ambiguous" if tip_tasks.ambiguous else "undeclared",
            "declared_by": declared_by,
            "declared_on": declared_on,
            "rows": None,
        }
    rows = []
    malformed = 0
    for row in tip_tasks.rows:
        if not isinstance(row, dict):
            # `build.validate_items` has already reported the malformed row;
            # the projection drops it rather than inventing a shape for it.
            malformed += 1
            continue
        entry = dict(row)
        if entry.get("state") == "open":
            entry["open_since"] = {"entry": declared_by, "date": declared_on}
        rows.append(entry)
    block = {
        # `cleared` is the fold's own posture for the *explicit empty list*,
        # never this list's post-filter emptiness: a declared list whose rows
        # are all malformed IS a declaration (zero valid rows + the count
        # below), and reporting it "cleared" would hide the error behind an
        # empty list that says "the author closed everything".
        "state": "declared" if tip_tasks.rows else "cleared",
        "declared_by": declared_by,
        "declared_on": declared_on,
        "rows": rows,
    }
    if malformed:
        block["malformed"] = malformed
    return block


def _verdict(project: Project, tip: Item, graph: chains_mod.ChainGraph) -> dict | None:
    """The tip's branch-local folded status, in the same object as its tasks
    (§5 rule 4: a verdict never prints alone).

    `chains.fold_field_at_tip` is `resolve_current_with_source`'s own fold
    anchored at this tip — identical answer on a one-tip thread, and the
    branch's own answer on a fork, where a thread-level "current status" does
    not exist. `state` keeps the three postures the (value, source) pair alone
    cannot separate: `VERDICT_RESOLVED` (there is a status, and what it
    says), `VERDICT_CONFLICTING` (entries at the same distance refused — §5
    rule 3's posture for `status`, said as itself and never displayed as
    "nothing concluded"), and — by the verdict being null — no entry on the
    branch ever declared a status at all.
    """
    fold = chains_mod.fold_field_at_tip(project, tip, "status", graph=graph)
    if fold is None or not fold.declared:
        return None
    if fold.ambiguous:
        return {
            "state": VERDICT_CONFLICTING,
            "status": None,
            "declared_by": None,
            "declared_on": None,
            "concluding": False,
        }
    status = fold.value
    return {
        "state": VERDICT_RESOLVED,
        "status": status,
        "declared_by": entry_label(fold.source),
        "declared_on": _date(fold.source),
        "concluding": _concluding(project, tip, status),
    }


def _concluding(project: Project, tip: Item, status) -> bool:
    """`blocked._is_settled`'s question, pointed at the thread's own tip:
    does the tip's type declare `satisfying_statuses:` (or, for a
    verifier-shaped type, `verifying_statuses:`), and is this folded status
    one of them? An unconfigured type concludes nothing."""
    spec = project.types.get(tip.type)
    if spec is None or status is None:
        return False
    allowed = (
        spec.satisfying_statuses
        if spec.satisfying_statuses is not None
        else spec.verifying_statuses
    )
    if allowed is None:
        return False
    return status in allowed


def _derived_problems(project: Project) -> dict:
    """The selection sets every thread's derived rows read from, computed
    once per projection — the lifecycle gate's own predicates (§5: these
    rows ARE what already blocks a release), not a re-derivation.

    Imports are private-by-position, same as render's use of
    `build._key_index`: the definition of "uncovered"/"unverified" (the
    coverable gate, the draft exclusion) lives in `lifecycle`, and a second
    copy here is exactly what §6 forbids.
    """
    return {
        "uncovered": set(lifecycle_mod._rule_uncovered_requirements(project)),
        "unverified": set(lifecycle_mod._rule_unverified_requirements(project)),
        "blocked": blocked_mod.by_item(project),
    }


def _scope(project: Project, members: list[Item]) -> dict[str, Item]:
    """Whose derived rows a thread shows: its members, plus what the
    members' own outgoing links point at (one hop, read through
    `Item.resolved_links` per AGENTS.md — never raw `links`).

    §6's decided example is the rule: a log thread carries
    `coverage REQ-... unverified` (what the log addresses) and
    `citation CMP-... unpinned` (what the log selects) — neither of them a
    thread member. A row whose subject is further away than that is the
    other thread's (or no thread's) to show.
    """
    scope: dict[str, Item] = {entry_label(member): member for member in members}
    for member in members:
        for targets in member.resolved_links.values():
            for ref in targets:
                target = project.item_by_ref(ref)
                if target is not None:
                    scope.setdefault(entry_label(target), target)
    return scope


def _rows_for_subject(project: Project, subject: Item, problems: dict) -> list[dict]:
    """The item-level derived rows for one subject: coverage, checks, blocked
    chains, citations. The single producer of those four kinds — both the
    per-thread derived block (`_derived`, over a thread's scope) and the
    whole-project worklist (`project_derived`, over every local item) read
    them from here, so a gap is never re-derived differently in the two
    places (§6: one query service, no client recomputing it)."""
    rows: list[dict] = []
    coverage = project.coverage.get(subject.id) if subject.id else None
    if coverage is not None:
        # `uncovered` (stage open — nobody has touched it) wins over the
        # broader `unverified` (anything short of verified), the same
        # way §5's table names the sharper problem when both are true.
        if subject.id in problems["uncovered"]:
            rows.append(
                {
                    "kind": "coverage",
                    "ref": entry_label(subject),
                    "problem": "uncovered",
                    "stage": coverage.stage,
                }
            )
        elif subject.id in problems["unverified"]:
            rows.append(
                {
                    "kind": "coverage",
                    "ref": entry_label(subject),
                    "problem": "unverified",
                    "stage": coverage.stage,
                }
            )
    for check in subject.checks:
        if check.ok is False:
            rows.append(
                {
                    "kind": "check",
                    "ref": entry_label(subject),
                    "value": check.value_name,
                    "against": check.against,
                    "actual": check.actual,
                    "limit": check.limit,
                    "detail": check.detail,
                    "margin": check.margin,
                }
            )
    for chain in problems["blocked"].get(entry_label(subject), ()):
        rows.append(
            {
                "kind": "blocked",
                "ref": chain.item_id,
                "path": list(chain.path),
                "root": chain.root_id,
                "root_status": chain.root_status,
                "stale": chain.stale,
            }
        )
    for status in subject.citations:
        if status.state in ("unpinned", "cache_missing"):
            # The two postures `_rule_unpinned_citations` /
            # `_rule_missing_kept_copies` select; "ok" is not a row, and
            # `hash_mismatch`/`missing` are the fetch/verify errors' own
            # diagnostics, not worklist material.
            rows.append(
                {
                    "kind": "citation",
                    "ref": entry_label(subject),
                    "problem": status.state,
                    "path": status.spec.path,
                    "detail": status.detail,
                }
            )
    return rows


def _derived(project: Project, members: list[Item], problems: dict) -> list[dict]:
    rows: list[dict] = []
    for subject in _scope(project, members).values():
        rows.extend(_rows_for_subject(project, subject, problems))
    rows.sort(key=lambda row: (_KIND_ORDER[row["kind"]], row["ref"], str(row)))
    return rows


# The folded verdicts that are an open decision — §5's table row "proposed/
# on-hold verdicts", matched BY STATUS VALUE below (the table enumerates the
# values), MINUS anything rule 4 calls concluding (`not concluding`: rule 4
# pairs a concluding verdict with its tip's open tasks in the authored block
# instead — never a lone worklist row — and a project overlay is free to make
# e.g. `on_hold` satisfying, which the status value alone would not see;
# review #194 W9). `in_progress`/`rejected`/`superseded` are the thread's own
# business, not the "someone still has to decide" gap the table names.
_OPEN_VERDICTS = ("proposed", "on_hold")


def project_derived(
    project: Project,
    *,
    graph: chains_mod.ChainGraph | None = None,
    threads: list[dict] | None = None,
) -> list[dict]:
    """Every derived gap in the project at once — §5's "Generated worklist"
    rows for `refdes work`, computed once over the whole project (not scoped
    per thread, so a gap two threads touch is not listed twice).

    The item-level rows (coverage / check / blocked / citation) are the exact
    same rows the per-thread derived block reads, from `_rows_for_subject`, over
    every local item. The two rows unique to the whole-project listing are read
    from `threads_projection` itself — no fold, coverage stage, or check is
    recomputed: a `verdict` row for each branch whose folded status is an open
    decision (`_OPEN_VERDICTS`) *and* for each branch whose fold *refused*
    (`VERDICT_CONFLICTING` — something has to reconcile it, and it must never
    vanish because its tip has no open task, review #194 W5), and a `fork` row
    for each forked thread naming its own tips. Two threads merged into one
    tip fold the same verdict at it, so verdict rows are listed once per tip.
    `threads` lets a caller that already ran the projection reuse it (and no
    graph is built for it then). Remote citation drift is deliberately absent:
    it is produced only by `citations.refresh`, which is networked and runs
    under `check --refresh` alone — `refdes work` never touches the network."""
    problems = _derived_problems(project)
    rows: list[dict] = []
    for subject in project.local_items:
        rows.extend(_rows_for_subject(project, subject, problems))
    if threads is None:
        # The graph exists only for the projection (review #194 W10): a
        # caller that passes `threads` in hand owes no chain-graph parse.
        threads = threads_projection(
            project, graph=graph if graph is not None else chains_mod.build_graph(project)
        )
    listed_verdicts: set[str] = set()
    for view in threads:
        if view["forked"]:
            rows.append({"kind": "fork", "ref": view["ref"], "tips": list(view["tips"])})
        for branch in view["branches"]:
            verdict = branch["verdict"]
            status: str | None = None
            if verdict is not None:
                if verdict["state"] == VERDICT_CONFLICTING:
                    status = VERDICT_CONFLICTING
                elif (
                    verdict["state"] == VERDICT_RESOLVED
                    and verdict["status"] in _OPEN_VERDICTS
                    and not verdict["concluding"]
                ):
                    status = verdict["status"]
            if status is None or branch["tip"] in listed_verdicts:
                continue
            listed_verdicts.add(branch["tip"])
            rows.append(
                {
                    "kind": "verdict",
                    "ref": branch["tip"],
                    "status": status,
                    "thread": view["ref"],
                }
            )
    rows.sort(key=lambda row: (_KIND_ORDER[row["kind"]], row["ref"], str(row)))
    return rows


def work_projection(
    project: Project,
    *,
    graph: chains_mod.ChainGraph | None = None,
    captures: dict | None = None,
) -> dict:
    """`refdes work`'s whole-project answer: the same `threads_projection` list
    (every thread's tips, authored task blocks, branch-local verdicts) plus the
    whole-project `derived` block, built over one graph so the two halves share
    a parse. This is §6's one query service in its whole-project form — the CLI
    renders it and computes no fold, coverage stage, or check of its own.

    `captures` is read once per command run by the caller and passed through to
    `threads_projection` like `cmd_thread` does (B4's one-read posture), so a
    run never parses the event store twice.

    The two halves are kept in separate keys exactly as §5 rule 1 wants them
    separate in the output: `threads[].branches[].tasks` are the authors' lists
    (per tip), `derived` is the self-closing block, and no row in one is ever
    written into the other."""
    graph = graph if graph is not None else chains_mod.build_graph(project)
    threads = threads_projection(project, graph=graph, captures=captures)
    return {
        "threads": threads,
        "derived": project_derived(project, graph=graph, threads=threads),
    }
