"""JSON API handlers for `refdes serve`, kept free of HTTP details.

`handle()` is given an already-authenticated request (see `server`) and
returns `(status, payload)`. Reads answer from the *built* project snapshot,
never from a file scan.
"""

from __future__ import annotations

import urllib.parse

from ..model import Item, Project
from ..seal import is_sealed
from . import filters as filters_mod
from .filters import FilterError, check_state, item_tags


def item_pages(project: Project) -> dict[str, str]:
    """`project.items` dict key (surrogate key or provisional handle) ->
    the rendered page filename `render_site` writes for that item."""
    return {key: f"{item.slug}.html" for key, item in project.items.items()}


def handle(app, method: str, path: str, query: dict[str, list[str]], body) -> tuple[int, dict]:
    if path == "/api/revision" and method in ("GET", "HEAD"):
        return 200, app.state.revision_info()
    if path == "/api/items" and method in ("GET", "HEAD"):
        return _items(app, query)
    if path.startswith("/api/item/") and method in ("GET", "HEAD"):
        ref = urllib.parse.unquote(path[len("/api/item/"):])
        return _item_view(app, ref)
    if path in ("/api/items", ) or path.startswith("/api/item/"):
        return 405, {"error": "method not allowed"}
    return 404, {"error": "not found"}


def _items(app, query: dict[str, list[str]]) -> tuple[int, dict]:
    project = app.state.snapshot.project
    try:
        filters = filters_mod.parse_filters(project, query)
        limit = filters_mod.parse_limit(query)
    except FilterError as exc:
        return exc.status, {"error": str(exc)}
    return 200, filters_mod.items_payload(project, filters, limit)


def _find_item(project: Project, ref: str) -> tuple[Item | None, str | None]:
    """Resolve an item-view reference. Accepted spellings, in order: the
    `project.items` dict key (surrogate key, or the provisional handle of a
    keyless item — what `/api/items` rows carry as `handle`), then display id,
    then surrogate key via `item_by_ref`. A provisional handle is never a
    linkable identity, so it is deliberately looked up only here, only by
    exact dict hit, and echoed back so the UI can address the item again."""
    if not ref:
        return None, None
    item = project.items.get(ref)
    if item is not None:
        return item, ref
    item = project.item_by_ref(ref)
    if item is not None:
        return item, item.key or ref
    return None, None


def _diagnostics_for(project: Project, item: Item, handle: str) -> list[dict]:
    refs = {r for r in (item.id, item.key, handle) if r}
    out = []
    for d in project.diagnostics:
        if d.item_id and d.item_id in refs:
            out.append(
                {
                    "level": d.level,
                    "message": d.message,
                    "file": d.file,
                    "line": d.line,
                    "code": d.code,
                }
            )
    return out


def _item_view(app, ref: str) -> tuple[int, dict]:
    project = app.state.snapshot.project
    item, handle = _find_item(project, ref)
    if item is None:
        return 404, {"error": f"no item matches {ref!r}"}
    cov = project.coverage.get(item.id) if item.id else None
    spec = project.types.get(item.type)
    return 200, {
        "revision": app.state.snapshot.revision,
        "handle": handle,
        "page": f"{item.slug}.html",
        "key": item.key,
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "board": item.board,
        "workspace": item.workspace,
        "tags": item_tags(item),
        "source_file": item.source_file.replace("\\", "/"),
        "source_line": item.source_line,
        "body": item.body,
        "fields": item.fields,
        "inherited_fields": sorted(item.inherited_fields),
        "external": item.external,
        "origin": item.origin,
        "append_only": bool(spec.append_only) if spec else False,
        "sealed": is_sealed(project, item),
        "links": {
            "outgoing": {v: list(t) for v, t in sorted(item.resolved_links.items())},
            "incoming": {v: list(t) for v, t in sorted(item.backlinks.items())},
        },
        "coverage": (
            None
            if cov is None
            else {
                "stage": cov.stage,
                "addressed_by": list(cov.addressed_by),
                "claimed_by": list(cov.claimed_by),
                "satisfied_by": list(cov.satisfied_by),
                "verified_by": list(cov.verified_by),
            }
        ),
        "check": check_state(item),
        "checks": [
            {
                "value_name": c.value_name,
                "against": c.against,
                "ok": c.ok,
                "detail": c.detail,
                "actual": c.actual,
            }
            for c in item.checks
        ],
        "diagnostics": _diagnostics_for(project, item, handle),
    }
