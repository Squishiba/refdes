"""The thread-view projection: one per-thread view of a whole project.

docs/design/living-notes.md §5 (the five binding rules as *output structure*)
and §6 (one query service every surface reads, so a client "must not
reconstruct the chain itself"); plan phase H7a builds this projection and the
index `threads` key, and H7b/H7c (the `refdes thread` / `refdes work`
commands) and the task-pane client (thread-workbench.md §7a) are consumers of
this one function — none of them computes its own fold.

The shape carries §5's decisions, not a rendering of them:

* two structurally separate groups — authored task lists live per tip in
  ``branches[].tasks`` (the `chains.fold_tasks` rows verbatim), derived rows
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
  ``blocked._is_settled`` already asks, pointed at the thread's own tip;
* a fork is never collapsed: there is no thread-level status anywhere, and
  each open tip gets its own branch (its own ``fold_tasks`` list, its own
  branch-local verdict via ``chains.fold_at_tip``).

Nothing here writes — the same tree-hash guarantee every read surface carries.
"""

from __future__ import annotations

from . import blocked as blocked_mod
from . import chains as chains_mod
from . import lifecycle as lifecycle_mod
from .model import Item, Project

# Derived rows sort coverage < check < blocked < citation, then by ref —
# the order §5's worklist table lists them in, so the block never reorders
# itself between builds.
_KIND_ORDER = {"coverage": 0, "check": 1, "blocked": 2, "citation": 3}


def _label(item: Item) -> str:
    """How every view names an entry: display id, or key when it has none
    (threads.md §2's permanently id-less continuation)."""
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


def threads_projection(
    project: Project,
    *,
    graph: chains_mod.ChainGraph | None = None,
) -> list[dict]:
    """Every thread in the project, oldest-root first, as JSON-serialisable
    dicts — §6's query service, whole-project form.

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
    """
    graph = graph if graph is not None else chains_mod.build_graph(project)
    nodes = set(graph.predecessors) | set(graph.successors)
    if not nodes:
        return []
    problems = _derived_problems(project)
    views: list[dict] = []
    seen: set[int] = set()
    for handle in sorted(nodes):
        item = project.items[handle]
        if id(item) in seen:
            continue
        members = chains_mod.thread_entries(project, item, graph=graph)
        seen.update(id(member) for member in members)
        views.append(_thread_view(project, members, graph, problems))
    views.sort(key=lambda view: view["ref"])
    return views


def _thread_view(
    project: Project,
    members: list[Item],
    graph: chains_mod.ChainGraph,
    problems: dict,
) -> dict:
    root = members[0]
    tips = chains_mod.thread_tips(project, root, graph=graph)
    folds = {
        id(tip_tasks.tip): tip_tasks
        for tip_tasks in chains_mod.fold_tasks(project, root, graph=graph)
    }
    branches = [
        {
            "tip": _label(tip),
            "date": _date(tip),
            "summary": _summary(tip),
            "verdict": _verdict(project, tip, graph),
            "tasks": _tasks(folds.get(id(tip))),
        }
        for tip in tips
    ]
    return {
        "ref": _label(root),
        "entries": [_label(member) for member in members],
        "tips": [branch["tip"] for branch in branches],
        "forked": len(branches) != 1,
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
    authored date — §5 rule 3, absolute only.
    """
    if tip_tasks is None:
        return {"state": "undeclared", "declared_by": None, "declared_on": None, "rows": None}
    source = tip_tasks.source
    declared_by = _label(source) if source is not None else None
    declared_on = _date(source) if source is not None else None
    if tip_tasks.rows is None:
        return {
            "state": "ambiguous" if tip_tasks.ambiguous else "undeclared",
            "declared_by": declared_by,
            "declared_on": declared_on,
            "rows": None,
        }
    rows = []
    for row in tip_tasks.rows:
        if not isinstance(row, dict):
            # `build.validate_items` has already reported the malformed row;
            # the projection drops it rather than inventing a shape for it.
            continue
        entry = dict(row)
        if entry.get("state") == "open":
            entry["open_since"] = {"entry": declared_by, "date": declared_on}
        rows.append(entry)
    return {
        "state": "declared" if rows else "cleared",
        "declared_by": declared_by,
        "declared_on": declared_on,
        "rows": rows,
    }


def _verdict(project: Project, tip: Item, graph: chains_mod.ChainGraph) -> dict | None:
    """The tip's branch-local folded status, in the same object as its tasks
    (§5 rule 4: a verdict never prints alone).

    `chains.fold_at_tip` is `resolve_current_with_source`'s own fold anchored
    at this tip — identical answer on a one-tip thread, and the branch's own
    answer on a fork, where a thread-level "current status" does not exist.
    """
    status, source = chains_mod.fold_at_tip(project, tip, "status", graph=graph)
    if source is None:
        return None
    return {
        "status": status,
        "declared_by": _label(source),
        "declared_on": _date(source),
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
    scope: dict[str, Item] = {_label(member): member for member in members}
    for member in members:
        for targets in member.resolved_links.values():
            for ref in targets:
                target = project.item_by_ref(ref)
                if target is not None:
                    scope.setdefault(_label(target), target)
    return scope


def _derived(project: Project, members: list[Item], problems: dict) -> list[dict]:
    rows: list[dict] = []
    for subject in _scope(project, members).values():
        coverage = project.coverage.get(subject.id) if subject.id else None
        if coverage is not None:
            # `uncovered` (stage open — nobody has touched it) wins over the
            # broader `unverified` (anything short of verified), the same
            # way §5's table names the sharper problem when both are true.
            if subject.id in problems["uncovered"]:
                rows.append(
                    {"kind": "coverage", "ref": _label(subject), "problem": "uncovered", "stage": coverage.stage}
                )
            elif subject.id in problems["unverified"]:
                rows.append(
                    {"kind": "coverage", "ref": _label(subject), "problem": "unverified", "stage": coverage.stage}
                )
        for check in subject.checks:
            if check.ok is False:
                rows.append(
                    {
                        "kind": "check",
                        "ref": _label(subject),
                        "value": check.value_name,
                        "against": check.against,
                        "actual": check.actual,
                        "limit": check.limit,
                        "detail": check.detail,
                        "margin": check.margin,
                    }
                )
        for chain in problems["blocked"].get(_label(subject), ()):
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
                        "ref": _label(subject),
                        "problem": status.state,
                        "path": status.spec.path,
                        "detail": status.detail,
                    }
                )
    rows.sort(key=lambda row: (_KIND_ORDER[row["kind"]], row["ref"], str(row)))
    return rows
