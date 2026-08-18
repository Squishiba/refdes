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
    )


def _suggest(value: str, known) -> str:
    close = difflib.get_close_matches(str(value), sorted(known), n=1, cutoff=0.5)
    return f" Did you mean {close[0]!r}?" if close else ""


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
    render: Callable[[Project, dict[str, str]], str]

    @property
    def all_params(self) -> tuple[str, ...]:
        return self.required + self.optional


def _validate_params(spec: BlockSpec, params: dict[str, str]) -> None:
    for key in params:
        if key not in spec.all_params:
            raise _BlockError(
                f"unknown parameter {key!r}. {spec.name} accepts: "
                + ", ".join(spec.all_params) + "."
            )
    for key in spec.required:
        if key not in params:
            raise _BlockError(f"{spec.name} is missing required parameter {key!r}.")


# --------------------------------------------------------------- {{index}}


def _render_index(project: Project, params: dict[str, str]) -> str:
    type_name = params["type"]
    by_field = params["by"]
    board = params.get("board")

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

    items = [
        item
        for item in project.local_items
        if item.type == type_name and (board is None or item.board == board)
    ]

    groups: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        value = item.fields.get(by_field)
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
            f"<tr><td>{_esc(i.id)}</td><td>{_esc(i.title)}</td></tr>" for i in groups[key]
        )
        parts.append(
            '<table class="index-table"><thead><tr><th>ID</th><th>Title</th></tr>'
            f"</thead><tbody>{rows}</tbody></table>"
        )
    return "".join(parts)


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
    the seam a future blocked_by report (docs/design/standard-library.md §9)
    reuses instead of `{{cascade}}`'s own graceful "already shown" marker,
    since a blocked_by graph is specifically asserted acyclic and a cycle in
    it is a real authoring bug, not a legitimate reconvergence."""

    def __init__(self, from_id: str, to_id: str):
        self.from_id = from_id
        self.to_id = to_id
        super().__init__(f"cycle: {from_id} -> {to_id}")


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
    return _walk(project, root_id, direction, via, via_inverses, depth, visited, on_cycle)


def _walk(
    project: Project,
    current_id: str,
    direction: str,
    via: set[str],
    via_inverses: set[str],
    depth: int,
    visited: set[str],
    on_cycle: str,
) -> list[CascadeNode]:
    if depth <= 0:
        return []
    item = project.items.get(current_id)
    if item is None:
        return []
    edges = item.links if direction == "up" else item.backlinks
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
                    raise CascadeCycleError(current_id, target_id)
                children.append(CascadeNode(target_id, label, already_shown=True))
                continue
            visited.add(target_id)
            sub = _walk(project, target_id, direction, via, via_inverses, depth - 1, visited, on_cycle)
            children.append(CascadeNode(target_id, label, children=sub))
    return children


def _render_node_list(nodes: list[CascadeNode], project: Project) -> str:
    parts = []
    for node in nodes:
        item = project.items.get(node.item_id)
        title = item.title if item else node.item_id
        text = f"{node.verb} {_esc(node.item_id)} — {_esc(title)}"
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


def _render_cascade(project: Project, params: dict[str, str]) -> str:
    root_id = params["from"]
    direction = params["direction"]
    depth_raw = params.get("depth", "3")
    via_raw = params.get("via")

    root_item = project.items.get(root_id)
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


# --------------------------------------------------------------- dispatch

_REGISTRY: dict[str, BlockSpec] = {
    "index": BlockSpec(
        name="index", required=("by", "type"), optional=("board",), render=_render_index
    ),
    "cascade": BlockSpec(
        name="cascade",
        required=("from", "direction"),
        optional=("depth", "via"),
        render=_render_cascade,
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
            html = block_spec.render(project, params)
        except _BlockError as exc:
            project.error(f"{{{{{content}}}}} — {exc}", file=where_file, line=line_no)
            html = f'<p class="block-error">⚠ {_esc(str(exc))}</p>'

        rendered.append(html)
        return placeholder(len(rendered) - 1)

    new_source = BLOCK_LINE_RE.sub(swap, source)
    return new_source, rendered
