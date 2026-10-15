"""Render the resolved project to a static HTML site plus items.json."""

from __future__ import annotations

import errno
import json
import os
import re
import shutil

from jinja2 import Environment, FileSystemLoader

from . import blocked as blocked_mod
from . import boards as boards_mod
from . import build as build_mod
from . import chains as chains_mod
from . import citations as citations_mod
from . import dates
from . import history as history_mod
from . import ids as ids_mod
from . import nav as nav_mod
from . import task_pane as task_pane_mod
from . import theme as theme_mod
from . import threads as threads_mod
from . import tree as tree_mod
from . import vocabulary as vocabulary_mod
from .model import Item, Project

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
ASSET_DIR = os.path.join(TEMPLATE_DIR, "assets")


PAGE_HREF_RE = re.compile(r'href="([a-z0-9][a-z0-9\-_.]*)\.html"')


def _anchorize(html: str, known_slugs: set[str]) -> str:
    """Rewrite per-page links into in-document anchors.

    The multi-page site links `href="con-thm-001.html"`. In the single-document
    render every item is a section on one page, so the same reference has to become
    `href="#con-thm-001"` or it dangles — which is exactly what breaks when you
    print a page-per-item site.
    """

    def swap(match: re.Match) -> str:
        slug = match.group(1)
        if slug in known_slugs:
            return f'href="#{slug}"'
        return match.group(0)

    return PAGE_HREF_RE.sub(swap, html)


_ID_ATTR_RE = re.compile(r'(?<![-\w])id="([^"]*)"')
_CALC_TABLE_ID_RE = re.compile(r'(<table class="calc" id=")(calc-[^"]*)(")')


def _unique_calc_anchors(html: str) -> str:
    """Rename a calc-table anchor that would repeat a `calc-` id on the page.

    Block names are unique per item (docs/design/named-calc-blocks.md
    §11.2), but a merged document -- document.html and its board/workspace
    copies, or a page with two `{{calcblock}}` directives -- renders several
    items' tables into one DOM, where two items naming their block `losses`
    would put `id="calc-losses"` on the page twice. The owner's own page
    always keeps the bare anchor, which is what every `[[ID#calc:name]]` href
    resolves to (they carry the owner's page name, so they resolve there from
    anywhere); on a page that renders the same calc anchor again, the *later*
    occurrence moves to `-2`/`-3`…, never onto an id the page already carries
    (an item can genuinely name a block `losses-2`).

    The rename targets only the exact opening tag `_calc_table_html` emits.
    An `id="` can also be the tail of some other attribute name (`data-id=`,
    `hiddenid=`, the generated `data-where-id=`) or plain escaped text, and
    a value inside such an attribute is not a DOM id -- matching only the
    generated tag keeps this pass from reading or moving anything it does
    not own. The collision inventory (`_ID_ATTR_RE`) is attribute-bounded
    for the same reason: `data-id="calc-losses-2"` must not push a rename
    one suffix further.
    """
    taken = set(_ID_ATTR_RE.findall(html))
    emitted: set[str] = set()

    def swap(match: re.Match) -> str:
        anchor = match.group(2)
        if anchor not in emitted:
            emitted.add(anchor)
            return match.group(0)
        suffix = 2
        while f"{anchor}-{suffix}" in taken or f"{anchor}-{suffix}" in emitted:
            suffix += 1
        renamed = f"{anchor}-{suffix}"
        emitted.add(renamed)
        return f"{match.group(1)}{renamed}{match.group(3)}"

    return _CALC_TABLE_ID_RE.sub(swap, html)


def _figured(project: Project, bodies: list[str]):
    """A `figured(html)` closure for one rendered document: numbers every
    `{id="..."}` figure across `bodies` in that document's own reading order,
    then returns a function that resolves figure-number markers and
    `[[fig:id]]` references against that one document's numbering
    (docs/design/index-blocks.md §9) -- the same per-document posture
    `_anchorize` already takes with cross-item hrefs."""
    numbers = build_mod.assign_figure_numbers(bodies)
    return lambda html: build_mod.resolve_figures(html, project, numbers)


def _in_scope(item: Item, board: str | None, workspace: str | None) -> bool:
    """The one filter every per-board/per-workspace report shares. Callers pass
    at most one of `board`/`workspace` -- both `None` means unscoped."""
    if board is not None and item.board != board:
        return False
    if workspace is not None and item.workspace != workspace:
        return False
    return True


def _date_sort_key(
    project: Project, item: Item, *, newest_first: bool = False
) -> tuple[int, int, str]:
    """Sort valid dates chronologically and keep absent/malformed values last."""
    value = item.fields.get("date")
    if value is None or str(value) == "":
        return (1, 0, item.id)
    try:
        ordinal = dates.parse_date(value, project.date_format).toordinal()
    except (TypeError, ValueError):
        return (1, 0, item.id)
    return (0, -ordinal if newest_first else ordinal, item.id)


def _document_sections(
    project: Project, board: str | None = None, workspace: str | None = None
) -> list[tuple[str, list[Item]]]:
    """Items grouped for linear reading: schema order, log entries by date.

    `board`/`workspace`, when given, scope this to that board's or
    workspace's own local items -- imported items carry neither, so a scoped
    document has no "Imported references" section.
    """
    # `includes:` members join the display (finding 33) -- `_in_scope` alone
    # stays the ownership filter everywhere a number is produced.
    included = boards_mod.included_map(project, board)
    sections: list[tuple[str, list[Item]]] = []
    for type_name, spec in project.types.items():
        items = [
            i
            for i in project.items.values()
            if i.type == type_name
            and not i.external
            and (
                _in_scope(i, board, workspace)
                or (board is not None and i.id in included)
            )
        ]
        if type_name == "log":
            items.sort(key=lambda i: _date_sort_key(project, i))
        else:
            items.sort(key=lambda i: i.id)
        sections.append((spec.plural, items))

    if board is None and workspace is None:
        imported = sorted(
            (i for i in project.items.values() if i.external), key=lambda i: i.id
        )
        if imported:
            sections.append(("Imported references", imported))
    return sections


_STAGE_ORDER = {"open": 0, "addressed": 1, "claimed": 2, "satisfied": 3, "verified": 4}


def _coverage_group_key(project: Project, item: Item) -> str:
    """The type a coverage row is grouped under: the parent type when
    `coverage.group_inherited` is on and the item's type extends one, the
    item's own type otherwise (docs/design/extends.md §4.2). Presentation
    only -- which items participate in coverage is decided upstream."""
    spec = project.types.get(item.type)
    if project.group_inherited and spec is not None and spec.extends:
        return spec.extends
    return item.type


def _coverage_subtype(project: Project, item: Item) -> str:
    """The `(bound)` badge text for a row grouped under its parent, else ""."""
    key = _coverage_group_key(project, item)
    return item.type if key != item.type else ""


def _coverage_sort_key(project: Project):
    """Stage first, then id -- and, only when grouping is on and the project
    actually has subtypes, the group's position in the schema between the two,
    so a subtype's rows sit with their parent's. A project with no `extends:`
    keeps the old ordering exactly."""
    if not (project.group_inherited and project.subtype_map):
        return lambda row: (_STAGE_ORDER.get(row[1].stage, 9), row[0].id)
    rank = {name: n for n, name in enumerate(project.types)}
    return lambda row: (
        _STAGE_ORDER.get(row[1].stage, 9),
        rank.get(_coverage_group_key(project, row[0]), len(rank)),
        row[0].id,
    )


def _coverage_rows(
    project: Project, board: str | None = None, workspace: str | None = None
) -> list[tuple[Item, object]]:
    rows = []
    for item_id, cov in project.coverage.items():
        item = project.item_by_id(item_id)
        if item is not None and _in_scope(item, board, workspace):
            rows.append((item, cov))
    rows.sort(key=_coverage_sort_key(project))
    return rows


def _contract_rows(project: Project, board: str) -> list[tuple[Item, object]]:
    """Board B's conforming contracts: its `conforms_to:` members, per board.

    Listed even when the requirement itself lives on another board -- that is
    the whole point of finding 24 -- so this is NOT scoped by `_in_scope`.
    Empty for a board with no `conforms_to:`, which is what keeps the coverage
    page byte-identical for every project that has never used the key.
    """
    rows = []
    for (item_id, board_name), cov in project.board_coverage.items():
        if board_name != board:
            continue
        item = project.item_by_id(item_id)
        if item is not None:
            rows.append((item, cov))
    rows.sort(key=_coverage_sort_key(project))
    return rows


def _unmet_boards(project: Project) -> dict[str, list[str]]:
    """item id -> boards whose per-board result for it is still short of satisfied."""
    unmet: dict[str, list[str]] = {}
    for (item_id, board_name), cov in project.board_coverage.items():
        if cov.stage in ("satisfied", "verified"):
            continue
        unmet.setdefault(item_id, []).append(board_name)
    return {item_id: sorted(boards) for item_id, boards in unmet.items()}


def _log_entries(
    project: Project, board: str | None = None, workspace: str | None = None
) -> list[Item]:
    included = boards_mod.included_map(project, board)
    return sorted(
        (
            i
            for i in project.local_items
            if i.type == "log"
            and (
                _in_scope(i, board, workspace)
                or (board is not None and i.id in included)
            )
        ),
        key=lambda i: _date_sort_key(project, i),
    )


def _check_state(item: Item) -> str:
    if not item.checks:
        return "none"
    if any(c.ok is False for c in item.checks):
        return "fail"
    if any(c.ok is None for c in item.checks):
        return "unknown"
    return "pass"


_PART_ANCHOR_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _part_anchor(part_number: str) -> str:
    """HTML id for a part number's row on parts.html -- the exact string,
    sanitized to characters an id/URL fragment can hold safely. Used both to
    write the anchor on parts.html and to link to it from a component page,
    so the two always agree."""
    return "part-" + _PART_ANCHOR_RE.sub("-", part_number).strip("-").lower()


def _trace_view(item: Item, project: Project) -> dict:
    """Split an item's links/backlinks into three buckets for the
    Traceability section: `outgoing` (this item's own declarations, minus
    self-inverse verbs), `incoming` (computed backlinks, same exclusion),
    and `self_inverse` -- every link type where `LinkType.inverse ==
    LinkType.name` (`drop_in`/`alternate` today, any future one
    automatically), merged from both `links` and `backlinks` into one
    de-duplicated list per verb.

    docs/design/standard-library.md §11: for a self-inverse verb,
    `links["drop_in"]` and `backlinks["drop_in"]` are the identical
    fact, not two different ones the way "Satisfies"/"Satisfied by" are --
    rendering them as separate Outgoing/Incoming entries would show a reader
    the same claim twice, differing only in which of the two items happened
    to type the YAML.
    """
    def visible_ref(ref: str) -> str:
        target = project.item_by_ref(ref)
        return (target.id or target.key) if target else ref

    self_inverse: dict[str, list[str]] = {}
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    # resolved links and backlinks carry display IDs for named items and
    # surrogate keys for id-less entries. Keep ordinary output byte-identical;
    # an id-less entry renders as its durable key rather than an empty ref.
    for name, targets in item.resolved_links.items():
        refs = [visible_ref(ref) for ref in targets]
        ltype = project.link_types.get(name)
        if ltype is not None and ltype.inverse == name:
            self_inverse.setdefault(name, []).extend(refs)
        else:
            outgoing[name] = refs
    for name, sources in item.backlinks.items():
        refs = [visible_ref(ref) for ref in sources]
        ltype = project.link_types.get(name)
        if ltype is not None and ltype.inverse == name:
            self_inverse.setdefault(name, []).extend(refs)
        else:
            incoming[name] = refs
    return {
        "outgoing": outgoing,
        "incoming": incoming,
        "self_inverse": {name: sorted(set(ids)) for name, ids in self_inverse.items()},
    }


# What the thread panel shows (docs/design/threads.md §8, decided 2026-09-14):
# the verdict fields a thread can conclude -- never the narrative ones
# (`date`, `author`, `summary`, body), which stay in the timeline.
THREAD_VERDICT_FIELDS = ("status", "rationale", "options", "checks")
THREAD_VERDICT_LINKS = ("satisfies", "selects", "constrained_by")


def _entry_ref(item: Item) -> dict:
    """How a thread view names one entry: display id, or key when it has
    none (threads.md §2's permanently id-less continuation)."""
    return {"label": item.id or item.key or item.slug, "href": f"{item.slug}.html"}


def _flat_value(value) -> str:
    """A one-line rendering of a folded field value for the panel's <dd>."""
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_flat_value(val)}" for key, val in value.items())
    if isinstance(value, (list, tuple)):
        return "; ".join(_flat_value(val) for val in value)
    return str(value)


def thread_view(
    item: Item,
    project: Project,
    *,
    graph: chains_mod.ChainGraph | tuple | None = None,
) -> dict | None:
    """The Thread section for an item's own page, or None when it isn't part
    of a thread (threads.md §8's "Rendering" row).

    `graph` is the build's one `chains.build_graph(project)`; `render_site`
    hands it to every page through the `thread_view` template global. Building
    it per page would make a whole-site render quadratic in the item count for
    no benefit, since the graph does not change while the site is written.

    Two parts: the "currently concludes" panel -- the thread's folded value
    of each verdict field and verdict link some entry declares, each
    attributed to the entry it came from -- and a compact timeline of every
    entry in the thread, reusing `log.html`'s timeline markup with this
    page's own entry marked.

    A forked thread (threads.md §6) shows no folded values at all: an
    unmerged fork is not yet a single conclusion. The panel says so plainly
    and names the open tips instead.

    None for an item with no `follows:` edge in either direction, which is
    what keeps every non-thread page byte-identical to before this existed.
    """
    if graph is None:
        graph = chains_mod.build_graph(project)
    if not chains_mod.is_threaded(project, item, graph=graph):
        return None

    entries_in_order = chains_mod.thread_entries(project, item, graph=graph)
    # Forked exactly when the fold has no single tip to fold from: the panel
    # asks `thread_tips`, the same question `_fold` asks, so a page can never
    # conclude something its own fold would refuse to.
    found_tips = chains_mod.thread_tips(project, item, graph=graph)
    forked = len(found_tips) != 1
    rows: list[dict] = []
    if not forked:
        for field in THREAD_VERDICT_FIELDS:
            value, source = chains_mod.resolve_current_with_source(
                project, item, field, graph=graph
            )
            if source is None:
                continue
            rows.append(
                {
                    "name": field,
                    "value": _flat_value(value),
                    "source": _entry_ref(source),
                }
            )
        # One key index for the page's link folds, not one per link name.
        by_key = build_mod._key_index(project)
        for link in THREAD_VERDICT_LINKS:
            targets, source = chains_mod.resolve_current_link_with_source(
                project, item, link, graph=graph, by_key=by_key
            )
            if source is None:
                continue
            rows.append(
                {
                    "name": link,
                    "value": ", ".join(_entry_ref(target)["label"] for target in targets),
                    "source": _entry_ref(source),
                }
            )

    entries = []
    for entry in entries_in_order:
        ref = _entry_ref(entry)
        summary = entry.fields.get("summary") or (
            "" if entry.id else f"entry {entry.key}"
        )
        entries.append(
            {
                **ref,
                "date": entry.fields.get("date", ""),
                "summary": summary,
                "current": entry is item,
            }
        )
    return {
        "forked": forked,
        "tips": [_entry_ref(tip) for tip in found_tips],
        "rows": rows,
        "entries": entries,
    }


def summary_payload(
    project: Project, board: str | None = None, workspace: str | None = None
) -> dict:
    """Everything the at-a-glance view needs, computed once.

    The per-type pages answer "what does this item say". This answers the questions
    you actually ask at a design review: what is closest to breaking, what numbers
    does the design depend on, and what is not traced to anything.

    `board`/`workspace`, when given, scope every table on the page to that
    board's or workspace's own items.
    """
    local = [
        i
        for i in project.items.values()
        if not i.external and _in_scope(i, board, workspace)
    ]

    # Every evaluated check, tightest margin first. A pass at 2% and a pass at 200%
    # are not the same engineering situation, and sorting by margin is what surfaces
    # the difference without anyone having to hunt.
    margin_rows = [
        (item, check)
        for item in local
        for check in item.checks
        if check.ok is not None
    ]
    margin_rows.sort(
        key=lambda row: (row[1].margin is None, row[1].margin if row[1].margin is not None else 0.0)
    )

    # Every number the design computes, in one table.
    calc_rows = [
        (item, line)
        for item in sorted(local, key=lambda i: i.id)
        for line in item.calcs
    ]

    # Items connected to nothing in any direction. Not an error -- a component can
    # legitimately stand alone -- but it is where traceability silently stops.
    #
    # A `checks:` entry is a real dependency that is not a link: a constraint an
    # expression is checked against is traced, even with no edges pointing at it.
    # Counting only links would list such a constraint as untraced, directly
    # contradicting the margins table above.
    checked_against = {
        check.against for i in local for check in i.checks if check.against
    }
    orphans = sorted(
        (
            i
            for i in local
            if not any(i.links.values())
            and not any(i.backlinks.values())
            and i.id not in checked_against
        ),
        key=lambda i: i.id,
    )

    log_entries = sorted(
        (i for i in local if i.type == "log"),
        key=lambda i: _date_sort_key(project, i, newest_first=True),
    )

    type_rows = []
    for type_name, spec in project.types.items():
        if project.group_inherited and spec.extends:
            continue  # counted under its parent's row
        items = [
            i
            for i in local
            if i.type == type_name or _coverage_group_key(project, i) == type_name
        ]
        if not items:
            continue
        covered = [project.coverage[i.id] for i in items if i.id in project.coverage]
        type_rows.append(
            {
                "name": type_name,
                "plural": spec.plural,
                "count": len(items),
                "verified": sum(1 for c in covered if c.stage == "verified"),
                "coverable": len(covered),
            }
        )

    local_ids = {i.id for i in local}
    stage_counts = {"open": 0, "addressed": 0, "claimed": 0, "satisfied": 0, "verified": 0}
    for item_id, cov in project.coverage.items():
        if item_id in local_ids:
            stage_counts[cov.stage] = stage_counts.get(cov.stage, 0) + 1
    total_covered = sum(stage_counts.values())

    evaluated = [c for _i, c in margin_rows]
    with_margin = [c.margin for c in evaluated if c.margin is not None]

    return {
        "item_count": len(local),
        "margin_rows": margin_rows,
        "calc_rows": calc_rows,
        "orphans": orphans,
        "log_entries": log_entries[:10],
        "log_total": len(log_entries),
        "type_rows": type_rows,
        "stage_counts": stage_counts,
        "total_covered": total_covered,
        "checks_total": len(evaluated),
        "checks_failing": sum(1 for c in evaluated if c.ok is False),
        "tightest": min(with_margin) if with_margin else None,
        "calc_errors": sum(1 for _i, line in calc_rows if line.error),
    }


def preview_payload(project: Project) -> dict:
    out = {}
    for item in project.items.values():
        spec = project.types[item.type]
        fields = []
        for name in spec.preview:
            value = item.fields.get(name)
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            text = str(value)
            fields.append(
                {"name": name, "value": text if len(text) <= 160 else text[:157] + "…"}
            )
        out[item.id] = {
            "id": item.id,
            "type": spec.label,
            "title": item.title,
            "href": f"{item.slug}.html",
            "fields": fields,
            "check": _check_state(item),
            # Present only when the item has some, the same "absent key, not
            # null" convention `items_json` uses for the boards registry: a
            # project that records no former ids keeps byte-identical
            # preview data. app.js renders it as a "formerly known as" row.
            **({"former_ids": list(item.former_ids)} if item.former_ids else {}),
        }
    return out


def _citations_json(item: Item) -> dict:
    """Resolved provenance for `item.citations`, grouped by field and ordered by index.

    Deliberately kept separate from `fields` -- `fields[fname][i]` is authored
    intent (path, rev, keep_copy:), this is what it resolved to (sha256, kept_copy,
    pinned). Every entry always carries the same keys, `state` included, so
    "unpinned" and "pinned but not kept" are each a distinct, explicit
    `state` value rather than something a consumer infers from an absent key.
    """
    out: dict[str, list[dict]] = {}
    for status in sorted(item.citations, key=lambda s: (s.spec.field, s.spec.index)):
        out.setdefault(status.spec.field, []).append(
            {
                "path": status.spec.path,
                "state": status.state,
                "pinned": status.state != "unpinned",
                "kept_copy": status.kept_copy,
                "sha256": status.sha256,
                "fetched": status.fetched,
                "local_path": status.local_path,
                "section_page": status.section_page,
                "detail": status.detail,
            }
        )
    return out


def items_json(
    project: Project,
    *,
    graph: chains_mod.ChainGraph | None = None,
    captures: dict | None = None,
    threads: list[dict] | None = None,
) -> dict:
    """The machine-readable export. Anything downstream should read this, not HTML.

    `graph` is the build's one `chains.build_graph(project)`; `render_site`
    hands it down so the `threads` projection never rebuilds it (the same
    one-graph-per-build rule `thread_view` follows above). `captures` is the
    same one-read rule for the event store (PR #197 review E1): when
    `render_site` has already read `history.capture_index` for its task
    panes it hands the result down, and nothing in one render parses the
    store twice; direct callers leave it None and this reads it itself.
    `threads` is the one-projection-per-render rule for the projection
    itself (PR #197 review round 5, P4): `render_site` computes the rows
    once for its task panes and hands the SAME list here, so one render
    projects once; direct callers leave it None and this projects itself.

    The `boards` key and each item's `board` are only present when a project has
    actually declared a `boards:` registry -- so a project that has not adopted
    boards gets byte-identical output to before this feature existed.
    """
    payload: dict = {
        "title": project.title,
        "version": project.version,
    }
    if project.boards:
        payload["boards"] = {
            name: {"label": spec.label, "token": spec.token, "path": spec.path}
            for name, spec in sorted(project.boards.items())
        }
    if project.workspaces:
        payload["workspaces"] = {
            name: {"label": spec.label, "shared": spec.shared, "path": spec.path}
            for name, spec in sorted(project.workspaces.items())
        }

    payload["coverage"] = {
        item_id: {
            "stage": cov.stage,
            "addressed_by": cov.addressed_by,
            "claimed_by": cov.claimed_by,
            "satisfied_by": cov.satisfied_by,
            "verified_by": cov.verified_by,
        }
        for item_id, cov in sorted(project.coverage.items())
    }
    # Phase H3: captured items carry a `captured` / `edited_after_captured`
    # pair so VS Code and the future editor read the fact from the index
    # instead of recomputing it. Uncaptured items get neither key -- the
    # same "absent key, not null" convention as `boards` -- so an
    # uncaptured project's payload stays byte-identical. A store that
    # refuses to be read yields no keys: build's own
    # "edited-after-captured was not checked" warning is already in this
    # payload's `diagnostics`, and the index never fails over the store.
    # Read once here (or handed down by `render_site`, E1) and handed to
    # the thread projection below, so one `index` run parses the event
    # store once, not twice.
    if captures is None:
        try:
            captures = history_mod.capture_index(project)
        except (history_mod.HistoryError, OSError):
            captures = {}
    # Living notes §6 / plan phase H7a: the thread projection, present only
    # when the project has threads at all -- the same "absent key, not null"
    # convention as `boards`, so a project with no `follows:` anywhere keeps
    # a byte-identical payload. H7b/H7c and the task-pane client read this
    # instead of reconstructing the chain (threads_projection is the one
    # fold/tip/derived-row service; see src/refdes/threads.py).
    thread_rows = (
        threads
        if threads is not None
        else threads_mod.threads_projection(project, graph=graph, captures=captures)
    )
    if thread_rows:
        payload["threads"] = thread_rows
    # `doc` appears only where a definition was actually declared (finding 38),
    # so a project that writes no `doc:` keys gets byte-identical output.
    payload["types"] = {
        name: {
            "label": spec.label,
            "plural": spec.plural,
            "prefix": spec.prefix,
            "append_only": spec.append_only,
            **({"doc": spec.doc} if spec.doc else {}),
            "fields": {
                f.name: {
                    "type": f.type,
                    "on_change": f.on_change,
                    "required": f.required,
                    "choices": f.choices,
                    **({"doc": f.doc} if f.doc else {}),
                }
                for f in spec.fields.values()
            },
            "links": spec.links,
        }
        for name, spec in project.types.items()
    }

    # Phase H3: captured items carry a `captured` / `edited_after_captured`
    # pair (the store was read for them above, once, and shared with the
    # thread projection). Uncaptured items get neither key -- the same
    # "absent key, not null" convention as `boards` -- so an uncaptured
    # project's payload stays byte-identical.
    items_out = []
    for item in sorted(project.items.values(), key=lambda i: i.id):
        entry = {
            "id": item.id,
            # A nullable, always-present field keeps the artifact schema
            # stable: `null` means this output came from a read-only
            # (--no-write) load before a local key could be persisted.
            "key": item.key or None,
            "type": item.type,
            "title": item.title,
        }
        if project.boards:
            entry["board"] = item.board
        if project.workspaces:
            entry["workspace"] = item.workspace
        capture = captures.get(item.key) if item.key else None
        if capture is not None:
            event, edited = capture
            entry["captured"] = str(event["id"])
            entry["edited_after_captured"] = edited
        entry.update({
            "fields": item.fields,
            "former_ids": item.former_ids,
            "citations": _citations_json(item),
            "links": item.links,
            "backlinks": item.backlinks,
            "content_hash": item.content_hash,
            "external": item.external,
            "origin": item.origin,
            "source": {"file": item.source_file, "line": item.source_line},
            # `reference` appears only on cross-item reference lines, so
            # every pre-existing export stays byte-identical.
            "calcs": [
                {
                    "name": c.name,
                    # display_expression == expression for every ordinary
                    # line; on a reference line it hides the key half so
                    # the export reads like the rendered table.
                    "expression": c.display_expression,
                    "result": c.result,
                    "bounds": c.bounds,
                    "error": c.error,
                    "line": c.line,
                    **({"reference": c.reference} if c.reference else {}),
                }
                for c in item.calcs
            ],
            "checks": [
                {
                    "value": c.value_name,
                    "against": c.against,
                    "ok": c.ok,
                    "actual": c.actual,
                    "limit": c.limit,
                    "detail": c.detail,
                    "margin": c.margin,
                }
                for c in item.checks
            ],
        })
        items_out.append(entry)
    payload["items"] = items_out

    # Finding 10 Part 1: the next id `refdes id` would hand out for each
    # prefix, so an editor can offer it as a completion while a new item's
    # id is still being typed by hand -- exactly the population id
    # completion (finding 8) doesn't cover, since a brand-new item's id is
    # precisely the one id that doesn't exist yet. Reuses high_water()
    # as-is: no new ledger logic, just one more number than what it already
    # reports as the highest seen per prefix.
    ledger = ids_mod.load_ledger(project)
    payload["next_ids"] = {
        prefix: number + 1
        for prefix, number in sorted(ids_mod.high_water(project, ledger).items())
    }

    payload["diagnostics"] = [
        {
            "level": d.level,
            "message": d.message,
            "file": d.file,
            "line": d.line,
            "item": d.item_id,
        }
        for d in project.diagnostics
    ]
    return payload


MANIFEST_NAME = ".refdes-manifest.json"


def _load_manifest(out_dir: str) -> set[str]:
    path = os.path.join(out_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _asset_file_list(asset_dir: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(asset_dir):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), asset_dir).replace("\\", "/")
            out.append(f"assets/{rel}")
    return out


def _copy_source_refused(exc: OSError, src: str, dest: str) -> bool:
    """Whether a `shutil.copy2` OSError means the *source* refused (True --
    name the asset) or the *destination* did (False -- cli.py's exit-2
    "cannot write the site" refusal owns it; sending the user to chmod the
    project file for a full disk is the same wrong-file bug this whole pass
    exists to kill, in the other direction).

    `shutil` names the file it was working on: opening/stat'ing the source
    carries `src`, opening the destination and `copystat`'s chmod carry
    `dest`. The copy loop's read and write do not (the OSError comes from
    the raw fd operation), so a filename-less OSError is split by errno:
    ENOSPC/EDQUOT/EFBIG/EROFS can only come from a write, so they are the
    destination; the rest -- EIO, EBADF, EFAULT -- can come from the read
    and are resolved for the source. EIO is the honest gap: `write()` can
    fail with EIO too (a storage fault mid-write is filename-less and
    undecidable), and that case takes the asset sentence and exit 1, not
    cli.py's site refusal -- the tie-break names a real file the user can
    inspect and unlinks the partial copy, while a site refusal for a
    source-side EIO would send the user to the output directory for an
    unreadable project file, the bug this split exists to kill.
    (IMAGE-ASSET-007 review, F1; round-5 review, P2.)
    """
    if exc.filename is not None:
        return exc.filename == src
    return exc.errno not in {errno.ENOSPC, errno.EDQUOT, errno.EFBIG, errno.EROFS}


def _copy_project_assets(
    project: Project, out_dir: str, written: set[str], taskpane_enabled: bool = False
) -> None:
    """Copy `project.assets` into `_site/assets/`: source path -> destination
    path (relative to assets/), the latter content-hashed for a resolved
    `<img src>` and identity-mapped for a `site.assets:` directory file (see
    `project.assets`'s own docstring in model.py).

    Runs after the template's own `assets/` copytree, so a project asset whose
    path collides with a name the template itself owns (`style.css`, `app.js`) is
    refused with a build error instead of silently overwriting it -- the same
    guard `render_site` already applies to a page whose slug collides with a
    generated report.
    """
    # `theme.css` is not in ASSET_DIR -- it is generated per project, after this
    # copy -- but it is just as template-owned, and a project directory of that
    # name would otherwise land on top of it. The task-pane assets join that
    # set exactly when this render emits them (and not one project earlier,
    # which would break the no-threads byte-identity the pane promises).
    reserved = (
        set(os.listdir(ASSET_DIR)) if os.path.isdir(ASSET_DIR) else set()
    ) | {theme_mod.THEME_CSS_NAME} | (
        set(TASKPANE_ASSET_NAMES) if taskpane_enabled else set()
    )
    asset_out = os.path.join(out_dir, "assets")
    for rel, dest_rel in sorted(project.assets.items()):
        top = dest_rel.split("/", 1)[0]
        if top in reserved:
            project.error(
                f"asset {rel!r} would be written to assets/{top}, which the site "
                f"template itself uses. Rename the source file or its enclosing "
                f"directory."
            )
            continue
        src = os.path.join(project.root, *rel.split("/"))
        if not os.path.isfile(src):
            continue  # already reported as a build error when the reference was resolved
        if rel in project.unreadable_assets:
            # Already refused this build -- at its reference, by
            # `_process_images` (IMAGE-ASSET-007 review round 3): a
            # second, copy-side sentence telling the author to remove
            # the file contradicts the reference's own advice and makes
            # `check` and `build` disagree on the count for one state.
            # The file stays registered (it resolved); it is simply not
            # published.
            continue
        dest = os.path.join(asset_out, *dest_rel.split("/"))
        # Destination-side failures deliberately sit OUTSIDE the try below:
        # makedirs and every write-path OSError (ENOSPC in the copy loop
        # carries no filename, a refused chmod names `dest`) must reach
        # cli.py's refusal, which names the site directory and exits 2 --
        # IMAGE-ASSET-007 review. Only the *source* read gets the named
        # per-asset error, so this function never sends the user to chmod
        # the wrong file.
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            if not _copy_source_refused(exc, src, dest):
                raise  # destination-side: cli.py's "cannot write the site" owns it
            try:
                # The failure landed mid-copy: `shutil` created `dest` and
                # may have written into it. "This build does not publish
                # it" must not leave the stub behind -- it is not in
                # `written`, so the manifest prune will never claim it
                # (IMAGE-ASSET-007 review round 2).
                os.remove(dest)
            except OSError:
                pass
            # The copy loop serves hashed images too, and those live
            # nowhere in `site.assets:` -- the remedy names their own
            # reference instead (review round 2).
            remedy = (
                "remove it from the site.assets: directory"
                if dest_rel == rel
                else "point the reference at a readable file"
            )
            project.error(
                f"asset {rel!r} cannot be read: {exc.strerror or exc}. Make "
                f"it readable, or {remedy} -- this build does not publish it"
            )
            continue
        written.add(f"assets/{dest_rel}")


def _copy_datasheet_assets(project: Project, out_dir: str, written: set[str]) -> None:
    """Copy `project.datasheet_assets` into `_site/assets/`, flattened.

    Populated only when `publish_datasheets` is on (citations.py) -- source and
    destination differ (`.refdes/copies/<sha256><ext>` -> flattened
    `assets/datasheets/<sha256><ext>`), so this can't reuse
    `_copy_project_assets`'s mirroring copy.
    """
    asset_out = os.path.join(out_dir, "assets")
    for rel, src in sorted(project.datasheet_assets.items()):
        target = f"assets/{rel}"
        if target in written:
            project.error(
                f"published datasheet {rel!r} collides with an existing "
                f"{target}, most likely a site.assets: directory of the same "
                f"name -- rename one of them."
            )
            continue
        if not os.path.isfile(src):
            continue  # already reported as cache_missing when the citation was resolved
        dest = os.path.join(asset_out, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # Same split as `_copy_project_assets` (IMAGE-ASSET-007 review, F4):
        # the source is `.refdes/copies/<sha>`, and an unreadable cached PDF
        # escaping to `cli.py`'s site-write refusal would send the user to
        # chmod their output directory for a cache-file problem.
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            if not _copy_source_refused(exc, src, dest):
                raise  # destination-side: cli.py's "cannot write the site" owns it
            try:
                # Same partial-stub rule as `_copy_project_assets`
                # (IMAGE-ASSET-007 review round 5): "does not publish
                # it" must not leave a truncated PDF in the site.
                os.remove(dest)
            except OSError:
                pass
            project.error(
                f"published datasheet {rel!r} cannot be read: "
                f"{exc.strerror or exc}. Refetch the citation, or make the "
                f"cache entry readable -- this build does not publish it"
            )
            continue
        written.add(target)


def _write_theme_css(project: Project, out_dir: str, written: set[str]) -> None:
    """Emit the project's resolved theme overrides as `assets/theme.css`.

    The generated file redefines tokens and nothing else (theme.py is what
    guarantees that), and it is linked after `assets/style.css` so the cascade
    does the rest. No overrides -- the default theme and no `site: tokens:` --
    means no file at all, and no `<link>` either: an un-themed project's output
    stays byte-for-byte what it was before theming existed.
    """
    palettes = theme_mod.resolve(project.theme, project.theme_tokens)
    if not palettes["light"] and not palettes["dark"]:
        return
    asset_out = os.path.join(out_dir, "assets")
    os.makedirs(asset_out, exist_ok=True)
    target = f"assets/{theme_mod.THEME_CSS_NAME}"
    with open(os.path.join(asset_out, theme_mod.THEME_CSS_NAME), "w", encoding="utf-8") as fh:
        fh.write(theme_mod.render_theme_css(palettes))
    written.add(target)


#: The task pane's own stylesheet and script (docs/design/thread-workbench.md
#: §7a, W5a). They live outside `ASSET_DIR` because the whole-site copytree
#: is unconditional and these two must not be: a project with no threads
#: gets neither file, no `<link>` and no `<script>`, and publishes exactly
#: the bytes it published before the pane existed.
TASKPANE_DIR = os.path.join(TEMPLATE_DIR, "taskpane")
TASKPANE_ASSET_NAMES = ("taskpane.css", "taskpane.js")


def _write_taskpane_assets(out_dir: str, written: set[str], enabled: bool) -> None:
    """Emit the pane's assets only when this render shows a pane anywhere
    (`enabled` = the projection had at least one thread). Same posture as
    `_write_theme_css`: nothing for the project that never asked -- the
    site stays "no build step, works with JavaScript disabled" for every
    project, and here additionally byte-identical for the ones with no
    threads."""
    if not enabled:
        return
    asset_out = os.path.join(out_dir, "assets")
    os.makedirs(asset_out, exist_ok=True)
    for name in TASKPANE_ASSET_NAMES:
        shutil.copyfile(
            os.path.join(TASKPANE_DIR, name), os.path.join(asset_out, name)
        )
        written.add(f"assets/{name}")


def _prune_stale_output(out_dir: str, written: set[str]) -> None:
    """Delete output from a previous build that this build no longer produces.

    A deleted or renamed item must not leave a live, still-linkable page behind.
    Only ever removes files this tool itself wrote and tracked in the manifest --
    never anything else that happens to live in out_dir.
    """
    previous = _load_manifest(out_dir)
    for rel in previous - written:
        path = os.path.join(out_dir, *rel.split("/"))
        if os.path.isfile(path):
            os.remove(path)
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(sorted(written), fh, indent=2)


def _write_html(out_dir: str, written: set[str], name: str, template, **context) -> None:
    """Render `template` to `<out_dir>/<name>`, tracking it in `written` and
    stamping `current_page` into its own context.

    The single seam every HTML page in the site is written through, so
    `current_page` -- which page a template's own render call is for -- is
    never something a call site can forget to pass. Findings 5 and 7 both
    need it: `base.html.j2` compares it against a nav node's `href` to mark
    `aria-current="page"`, and to decide which sidebar group should render
    pre-expanded because the reader is already standing inside it.

    The same seam is where a page's calc-table anchors are made unique
    (`_unique_calc_anchors`): uniqueness is a property of one rendered page,
    and this is the one place that sees a whole page.
    """
    written.add(name)
    context["current_page"] = name
    page_html = _unique_calc_anchors(template.render(**context))
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
        fh.write(page_html)


def render_site(project: Project, draft: bool = False) -> str:
    """`draft` (finding 5): true when this render came from `refdes build
    --dry-run`, i.e. `seal_write=False` was passed to `build()` -- the site
    is real and browsable, only the seal-recording side effect was skipped.
    Threaded through as a template global so every page can say so, the same
    way `check_state`/`coverage_of` already reach every template from here.
    """
    out_dir = os.path.join(project.root, project.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    written: set[str] = set()

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        # autoescape=True, not select_autoescape(["html"]): select_autoescape
        # matches on the template name's SUFFIX, and every template here is
        # named *.html.j2 -- ending in ".j2", not ".html" -- so it returned
        # False for every template and nothing was ever escaped. Every template
        # in this project is HTML, so escaping can simply always be on; the
        # intentional raw-markup sites are already marked | safe below.
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # The theme's generated stylesheet, or "" when there is none. A global
    # rather than a per-call argument because base.html.j2 is the only consumer
    # and every page inherits it; the empty string is what keeps the `<link>`
    # line from rendering at all in an un-themed build.
    _theme_palettes = theme_mod.resolve(project.theme, project.theme_tokens)
    env.globals["theme_css"] = (
        f"assets/{theme_mod.THEME_CSS_NAME}"
        if _theme_palettes["light"] or _theme_palettes["dark"]
        else ""
    )
    env.globals["draft_build"] = draft
    env.globals["check_state"] = _check_state
    env.globals["coverage_of"] = project.coverage.get
    env.globals["blocked_chains_for"] = blocked_mod.by_item(project).get
    env.globals["coverage_subtype"] = lambda item: _coverage_subtype(project, item)
    env.globals["trace_view"] = lambda item: _trace_view(item, project)
    # One `follows:` graph for the whole build, handed to every item page:
    # `thread_view` runs on each one, and rebuilding the graph per page made a
    # site render quadratic in the item count even for projects with no
    # threads at all.
    thread_graph = chains_mod.build_graph(project)
    env.globals["thread_view"] = lambda item: thread_view(item, project, graph=thread_graph)
    # PR #197 review E1: the event-store read the thread projection needs is
    # hoisted here so one whole `render_site` parses it once — the same
    # pass-through `threads_projection(captures=...)` already gives
    # `items_json`, extended to the pane's second projection call below.
    # PR #197 review round 2 (C6): gated on `project.items`, because a project
    # with no items cannot own a thread and returns early below — reading
    # the store on that path would be a store read no consumer ever sees.
    # The E1 test renders a threaded (items-bearing) project, so the hoist
    # still means exactly one read per `render_site` where it can happen.
    task_panes: dict[str, dict] = {}
    thread_rows: list[dict] | None = None
    capture_index: dict = {}
    if project.items:
        try:
            capture_index = history_mod.capture_index(project)
        except (history_mod.HistoryError, OSError):
            capture_index = {}
        # W5a task pane (docs/design/thread-workbench.md §7a): the floating
        # pane's model, computed once per render from
        # `threads.threads_projection` -- the same projection the index
        # payload's `threads` key carries and `refdes thread` renders, so the
        # pane computes no fold, no tip and no derived row of its own and
        # cannot disagree with either. PR #197 review round 5 (P4): the
        # projection runs HERE, once, and the very same rows are handed to
        # `items_json` below as `threads=` -- one render, one projection,
        # pane and payload reading literally the same objects. A project with
        # no `follows:` edge anywhere gets an empty mapping: no pane on any
        # page and no pane assets, published output byte-identical -- the
        # same "absent, not empty" posture as the thread panel itself.
        thread_rows = task_pane_mod.thread_views(
            project, graph=thread_graph, captures=capture_index
        )
        task_panes = task_pane_mod.panes_by_entry(thread_rows)
    env.globals["task_pane"] = lambda item: task_panes.get(task_pane_mod.label(item))
    taskpane_assets = bool(task_panes)
    env.globals["taskpane_assets"] = taskpane_assets
    env.globals["part_anchor"] = _part_anchor
    citations_by_path = citations_mod.by_path(project)
    parts_by_number = citations_mod.by_part_number(project)
    env.globals["parts_usage"] = parts_by_number.get

    # A page called `index` owns index.html; otherwise the item dashboard does. This
    # is what lets a docs-only project render as an ordinary website.
    page_slugs = {page.slug for page in project.pages}
    dashboard_name = "items.html" if "index" in page_slugs else "index.html"
    env.globals["home_href"] = "index.html"
    env.globals["dashboard_href"] = dashboard_name

    previews = preview_payload(project)
    previews_json = json.dumps(previews, ensure_ascii=False)
    # json.dumps does not escape < or >, and this string is embedded verbatim
    # (`| safe`) in a <script id="preview-data"> element in base.html.j2, so an
    # author-controlled title like `</script><script>...</script>` would close
    # the element at parse time and turn the rest of the title into live markup.
    # The escaping has to happen at dump time, not in the template: autoescape
    # would escape the quotes too and break JSON.parse(dataEl.textContent) in
    # app.js, whereas these are valid JSON string escapes, which JSON.parse
    # decodes back to the original characters -- the payload value is unchanged.
    previews_json = previews_json.replace("<", "\\u003c").replace(">", "\\u003e")

    by_type: dict[str, list[Item]] = {}
    for item in sorted(project.items.values(), key=lambda i: i.id):
        by_type.setdefault(item.type, []).append(item)

    failing = [
        (item, check)
        for item in project.items.values()
        for check in item.checks
        if check.ok is False
    ]
    # Coverage, ordered so the work that still needs doing floats to the top.
    coverage_rows = _coverage_rows(project)
    outstanding = [row for row in coverage_rows if row[1].stage != "verified"]

    log_entries = _log_entries(project)

    # Generated reports own these filenames. A page of the same name would be
    # silently clobbered by whichever is written last, so say so instead. Each
    # board and each workspace adds its own scoped set of the same six
    # reports -- schema.py's load-time check already guarantees a board key
    # and a workspace key never collide, so these two updates never fight.
    report_names = (
        "coverage", "log", "document", "summary", "references", "parts", "tree",
        "vocabulary",
    )
    reserved = {*report_names, dashboard_name[: -len(".html")]}
    for board_key in project.boards:
        reserved.update(f"{name}-{board_key}" for name in report_names)
    for workspace_key in project.workspaces:
        reserved.update(f"{name}-{workspace_key}" for name in report_names)
    if project.items:
        keep = []
        for page in project.pages:
            if page.slug in reserved:
                project.error(
                    f"page '{page.slug}.md' would be written to {page.slug}.html, "
                    f"which is a generated report. Rename the page.",
                    file=page.source_file,
                )
            else:
                keep.append(page)
        # Drop it entirely rather than half-including it: leaving it in would put a
        # nav link on every page pointing at the report instead of the page.
        project.pages = keep

    env.globals["nav_tree"] = nav_mod.build_nav(project, dashboard_href=dashboard_name)

    page_tpl = env.get_template("page.html.j2")
    for page in project.pages:
        _write_html(
            out_dir, written, f"{page.slug}.html", page_tpl,
            project=project, page=page, previews_json=previews_json,
            figured=_figured(project, [page.body_html]),
        )

    if project.items:
        index_tpl = env.get_template("index.html.j2")
        _write_html(
            out_dir, written, dashboard_name, index_tpl,
            project=project,
            by_type=by_type,
            failing=failing,
            outstanding=outstanding,
            previews_json=previews_json,
        )
    elif not project.pages:
        project.warn("nothing to render: no items and no pages")

    if not project.items:
        if os.path.isdir(ASSET_DIR):
            shutil.copytree(ASSET_DIR, os.path.join(out_dir, "assets"), dirs_exist_ok=True)
            written.update(_asset_file_list(ASSET_DIR))
        _copy_project_assets(project, out_dir, written, taskpane_assets)
        _copy_datasheet_assets(project, out_dir, written)
        _write_theme_css(project, out_dir, written)
        _write_taskpane_assets(out_dir, written, taskpane_assets)
        _prune_stale_output(out_dir, written)
        return out_dir

    summary_tpl = env.get_template("summary.html.j2")
    _write_html(
        out_dir, written, "summary.html", summary_tpl,
        project=project,
        previews_json=previews_json,
        **summary_payload(project),
    )

    coverage_tpl = env.get_template("coverage.html.j2")
    _write_html(
        out_dir, written, "coverage.html", coverage_tpl,
        project=project,
        coverage_rows=coverage_rows,
        unmet_boards=_unmet_boards(project),
        previews_json=previews_json,
    )

    log_tpl = env.get_template("log.html.j2")
    _write_html(
        out_dir, written, "log.html", log_tpl,
        project=project,
        shared_via={},
        entries=log_entries,
        figured=_figured(project, [entry.body_html for entry in log_entries]),
        previews_json=previews_json,
    )

    references_tpl = env.get_template("references.html.j2")
    _write_html(
        out_dir, written, "references.html", references_tpl,
        project=project,
        shared_via={},
        grouped=citations_by_path,
        previews_json=previews_json,
    )

    parts_tpl = env.get_template("parts.html.j2")
    _write_html(
        out_dir, written, "parts.html", parts_tpl,
        project=project,
        shared_via={},
        parts=parts_by_number,
        previews_json=previews_json,
    )

    item_tpl = env.get_template("item.html.j2")
    for item in project.items.values():
        spec = project.types.get(item.type)
        if spec is None:  # imported item of a type this schema does not declare
            continue
        _write_html(
            out_dir, written, f"{item.slug}.html", item_tpl,
            project=project,
            item=item,
            spec=spec,
            previews_json=previews_json,
            figured=_figured(project, [item.body_html]),
        )

    known_slugs = {item.slug for item in project.items.values()}
    document_tpl = env.get_template("document.html.j2")
    doc_sections = _document_sections(project)
    _write_html(
        out_dir, written, "document.html", document_tpl,
        project=project,
        shared_via={},
        sections=doc_sections,
        anchored=lambda html: _anchorize(html, known_slugs),
        figured=_figured(
            project, [item.body_html for _label, items in doc_sections for item in items]
        ),
        previews_json=previews_json,
    )

    tree_tpl = env.get_template("tree.html.j2")
    _write_html(
        out_dir, written, "tree.html", tree_tpl,
        project=project,
        tree_html=tree_mod.render_tree_html(project),
        previews_json=previews_json,
    )

    # Project-wide like the tree: the schema does not narrow to a board, so
    # there is exactly one vocabulary page and `scope_reports` says so.
    vocabulary_tpl = env.get_template("vocabulary.html.j2")
    _write_html(
        out_dir, written, "vocabulary.html", vocabulary_tpl,
        project=project,
        vocabulary_html=vocabulary_mod.render_html(project),
        previews_json=previews_json,
    )

    written.add("items.json")

    # One document/coverage/log/summary set per registered board, scoped to that
    # board's own items -- the unscoped pages above are unaffected either way.
    #
    # `nav.scope_reports` decides *which* of them exist, and the nav builds its
    # links from the same call, so the two cannot disagree. A board with no
    # items at all gets none: it used to get a full set of six pages
    # describing nothing, three of which the nav then declined to link, so
    # they were unreachable as well as empty.
    for board_key, board_spec in project.boards.items():
        board_reports = nav_mod.scope_reports(project, board=board_key)
        if not board_reports:
            continue
        # `{item id: group id}` for the items this board displays via
        # `includes:` but does not own -- the templates label them with it.
        board_shared = boards_mod.included_map(project, board_key)
        board_sections = _document_sections(project, board=board_key)
        board_known_slugs = {
            item.slug for _label, items in board_sections for item in items
        }
        _write_html(
            out_dir, written, f"document-{board_key}.html", document_tpl,
            project=project,
            board=board_spec,
            shared_via=board_shared,
            sections=board_sections,
            anchored=lambda html, slugs=board_known_slugs: _anchorize(html, slugs),
            figured=_figured(
                project, [item.body_html for _label, items in board_sections for item in items]
            ),
            previews_json=previews_json,
        )

        _write_html(
            out_dir, written, f"coverage-{board_key}.html", coverage_tpl,
            project=project,
            board=board_spec,
            coverage_rows=_coverage_rows(project, board=board_key),
            contract_rows=_contract_rows(project, board_key),
            conforms_to=board_spec.conforms_to,
            previews_json=previews_json,
        )

        if "log" in board_reports:
            board_log_entries = _log_entries(project, board=board_key)
            _write_html(
                out_dir, written, f"log-{board_key}.html", log_tpl,
                project=project,
                board=board_spec,
                shared_via=board_shared,
                entries=board_log_entries,
                figured=_figured(
                    project, [entry.body_html for entry in board_log_entries]
                ),
                previews_json=previews_json,
            )

        if "references" in board_reports:
            _write_html(
                out_dir, written, f"references-{board_key}.html", references_tpl,
                project=project,
                board=board_spec,
                shared_via=board_shared,
                grouped=citations_mod.by_path(project, board=board_key),
                previews_json=previews_json,
            )

        if "parts" in board_reports:
            _write_html(
                out_dir, written, f"parts-{board_key}.html", parts_tpl,
                project=project,
                board=board_spec,
                shared_via=board_shared,
                parts=citations_mod.by_part_number(project, board=board_key),
                previews_json=previews_json,
            )

        _write_html(
            out_dir, written, f"summary-{board_key}.html", summary_tpl,
            project=project,
            board=board_spec,
            previews_json=previews_json,
            **summary_payload(project, board=board_key),
        )

        if "tree" in board_reports:
            _write_html(
                out_dir, written, f"tree-{board_key}.html", tree_tpl,
                project=project,
                board=board_spec,
                tree_html=tree_mod.render_tree_html(project, board=board_key),
                previews_json=previews_json,
            )

    # Same reports, one set per registered workspace, scoped to that
    # workspace's own items -- mirrors the per-board loop above exactly,
    # `nav.scope_reports` gate included.
    for workspace_key, workspace_spec in project.workspaces.items():
        ws_reports = nav_mod.scope_reports(project, workspace=workspace_key)
        if not ws_reports:
            continue
        ws_sections = _document_sections(project, workspace=workspace_key)
        ws_known_slugs = {
            item.slug for _label, items in ws_sections for item in items
        }
        _write_html(
            out_dir, written, f"document-{workspace_key}.html", document_tpl,
            project=project,
            workspace=workspace_spec,
            shared_via={},
            sections=ws_sections,
            anchored=lambda html, slugs=ws_known_slugs: _anchorize(html, slugs),
            figured=_figured(
                project, [item.body_html for _label, items in ws_sections for item in items]
            ),
            previews_json=previews_json,
        )

        _write_html(
            out_dir, written, f"coverage-{workspace_key}.html", coverage_tpl,
            project=project,
            workspace=workspace_spec,
            coverage_rows=_coverage_rows(project, workspace=workspace_key),
            unmet_boards=_unmet_boards(project),
            previews_json=previews_json,
        )

        if "log" in ws_reports:
            ws_log_entries = _log_entries(project, workspace=workspace_key)
            _write_html(
                out_dir, written, f"log-{workspace_key}.html", log_tpl,
                project=project,
                workspace=workspace_spec,
                shared_via={},
                entries=ws_log_entries,
                figured=_figured(
                    project, [entry.body_html for entry in ws_log_entries]
                ),
                previews_json=previews_json,
            )

        if "references" in ws_reports:
            _write_html(
                out_dir, written, f"references-{workspace_key}.html", references_tpl,
                project=project,
                workspace=workspace_spec,
                shared_via={},
                grouped=citations_mod.by_path(project, workspace=workspace_key),
                previews_json=previews_json,
            )

        if "parts" in ws_reports:
            _write_html(
                out_dir, written, f"parts-{workspace_key}.html", parts_tpl,
                project=project,
                workspace=workspace_spec,
                shared_via={},
                parts=citations_mod.by_part_number(project, workspace=workspace_key),
                previews_json=previews_json,
            )

        _write_html(
            out_dir, written, f"summary-{workspace_key}.html", summary_tpl,
            project=project,
            workspace=workspace_spec,
            previews_json=previews_json,
            **summary_payload(project, workspace=workspace_key),
        )

        if "tree" in ws_reports:
            _write_html(
                out_dir, written, f"tree-{workspace_key}.html", tree_tpl,
                project=project,
                workspace=workspace_spec,
                tree_html=tree_mod.render_tree_html(project, workspace=workspace_key),
                previews_json=previews_json,
            )

    with open(os.path.join(out_dir, "items.json"), "w", encoding="utf-8") as fh:
        json.dump(
            items_json(
                project,
                graph=thread_graph,
                captures=capture_index,
                threads=thread_rows,
            ),
            fh,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    asset_out = os.path.join(out_dir, "assets")
    if os.path.isdir(ASSET_DIR):
        shutil.copytree(ASSET_DIR, asset_out, dirs_exist_ok=True)
        written.update(_asset_file_list(ASSET_DIR))
    _copy_project_assets(project, out_dir, written, taskpane_assets)
    _copy_datasheet_assets(project, out_dir, written)
    _write_theme_css(project, out_dir, written)
    _write_taskpane_assets(out_dir, written, taskpane_assets)

    _prune_stale_output(out_dir, written)
    return out_dir
