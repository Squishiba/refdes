"""`refdes serve` security boundary (docs/design/browser-editor.md, Security):
loopback only, Host/Origin checks, launch token on reads and writes, CSP, and a
preview that lives in a temp dir and never in the project."""

from __future__ import annotations

import os
import re
import tempfile

import pytest
from serve_support import Client, make_project, path_of, snapshot_tree

from refdes.serve import security
from refdes.serve.preview import MARKER, ROOT_PREFIX, PreviewManager, prune_stale
from refdes.serve.server import EditorApp


@pytest.fixture
def served(tmp_path):
    config = make_project(tmp_path)
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


def test_binds_ipv4_loopback_on_an_ephemeral_port(served):
    app, _client, _root = served
    host, port = app.httpd.server_address
    assert host == "127.0.0.1"
    assert port > 0
    assert app.launch_url.startswith(f"http://127.0.0.1:{port}/?token=")


def test_token_has_at_least_256_bits(served):
    app, _c, _r = served
    assert len(security.new_token()) >= 43  # 32 bytes, urlsafe base64
    assert len(app.token) >= 43


def test_two_launches_get_different_tokens(tmp_path):
    config = make_project(tmp_path)
    one, two = EditorApp(config), EditorApp(config)
    try:
        assert one.token != two.token and one.port != two.port
    finally:
        one.stop()
        two.stop()


# ------------------------------------------------------------------- host


@pytest.mark.parametrize(
    "host", ["evil.example:{port}", "127.0.0.1:1", "localhost", "[::1]:{port}", "127.0.0.1"]
)
def test_wrong_host_is_rejected_before_routing(served, host):
    app, client, _r = served
    host = host.format(port=app.port)
    for kw in ({"cookie": True}, {"token": True}, {}):
        status, _h, body = client.request("GET", "/api/revision", host=host, **kw)
        assert status == 403
        assert b"revision" not in body
    status, _h, _b = client.request("GET", "/preview/", host=host, cookie=True)
    assert status == 403


def test_localhost_host_is_accepted(served):
    app, client, _r = served
    status, _h, _b = client.request(
        "GET", "/api/revision", token=True, host=f"localhost:{app.port}"
    )
    assert status == 200


# ------------------------------------------------------------------ token


def test_reads_need_the_token_header_on_the_api(served):
    _app, client, _r = served
    assert client.request("GET", "/api/revision")[0] == 403
    assert client.request("GET", "/api/revision", headers={"X-Refdes-Token": "nope"})[0] == 403
    # the cookie alone is not enough for the API: it is the *header* that a
    # cross-site page cannot set
    assert client.request("GET", "/api/revision", cookie=True)[0] == 403
    assert client.request("GET", "/api/revision", token=True)[0] == 200


def test_pages_need_the_session_cookie(served):
    _app, client, _r = served
    for path in ("/", "/preview/", "/edit/", "/edit/static/app.js"):
        status, _h, body = client.request("GET", path)
        assert status == 403, path
        assert b"Serve test" not in body
    assert client.request("GET", "/preview/", headers={"Cookie": "refdes_token_1=x"})[0] == 403


def test_launch_url_sets_a_strict_httponly_cookie_and_strips_the_token(served):
    app, client, _r = served
    status, headers, _b = client.request("GET", path_of(app.launch_url))
    assert status == 302
    cookie = headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert app.token in cookie  # the cookie *is* the session
    assert "token=" not in headers["location"]


def test_wrong_launch_token_sets_nothing(served):
    _app, client, _r = served
    status, headers, _b = client.request("GET", "/?token=wrong")
    assert status == 403 and "set-cookie" not in headers


# ---------------------------------------------------------- origin / posts


def test_post_needs_origin_content_type_and_bounded_body(served):
    app, client, _r = served
    good = f"http://127.0.0.1:{app.port}"
    assert client.api_post("/api/nothing", {}, origin=None)[0] == 403  # missing
    assert client.api_post("/api/nothing", {}, origin="null")[0] == 403
    assert client.api_post("/api/nothing", {}, origin="http://evil.example")[0] == 403
    assert client.api_post("/api/nothing", {}, origin=f"http://127.0.0.1:{app.port + 1}")[0] == 403
    # 127.0.0.1 origin arriving on a localhost Host is a mismatched pair
    assert client.api_post("/api/nothing", {}, origin=good, host=f"localhost:{app.port}")[0] == 403
    assert client.api_post("/api/nothing", {}, origin=good)[0] == 404  # cleared every gate
    localhost = f"localhost:{app.port}"
    assert client.api_post("/api/nothing", {}, origin=f"http://{localhost}", host=localhost)[0] == 404

    status, _h, _b = client.request(
        "POST", "/api/nothing", token=True, body=b"{}",
        headers={"Origin": good, "Content-Type": "text/plain"},
    )
    assert status == 415
    status, _h, _b = client.request(
        "POST", "/api/nothing", token=True, body=b"x" * (1024 * 1024 + 1),
        headers={"Origin": good, "Content-Type": "application/json"},
    )
    assert status == 413
    status, _h, _b = client.request(
        "POST", "/api/nothing", body=b"{}",
        headers={"Origin": good, "Content-Type": "application/json"},
    )
    assert status == 403  # no token


def test_a_cross_origin_get_is_rejected_too(served):
    _app, client, _r = served
    status, _h, _b = client.request(
        "GET", "/api/revision", token=True, headers={"Origin": "http://evil.example"}
    )
    assert status == 403


def test_other_methods_are_refused(served):
    _app, client, _r = served
    for method in ("PUT", "DELETE", "PATCH"):
        assert client.request(method, "/api/revision", token=True)[0] == 405


# -------------------------------------------------------- headers / CSP


def test_csp_and_no_cors_on_every_surface(served):
    _app, client, _r = served
    responses = [
        client.page("/edit/"),
        client.page("/edit/static/app.js"),
        client.page("/preview/"),
        client.request("GET", "/api/revision", token=True),
        client.request("GET", "/preview/"),  # a refusal carries them too
    ]
    for _status, headers, _body in responses:
        assert "content-security-policy" in headers
        assert headers["x-content-type-options"] == "nosniff"
        assert not any(name.startswith("access-control-") for name in headers)
    editor_csp = client.page("/edit/")[1]["content-security-policy"]
    assert "script-src 'self'" in editor_csp and "'unsafe-inline'" not in editor_csp
    assert "frame-ancestors 'none'" in editor_csp and "default-src 'none'" in editor_csp
    assert "connect-src 'self'" in editor_csp


def test_editor_shell_has_no_inline_script_and_carries_the_token(served):
    app, client, _r = served
    status, _h, body = client.page("/edit/")
    html = body.decode("utf-8")
    assert status == 200
    assert f'content="{app.token}"' in html
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag and "http" not in tag


# --------------------------------------------------------------- traversal


@pytest.mark.parametrize(
    "path",
    [
        "/preview/../refdes-project.yaml",
        "/preview/%2e%2e/refdes-project.yaml",
        "/preview/..%2frefdes-project.yaml",
        "/preview/..\\refdes-project.yaml",
        "/preview/%5c..%5crefdes-project.yaml",
        "/preview/C:/Windows/win.ini",
        "/preview/index.html::$DATA",
        "/preview/CON",
        "/preview/nul.html",
        "/edit/static/../index.html",
        "/edit/static/%2e%2e/server.py",
        "/edit/static/..%5cserver.py",
        "/edit/static/index.html",
        "/edit/static/sub/app.js",
    ],
)
def test_path_traversal_and_odd_names_reach_nothing(served, path):
    _app, client, _root = served
    status, _h, body = client.page(path)
    assert status in (403, 404)
    assert b"site:" not in body and b"defaults:" not in body and b"[fonts]" not in body


# ----------------------------------------------- preview lives in a temp dir


def test_preview_is_rendered_outside_the_project_and_never_into_site(served):
    app, client, root = served
    assert not (root / "_site").exists()
    tmp_root = os.path.realpath(tempfile.gettempdir())
    assert os.path.realpath(app.preview.root).startswith(tmp_root)
    assert not os.path.realpath(app.preview.root).startswith(os.path.realpath(str(root)))

    status, _h, body = client.page("/preview/")
    assert status == 200
    html = body.decode("utf-8")
    assert "Serve test" in html and "refdes-serve-bar" in html  # toolbar in the response...
    on_disk = ""
    for dirpath, _d, names in os.walk(app.preview.current):
        for n in names:
            if n.endswith(".html"):
                with open(os.path.join(dirpath, n), encoding="utf-8") as fh:
                    on_disk += fh.read()
    assert "refdes-serve-bar" not in on_disk  # ...never in the rendered files
    assert "/edit/" not in on_disk


def test_item_pages_link_to_their_editor_form_only_in_the_response(served):
    app, client, _r = served
    project = app.state.snapshot.project
    req = project.item_by_id("REQ-001")
    status, _h, body = client.page(f"/preview/{req.slug}.html")
    assert status == 200
    assert f"/edit/#/items/{req.key}" in body.decode("utf-8")
    other, _h, dashboard = client.page("/preview/summary.html")
    assert other == 200 and "Edit this item" not in dashboard.decode("utf-8")


def test_stop_removes_the_preview_root(tmp_path):
    app = EditorApp(make_project(tmp_path))
    root = app.preview.root
    assert os.path.isdir(root)
    app.stop()
    assert not os.path.exists(root)


def test_prune_removes_only_stale_marked_roots(tmp_path):
    stale = tmp_path / f"{ROOT_PREFIX}old"
    stale.mkdir()
    (stale / MARKER).write_text("1", encoding="utf-8")
    old = 1577836800
    os.utime(stale / MARKER, (old, old))
    fresh = tmp_path / f"{ROOT_PREFIX}live"
    fresh.mkdir()
    (fresh / MARKER).write_text("2", encoding="utf-8")
    unmarked = tmp_path / f"{ROOT_PREFIX}unmarked"
    unmarked.mkdir()
    (unmarked / "keep.txt").write_text("x", encoding="utf-8")
    unrelated = tmp_path / "somebody-elses"
    unrelated.mkdir()
    (unrelated / MARKER).write_text("3", encoding="utf-8")
    os.utime(unrelated / MARKER, (old, old))

    removed = prune_stale(str(tmp_path))
    assert removed == [str(stale)]
    assert not stale.exists()
    assert fresh.exists() and unmarked.exists() and unrelated.exists()

    PreviewManager(str(tmp_path)).close()  # a new launch prunes on start


def test_serving_the_whole_surface_leaves_the_project_byte_identical(served):
    app, client, root = served
    before = snapshot_tree(root)
    project = app.state.snapshot.project
    for path in ("/", "/preview/", "/preview/summary.html", "/edit/", "/edit/static/app.js"):
        client.page(path)
    client.api_get("/api/revision")
    client.request("GET", "/preview/../refdes-project.yaml", cookie=True)
    for key in list(project.items)[:3]:
        client.page(f"/preview/{project.items[key].slug}.html")
    assert snapshot_tree(root) == before
