"""The existing-image picker (docs/design/editor-image-upload.md §17, Phase 0).

`GET /api/images?item=<handle>` lists the images the project already has and
hands back, for each, the exact `![alt](src)` line to insert. The claims pinned
here are the ones the slice is scoped by:

* the list is the build's own walk -- every file under a declared `site.assets:`
  directory, the same set `state.project_inputs` watches and
  `build.collect_static_assets` publishes -- so it can never offer an image a
  build would not resolve;
* `src` is relative to *this item's* source file, the spelling that resolves
  first and always wins (docs/markdown.md);
* the text it hands over is text the build accepts: it goes through the ordinary
  `set_body` save, the delta gate, and a rendered page that shows the image;
* it is a read. Nothing in this file's requests moves a byte of the project, and
  a `--no-write` server answers it normally;
* nothing outside a declared asset directory is reachable, and the endpoint
  takes no path from the client at all -- the bytes come from the existing
  preview surface, under the session cookie.
"""

from __future__ import annotations

import os

import pytest
from serve_support import Client, make_filter_project, snapshot_tree

from refdes.serve import api as api_mod
from refdes.serve import security
from refdes.serve.server import EditorApp

PNG = b"\x89PNG\r\n\x1a\n"


def _serve(root, *, read_only: bool = False):
    config = str(root / "refdes-project.yaml")
    app = EditorApp(config, poll_interval=60, read_only=read_only)
    app.start()
    return app, Client(app)


def make_image_project(tmp_path, files: dict[str, bytes] | None = None, *, assets="figures"):
    """The shared filter fixture plus a `site.assets:` directory. `files` maps a
    path under that directory to its bytes; a path outside it is written where
    it is named."""
    root = tmp_path
    make_filter_project(root)
    config = root / "refdes-project.yaml"
    if assets:
        text = config.read_text(encoding="utf-8").replace(
            'site:\n  title: "Filter test"\n',
            f'site:\n  title: "Filter test"\n  assets: [{assets}]\n',
        )
        config.write_text(text, encoding="utf-8")
    for rel, data in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


@pytest.fixture
def served(tmp_path):
    root = make_image_project(tmp_path, {"figures/curve.png": PNG, "figures/scan.jpg": PNG})
    app, client = _serve(root)
    try:
        yield app, client, root
    finally:
        app.stop()


def _rows(payload):
    return {row["rel"]: row for row in payload["images"]}


# ------------------------------------------------------------------- the list


def test_an_existing_image_is_listed_with_everything_the_picker_needs(served):
    _app, client, _root = served
    status, payload = client.api_get("/api/images?item=REQ-001")
    assert status == 200
    assert payload["item"] == "REQ-001"
    assert payload["source_file"] == "items/reqs.yaml"
    assert payload["asset_dirs"] == ["figures"]
    assert payload["total"] == 2
    row = _rows(payload)["figures/curve.png"]
    assert row["name"] == "curve.png"
    assert row["alt"] == "curve"
    assert row["bytes"] == len(PNG)
    assert row["insertable"] is True
    # the src is relative to the item's own source file, not the project root
    assert row["src"] == "../figures/curve.png"
    assert row["markdown"] == "![curve](../figures/curve.png)"


def test_the_same_file_gets_a_different_src_for_a_different_item(tmp_path):
    """The src is a function of the item, not of the picker: two items in two
    directories spell the same file two ways, and both are the relative path
    their own source file resolves from (docs/markdown.md)."""
    root = make_image_project(tmp_path, {"figures/curve.png": PNG})
    (root / "items" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "items" / "decisions" / "decs.yaml").write_text(
        "defaults: { type: decision, board: board-a }\n"
        "items:\n"
        "  - id: DEC-901\n"
        "    title: Deeper down.\n",
        encoding="utf-8",
    )
    app, client = _serve(root)
    try:
        _status, shallow = client.api_get("/api/images?item=REQ-001")
        _status, deep = client.api_get("/api/images?item=DEC-901")
        assert deep["source_file"] == "items/decisions/decs.yaml"
        assert _rows(shallow)["figures/curve.png"]["src"] == "../figures/curve.png"
        assert _rows(deep)["figures/curve.png"]["src"] == "../../figures/curve.png"
    finally:
        app.stop()


def test_a_non_image_in_an_asset_directory_is_not_offered(served):
    _app, client, root = served
    (root / "figures" / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "figures" / "diagram.svg").write_text("<svg/>", encoding="utf-8")
    app = _app
    app.state.refresh()
    status, payload = client.api_get("/api/images?item=REQ-001")
    assert status == 200
    assert "figures/notes.csv" not in _rows(payload)
    # SVG is listed: refusing it is an upload-side policy about bytes arriving
    # from a browser, and this endpoint accepts none.
    assert "figures/diagram.svg" in _rows(payload)


def test_a_file_outside_every_asset_directory_is_not_listed_and_not_reachable(served):
    app, client, root = served
    (root / "items" / "beside.png").write_bytes(PNG)
    (root / "private.png").write_bytes(b"not an image anybody may fetch")
    app.state.refresh()
    _status, payload = client.api_get("/api/images?item=REQ-001")
    listed = {row["rel"] for row in payload["images"]}
    assert "items/beside.png" not in listed
    assert "private.png" not in listed
    # and neither is fetchable: the preview surface only ever holds what the
    # build published, and no route takes a path from the client.
    for url in ("/preview/assets/items/beside.png", "/preview/assets/private.png"):
        status, _headers, _body = client.page(url)
        assert status == 404, url
    status, _headers, _body = client.page("/preview/assets/../../private.png")
    assert status == 404


def test_a_project_with_no_images_returns_an_empty_list(tmp_path):
    root = make_image_project(tmp_path)
    app, client = _serve(root)
    try:
        status, payload = client.api_get("/api/images?item=REQ-001")
        assert status == 200
        assert payload["images"] == []
        assert payload["total"] == 0
        assert payload["asset_dirs"] == ["figures"]
    finally:
        app.stop()


def test_a_project_with_no_asset_directories_says_so(tmp_path):
    root = make_image_project(tmp_path, assets="")
    (root / "curve.png").write_bytes(PNG)
    app, client = _serve(root)
    try:
        status, payload = client.api_get("/api/images?item=REQ-001")
        assert status == 200
        assert payload["images"] == []
        assert payload["asset_dirs"] == []
    finally:
        app.stop()


def test_a_declared_asset_directory_that_does_not_exist_is_skipped(tmp_path):
    root = make_image_project(tmp_path, assets="figures, absent")
    app, client = _serve(root)
    try:
        status, payload = client.api_get("/api/images?item=REQ-001")
        assert status == 200
        assert payload["images"] == []
    finally:
        app.stop()


def test_a_nested_asset_directory_is_walked_too(tmp_path):
    root = make_image_project(tmp_path, {"figures/2026/curve.png": PNG})
    app, client = _serve(root)
    try:
        _status, payload = client.api_get("/api/images?item=REQ-001")
        row = _rows(payload)["figures/2026/curve.png"]
        assert row["src"] == "../figures/2026/curve.png"
    finally:
        app.stop()


# ------------------------------------------------------- the text it hands over


def test_the_reference_it_hands_over_saves_and_renders(served):
    """The whole point, end to end: the exact text the picker inserts passes the
    delta gate, reaches disk, and the rendered page shows that image."""
    _app, client, _root = served
    _status, payload = client.api_get("/api/images?item=REQ-001")
    row = _rows(payload)["figures/curve.png"]
    _status, item = client.api_get("/api/item/REQ-001")
    status, result = client.api_post(
        "/api/item/REQ-001/edit",
        {
            "op": "set_body",
            "text": row["markdown"],
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 200, result
    assert result["kind"] == "applied"
    _status, _headers, page = client.page("/preview/req-001.html")
    assert b'<img src="assets/figures/curve.png"' in page


def test_a_name_the_renderer_would_encode_is_reported_not_offered(tmp_path):
    """Markdown percent-encodes a space in a destination and the build resolves
    the *rendered* src, so `thermal curve.png` is not referenceable by any
    spelling. The picker says so instead of handing over text the save refuses."""
    root = make_image_project(tmp_path, {"figures/thermal curve.png": PNG})
    app, client = _serve(root)
    try:
        _status, payload = client.api_get("/api/images?item=REQ-001")
        row = _rows(payload)["figures/thermal curve.png"]
        assert row["insertable"] is False
        assert "markdown" not in row
        assert "renaming" in row["note"]
    finally:
        app.stop()


def test_alt_text_is_the_filename_stem_and_never_empty(served):
    _app, client, root = served
    (root / "figures" / "chart.2026-09.png").write_bytes(PNG)
    _app.state.refresh()
    _status, payload = client.api_get("/api/images?item=REQ-001")
    row = _rows(payload)["figures/chart.2026-09.png"]
    assert row["alt"] == "chart.2026-09"
    assert row["markdown"] == "![chart.2026-09](../figures/chart.2026-09.png)"
    assert all(row["alt"] for row in payload["images"])


@pytest.mark.parametrize(
    "name,alt,markdown",
    [
        ("curve.png", "curve", "![curve](../figures/curve.png)"),
        ("thermal curve.jpg", "thermal curve", "![thermal curve](<../figures/thermal curve.jpg>)"),
        # a bracket in the stem would otherwise close the image early
        ("odd[1].png", "odd\\[1\\]", "![odd\\[1\\]](../figures/odd[1].png)"),
        # no stem at all still gets alt text: an empty one is a silent
        # accessibility failure (design §7)
        (".png", ".png", "![.png](../figures/.png)"),
    ],
)
def test_the_inserted_text_is_composed_by_the_server(name, alt, markdown):
    assert api_mod.image_alt(name) == alt
    assert api_mod.image_markdown(f"../figures/{name}", alt) == markdown


# ------------------------------------------------------------- read-only-ness


def test_reading_the_picker_writes_nothing(served):
    _app, client, root = served
    before = snapshot_tree(root)
    for _ in range(3):
        status, _payload = client.api_get("/api/images?item=REQ-001")
        assert status == 200
    assert snapshot_tree(root) == before


def test_a_read_only_server_serves_the_picker(tmp_path):
    root = make_image_project(tmp_path, {"figures/curve.png": PNG})
    app, client = _serve(root, read_only=True)
    try:
        before = snapshot_tree(root)
        status, payload = client.api_get("/api/images?item=REQ-001")
        assert status == 200
        assert payload["total"] == 1
        assert snapshot_tree(root) == before
    finally:
        app.stop()


# ------------------------------------------------------------------- the gate


def test_the_picker_needs_the_launch_token(served):
    _app, client, _root = served
    status, _headers, _body = client.request("GET", "/api/images?item=REQ-001")
    assert status == 403
    status, _headers, _body = client.request(
        "GET", "/api/images?item=REQ-001", headers={"X-Refdes-Token": "wrong"}
    )
    assert status == 403


def test_a_foreign_host_is_refused_before_routing(served):
    _app, client, _root = served
    status, _headers, _body = client.request(
        "GET", "/api/images?item=REQ-001", token=True, host="evil.example"
    )
    assert status == 403


def test_the_picker_is_a_read_and_nothing_else(served):
    """No upload lives here, and saying so in a test is what stops one being
    added quietly: the route takes no body, answers only GET/HEAD, and the
    project is unchanged afterwards."""
    app, client, root = served
    before = snapshot_tree(root)
    status, _headers, _body = client.request(
        "POST",
        "/api/images?item=REQ-001",
        token=True,
        body=b"{}",
        headers={
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{app.port}",
        },
    )
    assert status == 405
    assert snapshot_tree(root) == before


def test_an_item_that_matches_nothing_is_a_404(served):
    _app, client, _root = served
    status, payload = client.api_get("/api/images?item=NOPE-999")
    assert status == 404
    assert "NOPE-999" in payload["error"]


def test_the_picker_never_returns_an_absolute_server_path(served):
    """The `shown()` posture of every other route (`api.py`): the browser has no
    use for a server filesystem root, and a path it cannot read is a path it
    cannot leak. What it does get is project-relative and a same-origin URL."""
    _app, client, root = served
    _status, payload = client.api_get("/api/images?item=REQ-001")
    assert str(root) not in repr(payload)
    for row in payload["images"]:
        assert not os.path.isabs(row["rel"])
        assert not os.path.isabs(row["src"])
        assert row["rel"].startswith("figures/"), "only a declared asset directory is listed"
        assert row["thumb"].startswith("/preview/assets/")


# ------------------------------------------------------------- the thumbnails


def test_the_thumbnail_is_the_preview_surface_not_a_new_read_endpoint(served):
    """The bytes come from the build's own published asset, gated by the
    session cookie -- which is what an `<img>` can carry. No token in a URL, and
    nothing reachable without the cookie."""
    _app, client, _root = served
    _status, payload = client.api_get("/api/images?item=REQ-001")
    row = _rows(payload)["figures/curve.png"]
    assert row["thumb"] == "/preview/assets/figures/curve.png"

    status, headers, body = client.page(row["thumb"])
    assert status == 200
    assert body == PNG
    assert headers["content-type"] == "image/png"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["content-security-policy"] == security.PREVIEW_CSP

    status, _headers, _body = client.request("GET", row["thumb"])
    assert status == 403, "the preview surface is cookie-gated, not token-gated"
