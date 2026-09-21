"""JSON API handlers for `refdes serve`, kept free of HTTP details.

`handle()` is given an already-authenticated request (see `server`) and
returns `(status, payload)`. Reads answer from the *built* project snapshot,
never from a file scan.
"""

from __future__ import annotations

from ..model import Project


def item_pages(project: Project) -> dict[str, str]:
    """`project.items` dict key (surrogate key or provisional handle) ->
    the rendered page filename `render_site` writes for that item."""
    return {key: f"{item.slug}.html" for key, item in project.items.items()}


def handle(app, method: str, path: str, query: dict[str, list[str]], body) -> tuple[int, dict]:
    if path == "/api/revision" and method in ("GET", "HEAD"):
        return 200, app.state.revision_info()
    return 404, {"error": "not found"}
