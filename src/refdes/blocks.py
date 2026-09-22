"""Generated blocks in narrative pages: `{{index}}`, `{{cascade}}`, and
whatever joins them later.

A small, **fixed** family. Every block takes a closed set of named
parameters, each with one fixed meaning, validated against the resolved
schema at build time. There is no comparison operator, no `and`/`or`, no
wildcard, and no nesting one block inside another -- see docs/blocks.md's
own non-goal section, which exists to be quoted at anyone who proposes one.
A block only ever selects and arranges items that already exist in the
project.

**Scope: narrative pages only, not items** -- calc blocks are the
mirror-image precedent (item-scoped generation lives on items; project-scoped
generation lives on pages). Nothing here is wired into `render_bodies`.

Envelope: `{{name key="value" ...}}`, alone on its own source line -- the
same placement trick calc blocks already use (a token alone on a line
becomes `<p>{{...}}</p>` through markdown-it, found and swapped the same
way `render_bodies` already swaps a calc placeholder). Extraction happens on
raw markdown source, before `md.render`, so a real line number is available
for every diagnostic even though page-level `_linkify` diagnostics today
have none.

An unrecognized block name is left completely untouched -- literal text,
not an error, on the theory it was never meant as a directive (`{{TBD}}`
typed as a note to self keeps working). Once a name *does* match one of the
two below, everything past that point is validated strictly: an unknown
parameter or a missing required one is a build error naming the specific
fix, matching every other diagnostic this tool already produces.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import boards as boards_mod
from . import chains as chains_mod
from . import tree as tree_mod
from .model import Item, Project

# A line that is nothing but one `{{...}}` directive -- its own markdown
# paragraph. `.` doesn't match newline by default, so this only ever matches
# within one line regardless of MULTILINE scanning the whole document.
BLOCK_LINE_RE = re.compile(r'^[ \t]*\{\{(.+?)\}\}[ \t]*$', re.MULTILINE)
# A fenced code block in the *raw* markdown source (```/~~~, any language tag,
# closed by a matching fence) -- extraction happens before md.render (see
# extract_blocks below), so unlike _linkify's PROTECTED_RE (which skips
# already-rendered <pre>/<code>), this has to recognize the fence syntax
# itself. Without this, a doc showing "here's how you write {{index ...}}"
# inside a ```markdown example would have that example executed as a real
# directive -- exactly the trap docs/blocks.md's own examples fell into.
_RAW_FENCE_RE = re.compile(r'^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$', re.DOTALL | re.MULTILINE)
_NAME_TOKEN_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$', re.DOTALL)
# Same key="value"/key=bareword microsyntax as FIGURE_ATTR_RE (build.py) --
# duplicated rather than imported, since build.py imports this module and a
# reverse import would be circular.
_ATTR_RE = re.compile(r'([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|(\S+))')

_GROUPABLE_TYPES = ("text", "enum", "date", "person", "list", "quantity")
_DIRECTIONS = ("down", "up", "both")


class _BlockError(Exception):
    """Raised during one block's own validation/rendering; caught once at
    the dispatch level and turned into a project.error() naming the exact
    directive that failed, plus a visible in-page marker."""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _suggest(value: str, known) -> str:
    close = difflib.get_close_matches(str(value), sorted(known), n=1, cutoff=0.5)
    return f" Did you mean {close[0]!r}?" if close else ""


def _item_tags(item: Item) -> list[str]:
    """An item's tags as a list of strings, whatever shape `tags:` was stored
    in (schema-declared `list`, or a single scalar -- same lenient read
    `refdes ls` uses; duplicated rather than imported for the same circular-
    import reason _ATTR_RE is)."""
    tags = item.fields.get("tags")
    if not tags:
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]


def _parse_params(rest: str) -> dict[str, str]:
    return {
        m.group(1): m.group(2) if m.group(2) is not None else m.group(3)
        for m in _ATTR_RE.finditer(rest)
    }


@dataclass
class BlockSpec:
    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    # `render(project, params, where)` -- `where` is the page's source path, so
    # a block that warns can name the page it warned from
    # (docs/design/candidate-parts.md §3.7). Renderers that never warn accept
    # it and ignore it.
    render: Callable[..., str]
    # The accepted set as the unknown-parameter error lists it. Defaults to
    # required-then-optional; `{{compare}}` overrides it to spell the set in
    # the order its own error message reads (docs/design/candidate-parts.md
    # §3.7), which is not the order the two tuples happen to be written in.
    accepts: tuple[str, ...] | None = None

    @property
    def all_params(self) -> tuple[str, ...]:
        return self.required + self.optional

    @property
    def accepted_set(self) -> tuple[str, ...]:
        return self.accepts if self.accepts is not None else self.all_params


def _validate_params(spec: BlockSpec, params: dict[str, str]) -> None:
    for key in params:
        if key not in spec.all_params:
            raise _BlockError(
                f"unknown parameter {key!r}. {spec.name} accepts: "
                + ", ".join(spec.accepted_set) + "."
            )
    for key in spec.required:
        if key not in params:
            raise _BlockError(f"{spec.name} is missing required parameter {key!r}.")


# --------------------------------------------------------------- {{index}}


def _render_index(project: Project, params: dict[str, str], where: str = "") -> str:
    type_name = params["type"]
    by_field = params["by"]
    board = params.get("board")
    tag = params.get("tag")
    with_subtypes = _subtypes_param(project, params)

    spec = project.types.get(type_name)
    if spec is None:
        raise _BlockError(f"unknown type {type_name!r}.{_suggest(type_name, project.types)}")

    fspec = spec.fields.get(by_field)
    if fspec is None:
        raise _BlockError(
            f"type {type_name!r} has no field {by_field!r}. Declared fields: "
            + ", ".join(sorted(spec.fields)) + "."
        )
    if fspec.type not in _GROUPABLE_TYPES:
        raise _BlockError(
            f"{by_field!r} is type {fspec.type!r}, not a groupable field. index "
            "supports text, enum, date, person, list, and quantity fields."
        )

    if board is not None and board not in project.boards:
        raise _BlockError(f"unknown board {board!r}.{_suggest(board, project.boards)}")

    known_tags = {
        t for item in project.local_items for t in _item_tags(item)
    }
    if tag is not None and tag not in known_tags:
        raise _BlockError(f"unknown tag {tag!r}.{_suggest(tag, known_tags)}")

    # A board's index also lists the members of its `includes:` groups
    # (finding 33), labelled shared; the row builder below adds the label.
    included = boards_mod.included_map(project, board)
    listed_types = {type_name}
    if with_subtypes:
        listed_types |= project.subtype_map.get(type_name, set())
    items = [
        item
        for item in project.local_items
        if item.type in listed_types
        and (board is None or boards_mod.displays(item, board, included))
        and (tag is None or tag in _item_tags(item))
    ]

    chain_graph = chains_mod.build_graph(project)
    groups: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        declared = by_field in item.fields and by_field not in item.inherited_fields
        if declared or not chains_mod.is_threaded(project, item, graph=chain_graph):
            value = item.fields.get(by_field)
        else:
            value = chains_mod.resolve_current(project, item, by_field, graph=chain_graph)
        if value in (None, "", []):
            groups["(unset)"].append(item)
        elif isinstance(value, list):
            for v in value:
                groups[str(v)].append(item)
        else:
            groups[str(value)].append(item)

    if not groups:
        return f'<p class="index-empty">No {type_name} items.</p>'

    for key_items in groups.values():
        key_items.sort(key=lambda i: i.id)

    ordered_keys = _order_group_keys(groups, fspec)
    parts = []
    for key in ordered_keys:
        parts.append(f"<h4>{_esc(key)}</h4>")
        rows = "".join(
            f"<tr><td>{_esc(i.id)}</td><td>{_esc(i.title)}"
            f"{_subtype_note(i, type_name)}"
            f"{_shared_note(i, board, included)}</td></tr>"
            for i in groups[key]
        )
        parts.append(
            '<table class="index-table"><thead><tr><th>ID</th><th>Title</th></tr>'
            f"</thead><tbody>{rows}</tbody></table>"
        )
    return "".join(parts)


def _subtypes_param(project: Project, params: dict[str, str]) -> bool:
    """Whether `{{index}}` lists the type's subtypes alongside it
    (docs/design/extends.md §3.2, §8): the explicit `subtypes="true|false"`
    parameter, else `coverage.group_inherited` -- the one project-wide switch
    for "a subtype is shown under its parent"."""
    value = params.get("subtypes")
    if value is None:
        return project.group_inherited
    if value not in ("true", "false"):
        raise _BlockError(
            f"subtypes must be true or false, got {value!r}."
        )
    return value == "true"


def _subtype_note(item: Item, listed_type: str) -> str:
    """The `(bound)` marker on an index row listed under its parent's type."""
    if item.type == listed_type:
        return ""
    return f' <span class="muted small">({_esc(item.type)})</span>'


def _shared_note(item: Item, board: str | None, included: dict[str, str]) -> str:
    """The `shared, via GRP-...` marker on an index row an `includes:` group
    brought onto this board's page (finding 33); empty for owned items."""
    via = boards_mod.shared_via(item, board, included)
    return f' <span class="muted small">shared, via {_esc(via)}</span>' if via else ""


def _order_group_keys(groups: dict[str, list], fspec) -> list[str]:
    """Enum: the type's own declared choices: order. Date: chronological
    (ISO text sorts chronologically, the same assumption log entries already
    make). Everything else: lexicographic. (unset) always sorts last,
    regardless of the field's type -- see docs/design/index-blocks.md §4."""
    real_keys = [k for k in groups if k != "(unset)"]
    if fspec.type == "enum" and fspec.choices:
        rank = {v: i for i, v in enumerate(fspec.choices)}
        ordered = sorted(real_keys, key=lambda k: (rank.get(k, len(rank)), k))
    else:
        ordered = sorted(real_keys)
    if "(unset)" in groups:
        ordered.append("(unset)")
    return ordered


# ------------------------------------------------------------- {{cascade}}


@dataclass
class CascadeNode:
    item_id: str
    verb: str
    already_shown: bool = False
    children: list["CascadeNode"] = field(default_factory=list)


class CascadeCycleError(Exception):
    """Raised by walk_cascade() when on_cycle="error" and a revisit occurs --
    the seam the blocked_by cascade report (docs/design/standard-library.md
    §9) reuses instead of `{{cascade}}`'s own graceful "already shown"
    marker, since a blocked_by graph is specifically asserted acyclic and a
    cycle in it is a real authoring bug, not a legitimate reconvergence.

    `path` is the full walk from the root down to the closing edge, e.g.
    `["DEC-IO-003", "DEC-IO-001", "DEC-IO-003"]` -- enough to report the
    whole cycle, not just the one edge that happened to close it."""

    def __init__(self, path: list[str]):
        self.path = path
        super().__init__(f"cycle: {' -> '.join(path)}")


def walk_cascade(
    project: Project,
    root_id: str,
    direction: str,
    via: set[str],
    depth: int,
    on_cycle: str = "mark",
) -> list[CascadeNode]:
    """The shared rooted, bounded, cycle-aware walk primitive both
    `{{cascade}}` and (eventually) the blocked_by cascade report are built
    on -- see docs/design/index-blocks.md §6, "Relationship to the
    blocked_by cascade report." `direction` is `"up"` (the item's own
    declared `links:`) or `"down"` (its computed `backlinks:`) -- `"both"`
    is a block-level concern (two independent labeled subtrees), not
    something this primitive does itself: call this once per direction and
    combine the results.

    `via` names *forward* link-type names in every case, even when walking
    down -- the caller never has to know that backlinks are keyed by the
    inverse name; this function resolves that once, internally.

    `on_cycle="mark"` (default, what `{{cascade}}` uses) renders a
    re-visited node once more as a terminal leaf, annotated by the caller.
    `on_cycle="error"` raises `CascadeCycleError` instead -- the option a
    future blocked_by implementation wants, since it treats a cycle as a
    hard build error rather than a legitimate reconvergence.
    """
    visited = {root_id}
    via_inverses = (
        {project.inverse_of[n] for n in via if n in project.inverse_of}
        if direction == "down"
        else set()
    )
    return _walk(project, root_id, direction, via, via_inverses, depth, visited, on_cycle, [root_id])


def _walk(
    project: Project,
    current_id: str,
    direction: str,
    via: set[str],
    via_inverses: set[str],
    depth: int,
    visited: set[str],
    on_cycle: str,
    path: list[str],
) -> list[CascadeNode]:
    if depth <= 0:
        return []
    item = project.item_by_ref(current_id)
    if item is None:
        return []
    # resolved_links and backlinks carry a display id when available or a
    # surrogate key for id-less entries. item_by_ref() accepts both, while
    # raw links may instead hold a DISPLAY@key composite that is not a graph
    # reference.
    edges = item.resolved_links if direction == "up" else item.backlinks
    allowed = via if direction == "up" else via_inverses

    children: list[CascadeNode] = []
    for link_name in sorted(edges):
        if link_name not in allowed:
            continue
        if direction == "up":
            label = project.link_types[link_name].label if link_name in project.link_types else link_name
        else:
            # The raw inverse name, humanized for legible prose in a printed
            # tree -- "satisfied_by" -> "Satisfied by" -- rather than the
            # bare key a CSS text-transform styles elsewhere (item.html.j2's
            # Incoming panel). A printed/archived record needs real text,
            # not a visual-only transform.
            label = link_name.replace("_", " ").capitalize()

        for target_id in sorted(edges[link_name]):
            if target_id in visited:
                if on_cycle == "error":
                    raise CascadeCycleError(path + [target_id])
                children.append(CascadeNode(target_id, label, already_shown=True))
                continue
            visited.add(target_id)
            sub = _walk(
                project, target_id, direction, via, via_inverses, depth - 1,
                visited, on_cycle, path + [target_id],
            )
            children.append(CascadeNode(target_id, label, children=sub))
    return children


def _render_node_list(nodes: list[CascadeNode], project: Project) -> str:
    parts = []
    for node in nodes:
        item = project.item_by_ref(node.item_id)
        display_ref = (item.id or item.key) if item else node.item_id
        title = item.title if item else display_ref
        text = f"{node.verb} {_esc(display_ref)} — {_esc(title)}"
        if node.already_shown:
            parts.append(f'<li>{text} <span class="cascade-seen">(already shown above)</span></li>')
        else:
            inner = _render_node_list(node.children, project) if node.children else ""
            parts.append(f"<li>{text}{inner}</li>")
    return "<ul>" + "".join(parts) + "</ul>"


def _render_branch(label: str, nodes: list[CascadeNode], project: Project, direction: str) -> str:
    inner = (
        _render_node_list(nodes, project)
        if nodes
        else f'<p class="cascade-empty">nothing found (direction="{direction}")</p>'
    )
    return f'<li class="cascade-branch">{label}{inner}</li>'


def _render_cascade(project: Project, params: dict[str, str], where: str = "") -> str:
    root_id = params["from"]
    direction = params["direction"]
    depth_raw = params.get("depth", "3")
    via_raw = params.get("via")

    root_item = project.item_by_id(root_id)
    if root_item is None:
        raise _BlockError(f"{root_id} does not exist.")

    if direction not in _DIRECTIONS:
        raise _BlockError(
            f"unknown direction {direction!r}. cascade accepts: down, up, both."
        )

    try:
        depth = int(depth_raw)
    except (TypeError, ValueError):
        depth = 0
    if depth <= 0:
        raise _BlockError("depth must be a positive integer.")

    if via_raw is not None:
        via_names = [v.strip() for v in via_raw.split(",") if v.strip()]
        for name in via_names:
            if name not in project.link_types:
                raise _BlockError(
                    f"unknown link type {name!r}.{_suggest(name, project.link_types)}"
                )
        via = set(via_names)
    else:
        via = {name for name, spec in project.link_types.items() if spec.trace}

    root_text = f"{_esc(root_id)} — {_esc(root_item.title)}"

    if direction == "both":
        up_nodes = walk_cascade(project, root_id, "up", via, depth)
        down_nodes = walk_cascade(project, root_id, "down", via, depth)
        branches = _render_branch("Upward", up_nodes, project, "up") + _render_branch(
            "Downward", down_nodes, project, "down"
        )
        return f'<ul class="cascade"><li>{root_text}<ul>{branches}</ul></li></ul>'

    nodes = walk_cascade(project, root_id, direction, via, depth)
    if not nodes:
        return (
            f'<ul class="cascade"><li>{root_text}'
            f'<p class="cascade-empty">nothing found (direction="{direction}")</p></li></ul>'
        )
    return f'<ul class="cascade"><li>{root_text}{_render_node_list(nodes, project)}</li></ul>'


# ---------------------------------------------------------------- {{tree}}


def _render_tree(project: Project, params: dict[str, str], where: str = "") -> str:
    """The whole containment forest, optionally narrowed to one board or one
    workspace.

    `via` is deliberately absent. In `{{cascade}}` it names the relation the
    walk follows, and the walk's shape is whatever that relation makes it.
    The tree has no such choice: its whole purpose is the one fixed nesting
    every item already has -- workspace, board, `part_of` group, item -- and
    a `via` would replace the tree with a cascade wearing a hat. Nesting by
    some other relation belongs to `{{cascade}}`; asking the tree for it is
    reported as the unknown parameter it is.
    """
    board = params.get("board")
    workspace = params.get("workspace")
    if board is not None and board not in project.boards:
        raise _BlockError(f"unknown board {board!r}.{_suggest(board, project.boards)}")
    if workspace is not None and workspace not in project.workspaces:
        raise _BlockError(
            f"unknown workspace {workspace!r}."
            f"{_suggest(workspace, project.workspaces)}"
        )

    depth_raw = params.get("depth", str(tree_mod.DEFAULT_DEPTH))
    try:
        open_depth = int(depth_raw)
    except (TypeError, ValueError):
        open_depth = 0
    if open_depth <= 0:
        raise _BlockError("depth must be a positive integer.")

    markup = tree_mod.render_tree_html(
        project, board=board, workspace=workspace, open_depth=open_depth
    )
    if markup == '<ul class="tree"></ul>':
        scope = board or workspace
        who = f"{scope}" if scope else "the project"
        return f'<p class="tree-empty">No items in {who}.</p>'
    return markup


# -------------------------------------------------------------- {{compare}}

# The three states a comparison cell can be in, spelled out once under every
# table (docs/design/candidate-parts.md §3.5): an empty cell reads as "no" to
# a reviewer, and "nobody wrote it down" is a different finding from "it
# fails".
_COMPARE_MISSING = "\u2014"
_COMPARE_LEGEND = (
    '<p class="compare-legend">'
    '<span class="compare-missing">\u2014</span> not specified'
    "&nbsp;&nbsp;&nbsp;&nbsp;pass/fail checked"
    "&nbsp;&nbsp;&nbsp;&nbsp;"
    '<span class="check-error">error</span> check could not be evaluated'
    "</p>"
)
# Without `against=` there are no verdict cells to explain, only the em dash.
_COMPARE_LEGEND_SPEC_ONLY = (
    '<p class="compare-legend">'
    '<span class="compare-missing">\u2014</span> not specified'
    "</p>"
)


def _compare_missing_cell() -> str:
    return f'<td class="compare-missing">{_COMPARE_MISSING}</td>'


def _compare_cell(text: str, css: str = "") -> str:
    return f'<td class="{css}">{_esc(text)}</td>' if css else f"<td>{_esc(text)}</td>"


def _compare_field_text(value) -> str:
    """A field value as table text: a list joins with commas, anything else is
    its own string. Empty in, empty out -- the caller renders the em dash.

    An unset field is None, and `str(None)` is "None": the one string that
    must never reach a cell (docs/design/candidate-parts.md §3.5)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _compare_margin(margin: float | None) -> str:
    """`+88%`, `\u221233%`, `0%` -- integer percent, signed, with the typographic
    minus (U+2212) the spec's own table uses, and no sign on zero
    (docs/design/candidate-parts.md §3.4). None (no notion of margin) renders
    nothing: the verdict alone is the cell."""
    if margin is None:
        return ""
    pct = round(margin * 100)
    if pct > 0:
        return f" +{pct}%"
    if pct < 0:
        return f" \u2212{abs(pct)}%"
    return " 0%"


def _compare_bound_targets(project: Project, bound_ids: list[str]) -> list[tuple[str, str]]:
    """Resolve `against=` to (display id, limit text) pairs, in the order written.

    Only the bound's *text* is read here -- the limit string as authored --
    never parsed. The verdict and margin in each cell come from `item.checks`,
    which `run_checks` already filled (docs/design/candidate-parts.md §3.2).
    """
    targets: list[tuple[str, str]] = []
    for bound_id in bound_ids:
        target = project.item_by_id(bound_id)
        if target is None:
            raise _BlockError(f"{bound_id} does not exist.{_suggest(bound_id, project.items_by_id)}")
        target_spec = project.types.get(target.type)
        if target_spec is None or "limit" not in target_spec.fields:
            raise _BlockError(
                f"{bound_id!r} declares no limit. compare's against= needs a bound "
                "(a type with a 'limit' field)."
            )
        limit_text = str(target.fields.get("limit") or "").strip()
        targets.append((bound_id, f"{bound_id} {limit_text}".strip()))
    return targets


def _compare_columns(
    project: Project, spec, params: dict[str, str], rows: list[Item]
) -> list[tuple[str, str, str]]:
    """The `columns=` list as (header, kind, name) triples, kind in
    {"field", "calc"}. Default: the type's declared `preview:` list, falling
    back to `title` (docs/design/candidate-parts.md §3.4).

    A bare name must be a declared field -- the message is `{{index}}`'s shape
    plus the `calc:` hint, so an author who has seen one has seen both. A
    `calc:` name no row defines is an error naming what the first row does
    define; a name some rows define is legal, and the rows without it render
    the em dash.
    """
    raw = params.get("columns")
    if raw is None:
        names = list(spec.preview) or ["title"]
    else:
        names = [c.strip() for c in raw.split(",") if c.strip()]

    columns: list[tuple[str, str, str]] = []
    for name in names:
        if name.startswith("calc:"):
            calc_name = name[len("calc:"):]
            if rows and not any(calc_name in item.calc_values for item in rows):
                first = rows[0]
                defined = ", ".join(sorted(first.calc_values)) or "no calc values"
                raise _BlockError(
                    f"calc:{calc_name} is not a calc value any row in this selection "
                    f"defines. {first.id} defines: {defined}."
                )
            columns.append((calc_name, "calc", calc_name))
            continue
        if name not in spec.fields:
            raise _BlockError(
                f"type {spec.name!r} has no field {name!r}. Declared fields: "
                + ", ".join(sorted(spec.fields)) + ".\n"
                f"For a calc value, write calc:{name}."
            )
        columns.append((name, "field", name))
    return columns


def _compare_status_filter(spec, params: dict[str, str]) -> list[str] | None:
    """`status=` validated against the type's declared choices; None means
    every status the type declares, which is no filter at all."""
    raw = params.get("status")
    if raw is None:
        return None
    wanted = [s.strip() for s in raw.split(",") if s.strip()]
    status_spec = spec.fields.get("status")
    choices = list(status_spec.choices) if status_spec is not None else []
    for value in wanted:
        if value not in choices:
            raise _BlockError(
                f"type {spec.name!r} has no status {value!r}. Declared choices: "
                + ", ".join(choices) + "."
            )
    return wanted


def _render_compare(project: Project, params: dict[str, str], where: str = "") -> str:
    """The comparison table (docs/design/candidate-parts.md §3).

    Reads `item.checks` -- results `run_checks` already produced -- and formats
    them. It never evaluates a bound, never touches `item._env`, and never
    decides anything: "nobody checked" and "checked and failed" are different
    cells, and only the first is this block's to draw.
    """
    type_name = params["type"]
    spec = project.types.get(type_name)
    if spec is None:
        raise _BlockError(f"unknown type {type_name!r}.{_suggest(type_name, project.types)}")

    bound_ids = [b.strip() for b in params.get("against", "").split(",") if b.strip()]
    if bound_ids and "checks" not in spec.fields:
        raise _BlockError(
            f"type {type_name!r} declares no 'checks' field, so there is nothing to "
            f"compare against {bound_ids[0]}. Drop against=, or compare a type that "
            "declares checks."
        )

    board = params.get("board")
    tag = params.get("tag")
    if board is not None and board not in project.boards:
        raise _BlockError(f"unknown board {board!r}.{_suggest(board, project.boards)}")
    known_tags = {t for item in project.local_items for t in _item_tags(item)}
    if tag is not None and tag not in known_tags:
        raise _BlockError(f"unknown tag {tag!r}.{_suggest(tag, known_tags)}")

    statuses = _compare_status_filter(spec, params)

    # A board's index also lists the members of its `includes:` groups
    # (finding 33); rows are local-only -- an imported component is another
    # project's candidate with another project's checks.
    included = boards_mod.included_map(project, board)
    listed_types = {type_name}
    if _subtypes_param(project, params):
        listed_types |= project.subtype_map.get(type_name, set())
    rows = [
        item
        for item in project.local_items
        if item.type in listed_types
        and (board is None or boards_mod.displays(item, board, included))
        and (tag is None or tag in _item_tags(item))
        and (statuses is None or str(item.fields.get("status")) in statuses)
    ]
    # ID ascending, always: no `order=`, no `sort=` (docs/design/candidate-parts.md
    # §3.3). A table that reorders itself when someone edits a bound turns a
    # review diff into noise; ranking is summary.html's job.
    rows.sort(key=lambda i: i.id or "")

    # Validated before the empty state: a typo'd column or a bound that is not
    # a bound is an authoring error whether or not this selection has rows.
    columns = _compare_columns(project, spec, params, rows)
    bounds = _compare_bound_targets(project, bound_ids)

    if not rows:
        return f'<p class="compare-empty">No {type_name} items.</p>'

    headers = ["ID"] + [header for header, _kind, _name in columns]
    headers += [header for _bound_id, header in bounds]
    if bounds:
        headers.append("Checks")

    checked_bounds: set[str] = set()
    body_rows = []
    for item in rows:
        cells = [f"<td>{_esc(item.id)}</td>"]
        for _header, kind, name in columns:
            if kind == "calc":
                # The formatted result run_calcs already stored -- the one
                # surface a calc value has that is not the raw pint quantity.
                text = item.calc_values.get(name, "")
            else:
                text = _compare_field_text(item.fields.get(name))
            cells.append(_compare_missing_cell() if not text else _compare_cell(text))

        passed = total = 0
        for bound_id, _header in bounds:
            result = next((c for c in item.checks if c.against == bound_id), None)
            if result is None:
                cells.append(_compare_missing_cell())
                continue
            checked_bounds.add(bound_id)
            total += 1
            if result.ok is None:
                cells.append('<td class="check-error">error</td>')
            elif result.ok:
                passed += 1
                cells.append(_compare_cell(f"pass{_compare_margin(result.margin)}"))
            else:
                cells.append(_compare_cell(f"fail{_compare_margin(result.margin)}", "check-fail"))
        if bounds:
            cells.append(
                _compare_missing_cell() if total == 0 else _compare_cell(f"{passed}/{total}")
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    # An all-em-dash column reads as a completed comparison, which is this
    # project's characteristic bug: a build that reports success while the
    # thing is missing (docs/design/candidate-parts.md §3.7).
    for bound_id, _header in bounds:
        if bound_id not in checked_bounds:
            project.warn(
                f"no {type_name} in this selection has a checks: entry against "
                f"{bound_id}. Its column will be empty.",
                file=where,
            )

    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    legend = _COMPARE_LEGEND if bounds else _COMPARE_LEGEND_SPEC_ONLY
    return (
        f'<table class="compare-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>" + legend
    )


# --------------------------------------------------------------- dispatch

_REGISTRY: dict[str, BlockSpec] = {
    "compare": BlockSpec(
        name="compare",
        required=("type",),
        optional=("against", "board", "columns", "status", "subtypes", "tag"),
        accepts=("against", "board", "columns", "status", "subtypes", "tag", "type"),
        render=_render_compare,
    ),
    "index": BlockSpec(
        name="index", required=("by", "type"), optional=("board", "tag", "subtypes"), render=_render_index
    ),
    "cascade": BlockSpec(
        name="cascade",
        required=("from", "direction"),
        optional=("depth", "via"),
        render=_render_cascade,
    ),
    "tree": BlockSpec(
        name="tree",
        required=(),
        optional=("board", "workspace", "depth"),
        render=_render_tree,
    ),
}


def placeholder(index: int) -> str:
    """A token markdown will pass through untouched -- same convention
    calc blocks use (`_placeholder`, build.py), a distinct prefix so the
    two families never collide inside the same rendered page."""
    return f"xxrefdesblock{index}xx"


def extract_blocks(project: Project, source: str, where_file: str) -> tuple[str, list[str]]:
    """Scan raw markdown `source` for `{{name key="value"}}` lines, validate
    and render each recognized one, and replace it with a placeholder token.
    An unrecognized name is left completely untouched.

    Returns `(source_with_placeholders, [rendered_html, ...])` -- the caller
    (`render_pages`) swaps each placeholder for its entry in the returned
    list, in order, immediately after `md.render` and before `_linkify` --
    see this module's own docstring for why that ordering is load-bearing.
    """
    rendered: list[str] = []
    fences = [(m.start(), m.end()) for m in _RAW_FENCE_RE.finditer(source)]

    def swap(match: re.Match) -> str:
        if any(start <= match.start() < end for start, end in fences):
            return match.group(0)  # inside a fenced code block -- an example, not live

        content = match.group(1).strip()
        name_match = _NAME_TOKEN_RE.match(content)
        name = name_match.group(1) if name_match else ""
        block_spec = _REGISTRY.get(name)
        if block_spec is None:
            return match.group(0)  # never meant as a directive -- literal text

        line_no = source.count("\n", 0, match.start()) + 1
        params = _parse_params(name_match.group(2))
        try:
            _validate_params(block_spec, params)
            html = block_spec.render(project, params, where_file)
        except _BlockError as exc:
            project.error(f"{{{{{content}}}}} — {exc}", file=where_file, line=line_no)
            html = f'<p class="block-error">⚠ {_esc(str(exc))}</p>'

        rendered.append(html)
        return placeholder(len(rendered) - 1)

    new_source = BLOCK_LINE_RE.sub(swap, source)
    return new_source, rendered
