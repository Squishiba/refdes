"""The editor's filtered item query (docs/design/browser-editor.md, Filtering).

One rule governs everything here: answers come from the **built** project in
the in-memory snapshot, never from a file scan. Coverage stage, blocked state,
resolved links, and check verdicts only exist after `build()`, and a list that
disagreed with the report page would be worse than no list.

Semantics, fixed so the API, the URL, and the UI agree:

- every filter is a single value; filters **AND** together;
- matching follows `refdes ls` where that command already has an equivalent:
  `type`/`board` exact, `file` exact on the slash-normalized project-relative
  source path, `tag` a case-insensitive substring of any tag, `q` a
  case-insensitive substring of title and tags joined;
- `stage` matches the coverage stage exactly (only coverable items have one);
- `check` is `none|pass|fail|unknown`, the same rollup `items.json` reports;
- `blocked` is `yes|no` over `project.blocked_chains` (a declared
  `blocked_by:` edge, whatever the chain depth);
- `links_to`/`linked_from` name a target item (display id or surrogate key)
  and match resolved links/backlinks under any verb; `missing_verb` names a
  link verb and matches items whose type declares it with no resolved target;
- a bad value is a 400, never a silently-empty list.

Facet counts are cross-filtered: the count for a facet value is how many items
match that value *plus every other active filter* — the number a checkbox in
the sidebar has to show to be honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import Item, Project

FILTER_PARAMS = (
    "type",
    "board",
    "workspace",
    "tag",
    "file",
    "stage",
    "check",
    "blocked",
    "links_to",
    "linked_from",
    "missing_verb",
    "q",
)
STAGES = ("open", "addressed", "claimed", "satisfied", "verified")
CHECK_STATES = ("none", "pass", "fail", "unknown")
BLOCKED_VALUES = ("yes", "no")
DEFAULT_LIMIT = 500
MAX_LIMIT = 5000


class FilterError(ValueError):
    """A query parameter whose value cannot be honored. Carries the HTTP status
    to return (always 400) and a message safe to show the author."""

    def __init__(self, message: str):
        super().__init__(message)
        self.status = 400


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _norm_file(value: str) -> str:
    return value.replace("\\", "/")


def item_tags(item: Item) -> list[str]:
    """The same tag read `refdes ls` uses (`cli._item_tags`)."""
    tags = item.fields.get("tags")
    if not tags:
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]


def check_state(item: Item) -> str:
    """The same rollup `render._check_state`/`items.json` report."""
    if not item.checks:
        return "none"
    if any(c.ok is False for c in item.checks):
        return "fail"
    if any(c.ok is None for c in item.checks):
        return "unknown"
    return "pass"


@dataclass
class Filters:
    values: dict[str, str] = field(default_factory=dict)
    # derived once per query: refs of the item named by links_to/linked_from
    _link_refs: dict[str, str] = field(default_factory=dict, repr=False)

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def as_query(self) -> dict[str, str]:
        """The filter state as URL query pairs — what the UI writes into the
        address bar, and what re-parsing must return unchanged."""
        return dict(self.values)

    def stage_of(self, project: Project, item: Item) -> str | None:
        cov = project.coverage.get(item.id) if item.id else None
        return cov.stage if cov is not None else None

    def blocked_ids(self, project: Project) -> set[str]:
        return {chain.item_id for chain in project.blocked_chains}

    def _target_ref(self, project: Project, name: str) -> str | None:
        value = self.values.get(name)
        if value is None:
            return None
        if name in self._link_refs:
            return self._link_refs[name]
        target = project.item_by_ref(value)
        if target is None:
            raise FilterError(f"{name}: no item matches {value!r}")
        ref = target.id or target.key
        self._link_refs[name] = ref
        return ref

    def matches(self, project: Project, item: Item) -> bool:
        v = self.values
        if "type" in v and item.type != v["type"]:
            return False
        if "board" in v and item.board != v["board"]:
            return False
        if "workspace" in v and item.workspace != v["workspace"]:
            return False
        if "file" in v and _norm_file(item.source_file) != _norm_file(v["file"]):
            return False
        if "tag" in v:
            needle = v["tag"].lower()
            if not any(needle in t.lower() for t in item_tags(item)):
                return False
        if "q" in v:
            haystack = " ".join([item.title, *item_tags(item)]).lower()
            if v["q"].lower() not in haystack:
                return False
        if "stage" in v:
            stage = self.stage_of(project, item)
            if stage is None or stage != v["stage"]:
                return False
        if "check" in v and check_state(item) != v["check"]:
            return False
        if "blocked" in v:
            is_blocked = (item.id or item.key) in self.blocked_ids(project)
            if is_blocked != (v["blocked"] == "yes"):
                return False
        if "links_to" in v:
            ref = self._target_ref(project, "links_to")
            if ref not in {t for targets in item.resolved_links.values() for t in targets}:
                return False
        if "linked_from" in v:
            ref = self._target_ref(project, "linked_from")
            if ref not in {t for targets in item.backlinks.values() for t in targets}:
                return False
        if "missing_verb" in v:
            verb = v["missing_verb"]
            spec = project.types.get(item.type)
            if spec is None or verb not in spec.links:
                return False
            if item.resolved_links.get(verb):
                return False
        return True


def parse_filters(project: Project, query: dict[str, list[str]]) -> Filters:
    """Build a `Filters` from a parsed query string. Unknown parameters are
    ignored (forward-compatible); known ones are validated here so a typo is a
    400 rather than an empty list."""
    values: dict[str, str] = {}
    for name in FILTER_PARAMS:
        value = _first(query, name)
        if value is None:
            continue
        if name == "stage" and value not in STAGES:
            raise FilterError(f"stage must be one of {', '.join(STAGES)}")
        if name == "check" and value not in CHECK_STATES:
            raise FilterError(f"check must be one of {', '.join(CHECK_STATES)}")
        if name == "blocked" and value not in BLOCKED_VALUES:
            raise FilterError(f"blocked must be one of {', '.join(BLOCKED_VALUES)}")
        if name == "missing_verb":
            spec = project.types.get(value)
            declared = spec is not None and bool(spec.links)
            if not declared and value not in project.link_types:
                raise FilterError(f"missing_verb: no link verb {value!r} in this project")
        values[name] = value
    filters = Filters(values=values)
    for name in ("links_to", "linked_from"):
        if name in values:
            filters._target_ref(project, name)  # validates now, caches the ref
    return filters


def _sort_key(project: Project, item: Item) -> tuple:
    return (item.type, item.id, item.key)


def apply_filters(project: Project, filters: Filters) -> list[Item]:
    items = [item for item in project.items.values() if filters.matches(project, item)]
    items.sort(key=lambda item: _sort_key(project, item))
    return items


# -- facet value extractors ------------------------------------------------
# Each returns the value(s) this item contributes to that facet, or None when
# the item is outside the facet's domain entirely (a non-coverable item has no
# coverage stage at all — it is not "open").

def _f_type(project: Project, item: Item) -> list[str]:
    return [item.type]


def _f_board(project: Project, item: Item) -> list[str]:
    return [item.board] if item.board else []


def _f_workspace(project: Project, item: Item) -> list[str]:
    return [item.workspace] if item.workspace else []


def _f_tag(project: Project, item: Item) -> list[str]:
    return item_tags(item)


def _f_file(project: Project, item: Item) -> list[str]:
    return [_norm_file(item.source_file)] if item.source_file else []


def _f_stage(project: Project, item: Item) -> list[str]:
    cov = project.coverage.get(item.id) if item.id else None
    return [cov.stage] if cov is not None else []


def _f_check(project: Project, item: Item) -> list[str]:
    return [check_state(item)]


def _f_blocked(project: Project, item: Item) -> list[str]:
    blocked = (item.id or item.key) in {c.item_id for c in project.blocked_chains}
    return ["yes" if blocked else "no"]


_FACETS = {
    "type": _f_type,
    "board": _f_board,
    "workspace": _f_workspace,
    "tag": _f_tag,
    "file": _f_file,
    "stage": _f_stage,
    "check": _f_check,
    "blocked": _f_blocked,
}


def facet_counts(
    project: Project, filters: Filters
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """`{facet: {value: count}}` plus `{facet: matched_total}`.

    Cross-filtered: a facet's counts ignore only its own filter. Computed with
    one pass per facet over the item list — at this project's scale (the
    design's rebuild baseline is a ~1s full build) that is cheaper and far
    simpler than an incremental aggregate.
    """
    all_items = sorted(project.items.values(), key=lambda item: _sort_key(project, item))
    counts: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for name, extract in _FACETS.items():
        others = Filters(values={k: v for k, v in filters.values.items() if k != name})
        try:
            matched = [item for item in all_items if others.matches(project, item)]
        except FilterError:
            # Another facet's link target is bad; `parse_filters` already
            # rejected that query, so this is unreachable in practice.
            matched = []
        totals[name] = len(matched)
        tally: dict[str, int] = {}
        for item in matched:
            for value in extract(project, item):
                tally[value] = tally.get(value, 0) + 1
        counts[name] = tally
    return counts, totals


def handle_map(project: Project) -> dict[int, str]:
    """id(item) -> the `project.items` dict key, computed once per payload.
    Rows must carry the handle the item view is addressed by, and scanning
    the dict per row is quadratic on a real project."""
    return {id(item): key for key, item in project.items.items()}


def items_payload(project: Project, filters: Filters, limit: int) -> dict:
    counts, totals = facet_counts(project, filters)
    matched = apply_filters(project, filters)
    handles = handle_map(project)
    return {
        "filters": filters.as_query(),
        "total": len(matched),
        "limit": limit,
        "items": [row(project, item, handles) for item in matched[:limit]],
        "facets": counts,
        "facet_totals": totals,
    }


def row(project: Project, item: Item, handles: dict[int, str]) -> dict:
    """One line of the item list: everything the list pane renders, and
    nothing it would have to fetch per row to get."""
    return {
        "key": item.key,
        "handle": handles.get(id(item), item.key or item.id),
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "board": item.board,
        "workspace": item.workspace,
        "tags": item_tags(item),
        "source_file": _norm_file(item.source_file),
        "source_line": item.source_line,
        "stage": project.coverage[item.id].stage if item.id in project.coverage else None,
        "check": check_state(item),
        "blocked": (item.id or item.key) in {c.item_id for c in project.blocked_chains},
        "external": item.external,
    }


def parse_limit(query: dict[str, list[str]]) -> int:
    raw = _first(query, "limit")
    if raw is None:
        return DEFAULT_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        raise FilterError("limit must be an integer") from None
    if limit < 1 or limit > MAX_LIMIT:
        raise FilterError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit
