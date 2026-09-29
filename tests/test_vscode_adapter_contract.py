"""The server-side guarantees the VS Code adapter is built on.

docs/design/editor-vscode-adapter.md §7.1 names these ten by name. They are not
extension tests: they pin the *server* facts the extension depends on, so a
change that breaks the adapter fails in CI rather than in a window nobody is
watching. The split with §7.2 is deliberate -- the facts the extension reads off
the wire are pinned here, in Python, where CI runs them; the extension's own
wiring is pinned textually in `tests/test_vscode_extension.py`.

The posture is the project's: verify against the real thing. Two of the ten
spawn the real `refdes serve` CLI as a subprocess and read its stdout; the rest
drive a live `EditorApp` over real sockets, in the `serve_support.Client`
posture `test_serve_security.py` and `test_serve_editor_e2e.py` already use.
Nothing here writes to `editors/vscode/`, and nothing here tests the extension
itself.

Read-only by construction as far as this repo goes: the fixture is a temp
project, and nothing here touches this repo's own `items/`.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import threading
from urllib.parse import quote, urlsplit

import pytest
from conftest import write_project_config
from helpers import _build_at
from serve_support import (
    DEC_FILE,
    LOG_FILE,
    REQ_FILE,
    SERVE_SCHEMA,
    TST_FILE,
    Client,
    snapshot_tree,
)

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes.serve import security
from refdes.serve.server import EditorApp

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
SERVE_CLIENT_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "editors",
    "vscode",
    "serveClient.js",
)

# serve_support's own fixture project, plus the one thing it does not have: an
# *imported* item. §7.1's item-view test needs both read-only shapes the server
# can hand back -- a sealed append-only entry and an external item -- and they
# are different gates in `api.edit_state`, so the fixture carries both.
SCHEMA = SERVE_SCHEMA + """
imports:
  - name: upstream
    items: upstream/items.json
    version: "2026.3"
"""

UPSTREAM = {
    "title": "Upstream platform",
    "version": "2026.3",
    "items": [
        {
            "id": "REQ-900",
            "type": "requirement",
            "title": "The rail shall be 3.3 V nominal.",
            # A scalar, a collection and an enum, so "every field of this item
            # reports the same read-only reason" covers all three field shapes
            # and not just the easy one.
            "fields": {
                "text": "The rail shall be 3.3 V nominal.",
                "tags": ["power", "rail"],
                "status": "approved",
            },
            "links": {},
            "content_hash": "upstreamhash01",
        }
    ],
}

LOCAL_REFS = ("REQ-001", "REQ-002", "REQ-003", "DEC-001", "DEC-002", "TST-001", "LOG-001")
SEALED_REF = "LOG-001"
IMPORTED_REF = "REQ-900"


def make_root(tmp_path):
    """The fixture project in the state a real one is in: keys minted and bare
    links expanded by an ordinary writable run, and the clean log entry sealed
    -- the same two steps `test_serve_editor_e2e.make_root` performs."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in {
        "reqs.yaml": REQ_FILE,
        "decs.yaml": DEC_FILE,
        "tests.yaml": TST_FILE,
        "log.yaml": LOG_FILE,
    }.items():
        (items / name).write_text(text, encoding="utf-8", newline="\n")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "items.json").write_text(json.dumps(UPSTREAM), encoding="utf-8")

    # A writable check mints every key and expands the bare link, so the fixture
    # has the durable identities the deep link is built from.
    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0

    project = _build_at(tmp_path)
    assert not project.errors, [d.message for d in project.diagnostics if d.level == "error"]
    build_mod.build(project, seal_write=True)
    assert list((tmp_path / ".refdes").glob("log-seal*.yaml")), "the fixture did not seal"
    return tmp_path


def start(root, **kw):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture
def served(tmp_path):
    root = make_root(tmp_path)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


# ------------------------------------------------------------------- helpers


def _file_revision(client, ref) -> str:
    """The `file_revision` an edit against this item has to send back."""
    status, view = client.api_get(f"/api/item/{ref}")
    assert status == 200, view
    return view["edit"]["file_revision"]


def _api_get(port: int, token: str, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(
            "GET", path, headers={"Host": f"127.0.0.1:{port}", security.TOKEN_HEADER: token}
        )
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


# ---------------------------------------------- 1. the launch line, verbatim
#
# §3.2 option 1 is the whole reason the extension can parse stdout at all, and
# `tests/test_vscode_extension.py` pins the two *sides* of the literal as source
# text. This is the runtime half: the real CLI, the real first line, the real
# token, used against the real server.

LAUNCH_LINE = re.compile(
    r"\Arefdes serve: http://127\.0\.0\.1:(\d+)/\?token=([A-Za-z0-9_-]+)\n?\Z"
)


@contextlib.contextmanager
def _serve_process(config, tmpdir):
    """`python -m refdes.cli -c <cfg> serve --no-open`, exactly the argv
    `ServeClient.start` builds (`serveClient.js`), with PYTHONPATH pointed at
    this checkout's `src/` so the child is the code under test and not whatever
    happens to be installed, and its preview temp dir isolated from a concurrent
    run."""
    env = dict(os.environ, PYTHONPATH=os.path.abspath(SRC), PYTHONIOENCODING="utf-8")
    env.update(TMP=str(tmpdir), TEMP=str(tmpdir), TMPDIR=str(tmpdir))
    proc = subprocess.Popen(
        [sys.executable, "-m", "refdes.cli", "-c", config, "serve", "--no-open"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
        proc.stdout.close()
        proc.stderr.close()


def _first_stdout_line(proc, timeout: int = 60) -> str:
    """The child's first stdout line, and nothing else.

    Read on a thread so a child that never prints fails the test on the timeout
    rather than hanging the suite -- a server that boots and stays silent is
    exactly the regression this test exists to catch.
    """
    got: dict[str, str] = {}

    def read() -> None:
        got["line"] = proc.stdout.readline()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    # stderr is deliberately not read here: the child is still serving, so a
    # read on it would block until the context manager kills the process, and
    # this assertion would hang the suite instead of failing it.
    assert not reader.is_alive(), (
        f"`refdes serve` printed no line to stdout within {timeout}s (exit code "
        f"so far: {proc.poll()})"
    )
    return got.get("line", "")


def _run_cli(config, *args, timeout: int = 60):
    env = dict(os.environ, PYTHONPATH=os.path.abspath(SRC), PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "refdes.cli", "-c", config, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def test_serve_prints_launch_url_as_first_stdout_line(tmp_path):
    """The one line the extension parses, off the real CLI, then used."""
    root = make_root(tmp_path)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    config = str(root / "refdes-project.yaml")

    with _serve_process(config, tmpdir) as proc:
        line = _first_stdout_line(proc)
        match = LAUNCH_LINE.match(line)
        assert match, (
            "the first line `refdes serve` prints is not the launch line the "
            f"extension parses: {line!r}. It must be exactly "
            "'refdes serve: http://127.0.0.1:<port>/?token=<token>' and nothing "
            "else -- §3.2 option 1, and the first thing ServeClient.start reads"
        )
        port, token = int(match.group(1)), match.group(2)

        # the parsed token is a working credential, not just a string
        status, body = _api_get(port, token, "/api/revision")
        assert status == 200, (status, body)
        assert json.loads(body)["revision"], body


# ------------------------------------------------------ 2. the token in argv
#
# §3.2's row 4: argv is readable by any local process, so the token may not be
# there. `tests/test_vscode_extension.py` checks the client never passes a
# `--token`; this checks the *server* end of the same promise -- the running
# child's own command line, read back from the OS.


def _process_command_line(pid: int) -> str:
    """The live process's own argv, however this platform exposes it.

    Linux has `/proc/<pid>/cmdline`; elsewhere `ps`; on Windows the CIM query
    `Get-Process` cannot answer. If none of them work the check skips *loudly*
    (§7.2's own rule for a check that could not run: report "not verified", not
    "verified").
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError:
        raw = b""
    if raw:
        return " ".join(p.decode("utf-8", "replace") for p in raw.split(b"\0") if p)

    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
        ]
    else:
        command = ["ps", "-ww", "-o", "args=", "-p", str(pid)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
        out = done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    if not out:
        pytest.skip(
            "could not read this platform's command line for a live process, so "
            "the argv half of test_launch_url_token_never_appears_in_argv did not "
            "run; the flag half below still did"
        )
    return out


def test_launch_url_token_never_appears_in_argv(tmp_path):
    """The child's command line carries no token, and there is no flag to put
    one there."""
    root = make_root(tmp_path)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    config = str(root / "refdes-project.yaml")

    with _serve_process(config, tmpdir) as proc:
        line = _first_stdout_line(proc)
        match = LAUNCH_LINE.match(line)
        assert match, f"no launch line to take a token from: {line!r}"
        token = match.group(2)

        argv = _process_command_line(proc.pid)
        assert token not in argv, (
            f"the launch token is in the child's command line, which any local "
            f"process can read: {argv!r}"
        )
        assert "token=" not in argv, (
            f"the child's command line carries a token-shaped argument: {argv!r}"
        )
        # ...and the argv the extension builds is there and nothing else.
        assert "serve" in argv and "--no-open" in argv, argv

    # The reason the check above can pass at all: `refdes serve` has no option
    # that takes a token, so no command line can carry one. Asserted against the
    # real parser, which rejects it.
    refused = _run_cli(config, "serve", "--no-open", f"--token={token}")
    assert refused.returncode != 0, (
        "`refdes serve --token=...` was accepted, so a command line could carry "
        "the launch token and §3.2 row 4 is no longer true"
    )
    assert "unrecognized arguments" in refused.stderr, refused.stderr


# --------------------------------------------------------- 3. reads are gated


def test_token_gates_reads_as_well_as_writes(served):
    """`X-Refdes-Token` on a read is not optional (docs/design/browser-editor.md,
    Security): no header is 403 and leaks nothing; with it, 200."""
    _app, client, _root = served
    status, _headers, data = client.request("GET", "/api/items")
    assert status == 403, (status, data)
    assert b"REQ-001" not in data, "a tokenless read returned item data"
    # the cookie alone is not the API's credential either: /api/ takes the
    # header, because a cross-site page cannot set a header
    assert client.request("GET", "/api/items", cookie=True)[0] == 403
    # a wrong token is refused the same way, not merely absent
    assert client.request("GET", "/api/items", headers={security.TOKEN_HEADER: "nope"})[0] == 403

    status, payload = client.api_get("/api/items")
    assert status == 200, payload
    # the whole project, local and imported alike, every row carrying the key
    # the deep link is built from
    assert sorted(row["id"] for row in payload["items"]) == sorted(
        LOCAL_REFS + (IMPORTED_REF,)
    ), payload
    local_rows = [row for row in payload["items"] if row["id"] != IMPORTED_REF]
    assert all(row["key"] and row["handle"] == row["key"] for row in local_rows), payload


# ------------------------------------------------- 4/5. the Origin on mutations
#
# The header a future refactor is most likely to drop, and the reason the client
# sets Origin explicitly (§3.2). Both tests POST a payload that *does* apply, so
# a 403 can only be the gate and not a body the service would have refused.


def test_mutation_without_origin_is_refused(served):
    _app, client, root = served
    decs = root / "items" / "decs.yaml"
    payload = {
        "op": "set_field",
        "field": "title",
        "value": "Use a synchronous buck.",
        "expected_revision": _file_revision(client, "DEC-001"),
    }

    status, body = client.api_post("/api/item/DEC-001/edit", payload, origin=None)
    assert status == 403, (status, body)
    assert "Use a synchronous buck." not in decs.read_text(encoding="utf-8")

    # the same payload, with the Origin the client sends, is accepted -- so the
    # 403 above was the missing header and nothing else
    status, applied = client.api_post("/api/item/DEC-001/edit", payload)
    assert status == 200, applied
    assert applied["kind"] == "applied"
    assert "Use a synchronous buck." in decs.read_text(encoding="utf-8")


def test_mutation_origin_must_match_host(served):
    """`Origin: http://localhost:<port>` on a `Host: 127.0.0.1:<port>` request is
    a mismatched pair, and `security.origin_ok` refuses it -- even though both
    spellings are individually accepted."""
    app, client, _root = served
    payload = {
        "op": "set_field",
        "field": "title",
        "value": "Use a multiphase buck.",
        "expected_revision": _file_revision(client, "DEC-001"),
    }
    localhost = f"http://localhost:{app.port}"

    status, body = client.api_post(
        "/api/item/DEC-001/edit", payload, origin=localhost, host=f"127.0.0.1:{app.port}"
    )
    assert status == 403, (status, body)

    # ...and the same Origin against the Host it belongs to is accepted, so the
    # refusal above was the mismatch rather than `localhost` being unwelcome
    status, applied = client.api_post(
        "/api/item/DEC-001/edit", payload, origin=localhost, host=f"localhost:{app.port}"
    )
    assert status == 200, applied
    assert applied["kind"] == "applied"


# ------------------------------------------- 6. editability is the server's call


def test_item_view_reports_edit_state_for_every_field(served):
    """§4: the extension renders `edit` verbatim and decides nothing itself, so
    every field must arrive with an `editable`, and a reason whenever it is
    false."""
    _app, client, _root = served

    for ref in LOCAL_REFS + (IMPORTED_REF,):
        status, view = client.api_get(f"/api/item/{ref}")
        assert status == 200, (ref, view)
        assert view["edit"]["fields"], ref
        for name, state in view["edit"]["fields"].items():
            assert "editable" in state, f"{ref}.{name} has no editable: {state}"
            if not state["editable"]:
                assert state.get("reason"), f"{ref}.{name} is read-only with no reason: {state}"

    # An ordinary editable item, spelled out: the enum is a select, and the
    # collection field is refused as a collection rather than silently editable.
    _status, req = client.api_get("/api/item/REQ-001")
    assert req["edit"]["editable"] is True and req["edit"]["reason"] is None
    assert req["edit"]["fields"]["text"]["editable"] is True
    assert req["edit"]["fields"]["status"]["control"] == "select"
    assert req["edit"]["fields"]["status"]["choices"] == ["draft", "approved"]
    assert req["edit"]["fields"]["tags"]["editable"] is False
    assert "scalar" in req["edit"]["fields"]["tags"]["reason"]
    assert req["edit"]["body"]["editable"] is True

    # The sealed append-only entry: every field of the item is false, with the
    # one sealed reason, and the item says so up front.
    _status, sealed = client.api_get(f"/api/item/{SEALED_REF}")
    assert sealed["append_only"] is True and sealed["sealed"] is True
    reason = sealed["edit"]["reason"]
    assert "sealed" in reason, reason
    assert sealed["edit"]["editable"] is False
    for name in sealed["fields"]:
        state = sealed["edit"]["fields"][name]
        assert state["editable"] is False, (name, state)
        assert state["reason"] == reason, (name, state)
    assert sealed["edit"]["body"] == {"editable": False, "reason": reason}

    # The imported item: the other gate, and the same shape. `id`/`key`/`type`
    # are identity pseudo-fields the server never offers to edit and carries its
    # own reason for; they are checked for the same promise (false, and
    # explained), not for the blocked reason, which is about the item.
    _status, imported = client.api_get(f"/api/item/{IMPORTED_REF}")
    assert imported["external"] is True and imported["origin"] == "upstream"
    reason = imported["edit"]["reason"]
    assert "imported" in reason, reason
    assert imported["edit"]["editable"] is False
    for name, value in imported["fields"].items():
        state = imported["edit"]["fields"][name]
        assert state["editable"] is False, (name, value, state)
        assert state["reason"] == reason, (name, state)
    for name in ("id", "key", "type"):
        state = imported["edit"]["fields"][name]
        assert state["editable"] is False and state["reason"], (name, state)


# ------------------------------------------------------ 7. what a conflict carries


def test_conflict_payload_carries_current_text_and_diff(served):
    """A stale `file_revision` is a 409 the client's conflict screen can render:
    it must arrive with the current text and the diff, and the losing edit must
    have changed nothing on disk."""
    _app, client, root = served
    decs = root / "items" / "decs.yaml"
    stale = _file_revision(client, "DEC-001")

    # Somebody edits the same file outside the editor, behind the held revision.
    outside = decs.read_text(encoding="utf-8").replace(
        "title: Use the buck regulator.", "title: Use the buck regulator (edited elsewhere)."
    )
    decs.write_text(outside, encoding="utf-8", newline="")
    after_edit = hashlib.sha256(decs.read_bytes()).hexdigest()

    status, body = client.api_post(
        "/api/item/DEC-001/edit",
        {
            "op": "set_field",
            "field": "title",
            "value": "Use a synchronous buck.",
            "expected_revision": stale,
        },
    )
    assert status == 409, body
    assert body["kind"] == "conflict" and body["ok"] is False
    assert body["expected_revision"] == stale
    assert body["current_revision"] == after_edit
    assert body["current_text"], "a 409 with no current_text cannot render a conflict"
    assert isinstance(body["current_text"], str) and "buck regulator" in body["current_text"]
    assert body["diff"], "a 409 with no diff cannot show what changed"
    assert "edited elsewhere" in body["diff"], body["diff"]
    assert "-" in body["diff"] and "+" in body["diff"], body["diff"]

    # The losing edit wrote nothing: the file is the outside edit's bytes.
    assert decs.read_text(encoding="utf-8") == outside
    assert "Use a synchronous buck." not in outside


# ------------------------------------------------- 8. `--no-write` refuses it all


def test_no_write_server_refuses_every_mutation_route(tmp_path):
    """Every route that writes, not just the one the e2e scenario happened to
    use: the edit route, the create route and the asset upload, each a 403 that
    says why, and the tree byte-identical at the end."""
    root = make_root(tmp_path)
    before = snapshot_tree(root)
    app = start(root, read_only=True)
    try:
        client = Client(app)
        origin = f"http://127.0.0.1:{app.port}"

        status, body = client.api_post(
            "/api/item/DEC-001/edit",
            {"op": "set_field", "field": "title", "value": "nope", "expected_revision": "0" * 64},
        )
        assert status == 403 and "--no-write" in body["error"], body

        status, body = client.api_post(
            "/api/items/create",
            {"type": "decision", "fields": {"title": "Use a synchronous buck."}},
        )
        assert status == 403 and "--no-write" in body["error"], body

        status, _headers, data = client.request(
            "POST",
            "/api/assets?dest=items&name=shot.png",
            token=True,
            body=b"\x89PNG\r\n\x1a\n",
            headers={"Origin": origin, "Content-Type": "application/octet-stream"},
        )
        assert status == 403, (status, data)
        assert "--no-write" in json.loads(data)["error"], data

        # ...and the reads still work, so this is a write gate and not a dead server
        assert client.api_get("/api/revision")[0] == 200
    finally:
        app.stop()

    assert snapshot_tree(root) == before
    assert not (root / "items" / "shot.png").exists()
    # the create really would have appended: the title is nowhere in the file
    assert "Use a synchronous buck." not in (root / "items" / "decs.yaml").read_text(
        encoding="utf-8"
    )


# --------------------------------------------------------- 9. the editor refuses framing


def test_editor_csp_refuses_framing(served):
    """§9.2's answer, in shipped behaviour: the editor is not frameable, so a
    webview could never frame it even if one shipped."""
    app, client, _root = served

    # through the cookie flow: the launch URL sets the session cookie, and the
    # cookie is what the navigable surfaces take
    status, headers, _body = client.request("GET", f"/?token={app.token}")
    assert status == 302
    cookie = headers["set-cookie"].split(";")[0]

    status, headers, _body = client.request("GET", "/edit/", headers={"Cookie": cookie})
    assert status == 200
    csp = headers["content-security-policy"]
    assert csp == security.EDITOR_CSP, csp
    assert "frame-ancestors 'none'" in security.EDITOR_CSP

    # The preview is the deliberate contrast: `frame-ancestors 'self'` on the
    # page plus `frame-src 'self'` on the editor is what lets the editor embed
    # *it*. Copying the preview's policy onto the editor would quietly allow the
    # framing this test exists to forbid, so both directions are pinned.
    _status, headers, _body = client.page("/preview/")
    assert "frame-ancestors 'self'" in headers["content-security-policy"]
    assert "frame-src 'self'" in security.EDITOR_CSP


# ------------------------------------------------- 10. one deep link, two spellers

DEEP_LINK_TEMPLATE = re.compile(r"deepLink\s*\(\s*key\s*\)\s*\{.*?return\s+`([^`]+)`", re.DOTALL)
INJECTED_LINK = re.compile(r'href="(/edit/#/items/[^"]+)"')


def test_deep_link_shape_matches_server_toolbar(served):
    """The preview toolbar's "Edit this item" and the extension's "Open in
    editor" must build the same URL, or the two affordances drift into opening
    different places for the same item."""
    app, client, _root = served
    project = app.state.snapshot.project
    item = project.item_by_id("DEC-001")

    # the server's own spelling, taken out of a real preview response
    status, _headers, data = client.page(f"/preview/{item.slug}.html")
    assert status == 200
    html = data.decode("utf-8")
    match = INJECTED_LINK.search(html)
    assert match, f"the preview toolbar injected no /edit/#/items/ link: {html!r}"
    injected = match.group(1)
    assert injected == "/edit/#/items/" + quote(item.key, safe=""), (injected, item.key)

    # the fragment names a handle the API answers for, so the link lands
    assert client.api_get(f"/api/item/{quote(item.key, safe='')}")[0] == 200

    # the extension's spelling, from the source of the module that builds it
    with open(SERVE_CLIENT_JS, encoding="utf-8") as fh:
        source = fh.read()
    template_match = DEEP_LINK_TEMPLATE.search(source)
    assert template_match, (
        "editors/vscode/serveClient.js no longer builds its deep link from a "
        "template literal in deepLink(key), so this can no longer be compared "
        "with what the server injects"
    )
    built = (
        f"http://127.0.0.1:{app.port}"
        + template_match.group(1)
        .replace("${this.base}", "")
        .replace("${TOKEN_QUERY(this.token)}", f"token={app.token}")
        .replace("${encodeURIComponent(key)}", quote(item.key, safe=""))
    )

    # The two are not the same URL on purpose: the toolbar's link is
    # same-origin (the browser already holds the session cookie) while the
    # extension's opens an external browser, which does not, so it carries the
    # token in the query for `_start_session` to consume and strip. What must
    # not differ is the path and the fragment -- where the item's form is.
    parts = urlsplit(built)
    assert parts.path + "#" + parts.fragment == injected, (
        f"the extension opens {parts.path}#{parts.fragment} where the server's "
        f"preview toolbar injects {injected!r}: the two 'open this item' "
        "affordances have drifted"
    )
    assert parts.query == f"token={app.token}", built
