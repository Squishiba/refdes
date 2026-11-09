"""Thread workbench W5b.4c-2b contract: the SAVE half of the pane's DOM glue.

docs/design/thread-workbench-w5b-plan.md §4 W5b.4 + §6 Q2/Q3/Q5/Q6/Q8 (all
RATIFIED 2026-11-06). The pure save model (``tick-save.js``, #468) and the
pure pane/store pair (``tick-pane.js``, ``tick-drafts.js``) exist; this slice
is the network seam: a new module ``taskpane-save.js`` that owns ALL of the
fetch/token code, and ``taskpane-ticks.js`` gains ONLY the relative import of
it and ONE ``initSave({drafts, panels, refreshPanel})`` call -- so every old
W5b.3/4c-1b pin on the glue (no fetch, no XMLHttpRequest, no X-Refdes-Token,
no /api/) stays true, unedited, and is re-asserted here.

The ratified contract this file pins (Q3 RATIFIED (a): a save that finds the
tip moved is REFUSED, and the pane shows the current tip's list against the
pending ticks with exactly three outcomes -- keep mine / keep theirs / copy
it out -- and NOTHING that merges):

  * the Save button: ``button type="button"`` class ``refdes-taskpane-save``,
    label via ``textContent``, visible only while the panel has >=1 pending
    tick and no save is in flight (``disabled`` during flight);
  * the POST: ``buildSaveRequest({ref, revision, pendingTicks})`` ->
    ``fetch(path, {method: 'POST', credentials: 'same-origin', headers:
    {'Content-Type': 'application/json', 'X-Refdes-Token': <meta content>}})``
    -- the token read from ``meta[name="refdes-token"]`` at save time, never
    in a URL, storage, the DOM, or a log;
  * ``saved`` -> ``drafts.discard(tipKey)`` then ``location.reload()`` once
    (the new entry becomes the tip; the preview re-renders);
  * ``refused`` / ``invalid`` / ``forbidden`` / ``error`` -> the message in a
    ``role="alert"`` element via ``textContent``, the draft KEPT, Save
    re-enabled;
  * ``conflict`` -> the 409 carries ``current_revision``/``current_text``/
    ``diff`` and NO task rows (pinned live below), so the glue re-fetches
    ``location.href``, parses it with DOMParser, reads the CURRENT tip's rows
    (``panelFromRows``), and shows ``class refdes-taskpane-conflict`` with the
    ``describeConflict`` rows and the three ``conflictChoices`` buttons. Keep
    mine re-stamps MY ticks on the CURRENT tip key/revision (``setTick``/
    ``setRevision``) and reloads; keep theirs discards and reloads; copy it
    out shows ``copyOut.text`` in a read-only textarea and tries the
    clipboard inside try/catch. A page with no panel for the thread says so
    and offers only Copy it out + Keep theirs. Nothing merges, ever.

The `ref` form the real route resolves (run against the live server,
test_the_continue_route_resolves_the_key_and_the_display_id): BOTH the tip's
surrogate key and its display id resolve (serve/resolution.py steps 1 and 2),
and the panels carry ``data-refdes-tip-key``, so the glue names the key --
the identity that survives a rename.

What a headless suite can pin, this file pins: (a) the real server (tags,
served bytes, the built site's silence, the preview CSS block, the live route
and 409 shape); (b) source pins over the comment-stripped modules (import
graph, one POST + one GET, the token seam, inert markup, clipboard guarded,
no second beforeunload, the glue's unchanged purity); (c) a NODE run of
``taskpane-save.js`` over an honest fake: a DOM of plain nodes built by
``document.createElement`` (the repo's posture, test_editor_draft_mirror.py),
a ``fetch`` that records every (url, init) and answers scripted
``{status, json, text}``, a ``location`` that counts ``reload()`` calls, a
``navigator.clipboard`` that records text, and a DOMParser stub that reads
``data-refdes-*`` attributes out of the page text it was given -- NO layout,
NO CSS, NO real event dispatch, NO cookie/credentials handling.

Browser-only (Chromium/Firefox, NOT pinnable here, listed for the verifier):
button visibility/enablement rendered; the CSS rules' visual effect; a real
``location.reload()`` landing on the re-rendered page with the continuation
as tip; the real same-origin cookie + token round trip (CSP connect-src
'self' permitting the same-origin fetch); a real DOMParser over a real
preview page; the clipboard's real permission prompt; the beforeunload prompt
firing when a draft is open at navigation.

Red today, green after the slice (the marked green guards pass today and
must keep passing):

  test_the_preview_page_carries_exactly_one_module_tag            green guard
  test_the_save_glue_is_served_as_javascript                          RED (404)
  test_the_built_site_ships_none_of_the_save_glue                   green guard
  test_the_preview_css_block_grows_the_save_and_conflict_rules          RED
  test_the_built_stylesheet_stays_byte_identical                    green guard
  test_the_continue_route_resolves_the_key_and_the_display_id       green guard
  test_the_conflict_answer_carries_no_task_rows                     green guard
  test_the_save_module_imports_the_pure_modules_never_the_glue          RED
  test_the_save_module_makes_exactly_two_fetches                        RED
  test_the_save_module_reads_the_token_from_the_meta_only               RED
  test_the_save_module_is_inert_markup                                  RED
  test_the_save_module_wraps_the_clipboard_and_ships_no_unload          RED
  test_the_glue_gains_the_save_hook_and_no_network                      RED
  test_the_save_module_names_the_dom_contract                           RED
  the nine node scenarios (fixture exits red: no module to import)      RED
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.parse

import pytest
from conftest import write_project_config
from serve_support import Client
from test_serve_static import (  # the js rules, imported, not re-typed
    DYNAMIC_CODE,
    INLINE_HANDLER,
    JS_IMPORT,
    strip_js_comments,
)

from refdes import cli as cli_mod
from refdes.serve import edit as edit_mod
from refdes.serve.server import _TICKS_TAG, EditorApp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_REFDES = os.path.join(REPO_ROOT, "src", "refdes")
STATIC_DIR = os.path.join(SRC_REFDES, "serve", "static")
TASKPANE_CSS = os.path.join(SRC_REFDES, "templates", "taskpane", "taskpane.css")

GLUE = "taskpane-ticks.js"
SAVE = "taskpane-save.js"
MODEL = "tick-save.js"
STORE = "tick-drafts.js"
PANE = "tick-pane.js"

PREVIEW_CSS_START = "/* refdes:preview-css-start */"
PREVIEW_CSS_END = "/* refdes:preview-css-end */"
PREVIEW_CSS_BYTES_RE = re.compile(
    re.escape(PREVIEW_CSS_START.encode("utf-8"))
    + b".*?"
    + re.escape(PREVIEW_CSS_END.encode("utf-8")),
    re.DOTALL,
)

# The names of the save UI (the same list is spelled in the node harness):
# what the browser harness queries, pinned as source strings so the JS, the
# CSS, and a verifier's script cannot drift.
DOM_CONTRACT = (
    "refdes-taskpane-save",
    "refdes-taskpane-conflict",
    "Save",
    "Keep mine",
    "Keep theirs",
    "Copy it out",
    "role",
    "alert",
    "textarea",
    "readOnly",
    "data-refdes-tip-key",
    "data-refdes-revision",
    "data-refdes-task",
    'meta[name="refdes-token"]',
)

# The save seam's own rules: the token comes from the meta and goes ONLY in
# the request header; the pane renders authored text through textContent;
# taskpane-ticks.js owns the page's ONE beforeunload listener.
FORBIDDEN = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "javascript:",
    "?token=",
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "beforeunload",
)

# The old W5b.3/4c-1b pin, re-asserted here (the task: it STAYS true): the
# glue gains the save hook and NOTHING network-shaped.
GLUE_FORBIDDEN = (
    "fetch(",
    "XMLHttpRequest",
    "X-Refdes-Token",
    "refdes-token",
    "?token=",
    "/api/",
    "/continue",
    "location.reload",
    "navigator.clipboard",
)

IMPORT_OF = {
    MODEL: re.compile(r"""from\s+['"]\./""" + re.escape(MODEL) + r"""['"]"""),
    PANE: re.compile(r"""from\s+['"]\./""" + re.escape(PANE) + r"""['"]"""),
}
GLUE_IMPORT_OF_SAVE = re.compile(r"""from\s+['"]\./""" + re.escape(SAVE) + r"""['"]""")
FETCH_CALL = re.compile(r"\bfetch\(")

# A one-tip thread, warmed by a writable load (keys minted): the state a real
# project is in when anyone serves it, and the shape whose panel carries both
# halves of the save identity (data-refdes-tip-key / data-refdes-revision,
# pinned by test_task_pane_tick_context.py).
ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model the copper temperature., state: open}\n"
    "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"
)


def _warm(root) -> str:
    write_project_config(
        root,
        "site: { title: Tick Save UI, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = root / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_bytes(ONE_TIP.encode("utf-8"))
    config = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0  # the writable load mints the keys
    return config


@pytest.fixture
def served(tmp_path):
    app = EditorApp(_warm(tmp_path), poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


def _preview_page(client, app) -> str:
    page = app.state.snapshot.project.item_by_id("LOG-002").slug + ".html"
    status, _headers, body = client.page(f"/preview/{page}")
    assert status == 200
    return body.decode("utf-8")


def _sha(root, rel) -> str:
    with open(os.path.join(str(root), "items", rel), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _save_code() -> str:
    with open(os.path.join(STATIC_DIR, SAVE), encoding="utf-8") as fh:
        return strip_js_comments(fh.read())


def _glue_code() -> str:
    with open(os.path.join(STATIC_DIR, GLUE), encoding="utf-8") as fh:
        return strip_js_comments(fh.read())


def _walk_text(root: str):
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                yield os.path.relpath(path, root).replace("\\", "/"), fh.read().decode(
                    "utf-8", errors="replace"
                )


def _preview_block(css: str) -> str:
    start = css.index(PREVIEW_CSS_START)
    end = css.index(PREVIEW_CSS_END, start)
    return css[start:end]


def _guarded(code: str, needle: str) -> bool:
    """Every occurrence of `needle` sits between a `try` and a later `catch`
    (test_task_pane_tick_ui.py's naive region scan, same house posture)."""
    try_at = [m.start() for m in re.finditer(r"\btry\b", code)]
    catch_at = [m.start() for m in re.finditer(r"\bcatch\b", code)]
    seen = False
    for m in re.finditer(re.escape(needle), code):
        seen = True
        at = m.start()
        if not any(t < at for t in try_at) or not any(c > at for c in catch_at):
            return False
    return seen


# ------------------------------------------- (a) the real server: seam shape


def test_the_preview_page_carries_exactly_one_module_tag(served):
    """GREEN GUARD today (and the structural premise of the whole slice):
    the save glue rides in as an IMPORT of the tagged module, never as a
    second tag. The preview response of a threaded page carries the
    taskpane-ticks.js tag exactly once (the reload probe's preview.js tag is
    the page's other module -- the pane's own module count stays one)."""
    app, client = served
    page = _preview_page(client, app)
    assert page.count(_TICKS_TAG) == 1
    assert page.count('src="/edit/static/taskpane-ticks.js"') == 1


def test_the_save_glue_is_served_as_javascript(served):
    """RED today (404: the module does not exist; tick-save.js is the green
    half): GET /edit/static/taskpane-save.js and /edit/static/tick-save.js
    serve 200 JavaScript, byte for byte. The relative imports of the tagged
    module resolve at the real URL -- a 404 module is a blank pane with the
    save silently dead, and CSP script-src 'self' forbids any other origin
    to cover for it."""
    _app, client = served
    for name in (SAVE, MODEL):
        status, headers, data = client.page(f"/edit/static/{name}")
        assert status == 200, name
        assert headers["content-type"].startswith("text/javascript"), name
        with open(os.path.join(STATIC_DIR, name), "rb") as fh:
            assert data == fh.read(), name


def test_the_built_site_ships_none_of_the_save_glue(tmp_path):
    """GREEN GUARD today (Q9 'confirmed, enforced by test'; the W5b.3 walk,
    widened to this slice's needles): every byte `refdes build` writes
    carries no save module, no tick-save module, no module tag, neither new
    class, no token string, no write route. The write-capable pane lives in
    the serve response and nowhere in the generation."""
    config = _warm(tmp_path)
    assert cli_mod.main(["-c", config, "build"]) == 0
    out = os.path.join(str(tmp_path), "_site")
    needles = (
        SAVE,
        MODEL,
        _TICKS_TAG,
        "refdes-taskpane-save",
        "refdes-taskpane-conflict",
        "X-Refdes-Token",
        "?token=",
        "/api/",
        "/continue",
    )
    seen_html = False
    for rel, text in _walk_text(out):
        for needle in needles:
            assert needle not in text, (rel, needle)
        if rel.endswith("log-002.html"):
            seen_html = True
    assert seen_html, "the build wrote no item page: the walk proved nothing"


def test_the_preview_css_block_grows_the_save_and_conflict_rules():
    """RED today: the save button and the conflict panel are styled in the
    PREVIEW-ONLY marked block of taskpane.css (the response injects it, the
    build strips it -- the pair the next test pins). Comments stripped
    first: a comment merely naming a class is not a style."""
    with open(TASKPANE_CSS, encoding="utf-8") as fh:
        css = _preview_block(fh.read())
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for selector in (".refdes-taskpane-save", ".refdes-taskpane-conflict"):
        rule = re.search(r"(?m)^[ \t]*" + re.escape(selector) + r"[ \t]*\{", css)
        assert rule, f"the preview CSS block has no {selector} rule"


def test_the_built_stylesheet_stays_byte_identical(tmp_path):
    """GREEN GUARD today (R3's CSS half, byte-identity in the W5b.3 style):
    the built stylesheets carry neither marker nor this slice's selectors,
    and the built taskpane.css equals the source minus the marked block,
    byte for byte -- whatever the slice ADDS to the block, the build must
    keep stripping the whole of it."""
    config = _warm(tmp_path)
    assert cli_mod.main(["-c", config, "build"]) == 0
    assets = os.path.join(str(tmp_path), "_site", "assets")
    names = set(os.listdir(assets))
    assert "taskpane.css" in names
    glue_selectors = (".refdes-taskpane-save", ".refdes-taskpane-conflict")
    for name in sorted(n for n in names if n.endswith(".css")):
        with open(os.path.join(assets, name), encoding="utf-8") as fh:
            text = fh.read()
        assert PREVIEW_CSS_START not in text, name
        assert PREVIEW_CSS_END not in text, name
        for selector in glue_selectors:
            assert selector not in text, (name, selector)
    with open(os.path.join(assets, "taskpane.css"), "rb") as fh:
        built_css = fh.read()
    with open(TASKPANE_CSS, "rb") as fh:
        expected_css = PREVIEW_CSS_BYTES_RE.sub(b"", fh.read(), count=1)
    assert built_css == expected_css


# --------------------------------- (a) the real route: ref forms, 409 shape


def test_the_continue_route_resolves_the_key_and_the_display_id(served):
    """GREEN GUARD today -- the RUN the task asks for, so the implementer
    names the right ref: with a warmed fixture, POST /api/item/<ref>/continue
    APPLIES under BOTH spellings -- the tip's surrogate key (resolution.py
    step 1: the project.items dict key) and its display id (step 2,
    item_by_ref). The panels carry data-refdes-tip-key, so the glue posts the
    KEY: the identity that survives a rename (Q5a). A stale revision is the
    409 the conflict flow consumes."""
    app, client = served
    project = app.state.snapshot.project
    key = project.item_by_id("LOG-002").key
    assert key
    rev0 = _sha(project.root, "log.yaml")
    status, payload = client.api_post(
        "/api/item/" + urllib.parse.quote(key, safe="") + "/continue",
        {"ticks": [["T-thermal-model", "done"]], "expected_revision": rev0},
    )
    assert status == 200 and payload["kind"] == "applied", payload
    # move the file behind the pane's back
    applied = edit_mod.apply_edit(
        project.root,
        edit_mod.EditRequest(
            who="other-author",
            ref="LOG-001",
            op=edit_mod.SetField("summary", "Power work list, reworded."),
            expected_revision=_sha(project.root, "log.yaml"),
        ),
        config_path=str(app.state.config_path),
    )
    assert isinstance(applied, edit_mod.Applied), applied.message
    status2, payload2 = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-input-range", "open"]], "expected_revision": rev0},
    )
    assert status2 == 409 and payload2["kind"] == "conflict", payload2
    status3, payload3 = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-input-range", "open"]], "expected_revision": _sha(project.root, "log.yaml")},
    )
    assert status3 == 200 and payload3["kind"] == "applied", payload3


def test_the_conflict_answer_carries_no_task_rows(served):
    """GREEN GUARD today (the reason the glue must fetch the page): the 409
    body is exactly the W5b.2 shape -- kind/ok/message/path,
    expected_revision, current_revision, current_text (RAW disk text), diff.
    It carries NO structured task rows, so `describeConflict` can only be
    fed rows the glue reads from the CURRENT page -- which is why the
    conflict branch of the seam GETs location.href and parses it."""
    app, client = served
    project = app.state.snapshot.project
    rev0 = _sha(project.root, "log.yaml")
    applied = edit_mod.apply_edit(
        project.root,
        edit_mod.EditRequest(
            who="other-author",
            ref="LOG-001",
            op=edit_mod.SetField("summary", "Power work list, reworded."),
            expected_revision=rev0,
        ),
        config_path=str(app.state.config_path),
    )
    assert isinstance(applied, edit_mod.Applied), applied.message
    status, payload = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-thermal-model", "done"]], "expected_revision": rev0},
    )
    assert status == 409
    assert payload["kind"] == "conflict"
    assert set(payload) == {
        "kind",
        "ok",
        "message",
        "path",
        "expected_revision",
        "current_revision",
        "current_text",
        "diff",
    }
    assert "rows" not in payload and "tasks" not in payload
    assert isinstance(payload["current_text"], str)


# ----------------------------------------------------- (b) source pins, seam


def test_the_save_module_imports_the_pure_modules_never_the_glue():
    """RED today (no such file): the seam is the ONLY network module and it
    decides nothing of its own -- it imports ./tick-save.js (the pure model)
    and ./tick-pane.js (panelFromRows for the current page's rows), and NOT
    ./taskpane-ticks.js (the glue imports the seam: a cycle is a module that
    never evaluates). Every import target exists beside it."""
    code = _save_code()
    for name in (MODEL, PANE):
        assert IMPORT_OF[name].search(code), f"{SAVE} must import ./{name}"
    assert not IMPORT_OF.get(GLUE) and f"./{GLUE}" not in code, (
        f"{SAVE} imports the glue: taskpane-ticks.js imports {SAVE}, so this is a cycle"
    )
    for target in JS_IMPORT.findall(code):
        target = target.removeprefix("./")
        assert os.path.isfile(os.path.join(STATIC_DIR, target)), (
            f"{SAVE} imports a module that does not exist: {target}"
        )


def test_the_save_module_makes_exactly_two_fetches():
    """RED today: one POST (buildSaveRequest's path, method POST, the
    same-origin credentials the session cookie rides on, JSON content type)
    and the ONE GET of the current page the conflict branch needs --
    location.href, same-origin. A third fetch is a second seam nothing
    pins; zero GETs means the conflict branch reads rows out of the 409,
    which carries none (pinned above)."""
    code = _save_code()
    assert len(FETCH_CALL.findall(code)) == 2, (
        f"{SAVE} must fetch exactly twice: the save POST and the conflict page GET"
    )
    assert re.search(r"method\s*:\s*['\"]POST['\"]", code)
    assert "credentials" in code and "same-origin" in code
    assert "Content-Type" in code and "application/json" in code
    assert "location.href" in code, "the conflict branch must GET the current page"


def test_the_save_module_reads_the_token_from_the_meta_only():
    """RED today: the token seam. The header is X-Refdes-Token; its value is
    read from meta[name="refdes-token"] AT SAVE TIME (the page's meta, the
    same one the reload probe writes -- a token baked at module load survives
    nothing); and the token is data that never leaks: not into a URL
    (?token=), not into storage (the module touches NO storage at all -- the
    drafts store owns it), not into document.cookie, and never a textContent
    (the pane renders task text and model strings, never the token)."""
    code = _save_code()
    assert "X-Refdes-Token" in code
    assert re.search(r"""querySelector\(\s*['"]meta\[name=["']?refdes-token""", code), (
        f'{SAVE} must read the token from meta[name="refdes-token"]'
    )
    for needle in FORBIDDEN:
        assert needle not in code, f"{SAVE} grew {needle!r}"
    assert not re.search(r"textContent\s*=\s*[^;\n]*token", code, re.IGNORECASE), (
        f"{SAVE} writes the token into a textContent"
    )


def test_the_save_module_is_inert_markup():
    """RED today: the CSP rules of tests/test_serve_static.py, applied to
    this module (imported, not re-typed): no inline handler, no eval/new
    Function, no javascript: URL. The pane renders the server's refusal text,
    the task ids, and the conflict rows -- all authored data -- through
    textContent on createElement nodes ONLY: no innerHTML/outerHTML/
    insertAdjacentHTML/document.write. Parseable: brackets balanced, no
    duplicate top-level declarations (the test_task_pane_tick_ui.py shape)."""
    code = _save_code()
    assert not INLINE_HANDLER.search(code), "an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(code)
    assert "createElement" in code
    assert "textContent" in code
    depth = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    in_string = None
    escaped = False
    for ch in code:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in "'\"`":
            in_string = ch
        elif ch in depth:
            stack.append(depth[ch])
        elif stack and ch in ")]}":
            assert stack.pop() == ch, "unbalanced bracket in the save module"
    assert not stack, f"unclosed {stack}"
    top = re.findall(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", code, re.MULTILINE)
    assert len(top) == len(set(top)), "duplicate top-level declaration"


def test_the_save_module_wraps_the_clipboard_and_ships_no_unload_prompt():
    """RED today: Copy-it-out tries navigator.clipboard.writeText, and a
    clipboard that refuses (no permission, no clipboard API on a plain-HTTP
    origin) must cost the copy, never the pane -- so every writeText sits
    inside a try/catch. And NO beforeunload here: taskpane-ticks.js owns the
    page's single prompt (Q8), a second listener is a second prompt."""
    code = _save_code()
    assert "navigator.clipboard" in code
    assert "writeText" in code
    assert _guarded(code, "writeText"), f"{SAVE} calls clipboard.writeText outside a try/catch"
    assert "beforeunload" not in code, (
        f"{SAVE} registers a second unload prompt: the glue owns the page's one"
    )


def test_the_glue_gains_the_save_hook_and_no_network():
    """RED today on the hook (import + call absent), and the old pin
    re-asserted (it STAYS true, unedited, per the task's structure):
    taskpane-ticks.js imports ./taskpane-save.js, calls initSave({drafts,
    panels, refreshPanel}) exactly once -- hooks, not the network -- and
    still contains none of fetch/XMLHttpRequest/X-Refdes-Token//api/; no
    reload, no clipboard, no token string. The W5b.3 purity of the glue is
    the reason the save lives in its own module."""
    code = _glue_code()
    assert GLUE_IMPORT_OF_SAVE.search(code), f"{GLUE} must import ./{SAVE}"
    assert "initSave" in code
    calls = re.findall(r"\binitSave\(([^)]*)\)", code)
    assert len(calls) == 1, f"{GLUE} must call initSave exactly once, found {len(calls)}"
    for name in ("drafts", "panels", "refreshPanel"):
        assert name in calls[0], f"initSave must receive {name} (the entry seam)"
    for needle in GLUE_FORBIDDEN:
        assert needle not in code, f"{GLUE} grew {needle!r}: the network lives in {SAVE}"
    assert len(re.findall(r"""addEventListener\(\s*['"]beforeunload['"]""", code)) == 1, (
        f"{GLUE} must keep the page's exactly-one beforeunload listener"
    )


def test_the_save_module_names_the_dom_contract():
    """RED today: the exact names the browser harness queries -- the Save
    button's class, the conflict panel's class, the three outcome labels
    verbatim (Q3's ratified three, spelled so the JS, the CSS, and the
    verifier's script cannot drift), the role=alert channel, the read-only
    textarea of Copy-it-out, the markup attributes it reads, and the meta
    selector it reads the token from."""
    code = _save_code()
    for name in DOM_CONTRACT:
        assert name in code, f"{SAVE} lost the contract name {name!r}"


# ------------------------------------------------- (c) the node run of the seam

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120

HARNESS = """
const STATIC = __STATIC__;
const PAGE = __PAGE__;
const url = (name) => `file://${STATIC}/${name}`;

// What is faked, plainly: a DOM of plain nodes built by createElement (no
// layout, no CSS, no real event dispatch beyond a recorded click listener);
// a fetch that records (url, init) and answers scripted {status, json, text}
// (no cookies, no CSP -- browser-only, listed in the test docstring); a
// location that counts reload() calls; a clipboard that records text; and a
// DOMParser stub that reads data-refdes-* attributes out of the page text it
// was handed -- attribute extraction over the real page text, not a browser.
class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.parentNode = null;
    this.listeners = {};
    this._text = "";
    this.type = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.readOnly = false;
    this.value = "";
    this.checked = false;
  }
  get parentElement() { return this.parentNode; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this.children.length
      ? this.children.map((c) => c.textContent).join("")
      : this._text;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] === undefined ? null : this.attrs[name]; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  insertBefore(child, ref) {
    child.parentNode = this;
    const at = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(at < 0 ? this.children.length : at, 0, child);
    return child;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
  }
  // The honest slice of event dispatch: a listener the seam registered on
  // this very node, called with a plain event object. NO bubbling, NO real
  // Event -- the harness fires 'change' on the panel where a checkbox click
  // would bubble in a real DOM (browser-only fidelity, listed above).
  fire(type) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {} }); }
  querySelectorAll(sel) {
    const out = [];
    const want = (node) => {
      if (sel.startsWith(".") && node.className.split(/\\s+/).includes(sel.slice(1))) out.push(node);
      if (sel.startsWith("[") && node.getAttribute(sel.slice(1, -1)) !== null) out.push(node);
      if (sel === "button" && node.tagName === "BUTTON") out.push(node);
    };
    const walk = (node) => { want(node); for (const c of node.children) walk(c); };
    walk(this);
    return out;
  }
  click() { for (const fn of this.listeners.click || []) fn({ preventDefault() {} }); }
}

const store = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const TOKEN = "tok-1";
const metaQuery = [];
globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector(sel) {
    metaQuery.push(sel);
    if (sel.includes("refdes-token")) return { content: TOKEN };
    return null;
  },
  querySelectorAll: () => [],
};
globalThis.window = { addEventListener: () => {} };

let reloads = 0;
globalThis.location = {
  href: "http://127.0.0.1:8123/preview/log-002.html",
  reload() { reloads += 1; },
};

const copies = [];
// node >= 21 ships a real `navigator` global with a getter-only slot, so a
// plain assignment throws; defineProperty replaces the slot honestly.
Object.defineProperty(globalThis, "navigator", {
  value: { clipboard: { writeText: async (t) => { copies.push(String(t)); } } },
  configurable: true,
  writable: true,
});

const posts = [];
const gets = [];
let queue = []; // scripted answers for the POSTs, in order: {status, json, text, throws}
let pageText = PAGE;
globalThis.fetch = async (path, init) => {
  const method = (init && init.method) || "GET";
  const headers = (init && init.headers) || {};
  if (method === "POST") {
    posts.push({
      url: String(path),
      method,
      credentials: (init && init.credentials) || null,
      headers: {
        "Content-Type": headers["Content-Type"] === undefined ? null : headers["Content-Type"],
        "X-Refdes-Token": headers["X-Refdes-Token"] === undefined ? null : headers["X-Refdes-Token"],
      },
      body: init && init.body ? JSON.parse(init.body) : null,
    });
    const next = queue.shift();
    if (!next) throw new Error("harness: no scripted POST answer left");
    if (next.throws) throw new Error("transport down");
    return {
      ok: next.status === 200,
      status: next.status,
      json: async () => next.json,
      text: async () => next.text === undefined ? "" : next.text,
    };
  }
  gets.push({ url: String(path), method });
  return { ok: true, status: 200, text: async () => pageText };
};

const parseCount = [];
class FakeParsedDoc {
  constructor(text) { this.text = text; }
  querySelectorAll(sel) {
    if (sel !== ".refdes-taskpane-panel") return [];
    const tags = [...this.text.matchAll(/<div class="refdes-taskpane-panel"[^>]*>[\\s\\S]*?(?=<div class="refdes-taskpane-panel"|<\\/aside>)/g)];
    return tags.map((m) => {
      const panel = new FakeNode("div");
      panel.className = "refdes-taskpane-panel";
      for (const a of m[0].matchAll(/([\\w-]+)="([^"]*)"/g)) panel.setAttribute(a[1], a[2]);
      panel.querySelectorAll = (inner) => {
        if (inner !== "input[data-refdes-task]") return [];
        return [...m[0].matchAll(/<input[^>]*data-refdes-task="[^"]*"[^>]*>/g)].map((im) => {
          const box = new FakeNode("input");
          for (const a of im[0].matchAll(/([\\w-]+)="([^"]*)"/g)) box.setAttribute(a[1], a[2]);
          box.checked = /checked=/.test(im[0]);
          return box;
        });
      };
      return panel;
    });
  }
}
globalThis.DOMParser = class {
  parseFromString(text, type) { parseCount.push(String(type)); return new FakeParsedDoc(text); }
};

const { createTickDrafts } = await import(url("tick-drafts.js"));
const { initSave } = await import(url("taskpane-save.js"));

function freshPanel(tipKey, revision) {
  const drafts = createTickDrafts(globalThis.sessionStorage);
  const panelEl = new FakeNode("div");
  panelEl.className = "refdes-taskpane-panel";
  panelEl.setAttribute("data-refdes-tip-key", tipKey);
  panelEl.setAttribute("data-refdes-revision", revision);
  const status = panelEl.appendChild(new FakeNode("p"));
  status.className = "refdes-taskpane-tick-status";
  const discard = panelEl.appendChild(new FakeNode("button"));
  discard.className = "refdes-taskpane-discard";
  return { drafts, panelEl, entry: { tipKey, revision, canDraft: true, panelEl, status, discard } };
}

function findButton(root, cls) {
  return root.querySelectorAll("." + cls).filter((n) => n.tagName === "BUTTON")[0] || null;
}
function findClass(root, cls) {
  return root.querySelectorAll("." + cls)[0] || null;
}
function buttonsIn(root) {
  const labels = [];
  const walk = (node) => {
    if (node.tagName === "BUTTON") labels.push(node.textContent);
    for (const c of node.children) walk(c);
  };
  walk(root);
  return labels;
}
function alertTexts(root) {
  const out = [];
  const walk = (node) => {
    if (node.getAttribute("role") === "alert") out.push(node.textContent);
    for (const c of node.children) walk(c);
  };
  walk(root);
  return out;
}
const settle = () => new Promise((r) => setTimeout(r, 80));

const results = { ok: true };

async function scenario(name, run) {
  // each scenario is its OWN TAB: a fresh mirror, like a fresh page
  store.clear();
  posts.length = 0; gets.length = 0; copies.length = 0; metaQuery.length = 0;
  parseCount.length = 0;
  reloads = 0; queue = []; pageText = PAGE;
  try {
    // snapshot: scenario results must not alias the live recorder arrays
    // (a later scenario clears them, and the JSON prints only at the end)
    results[name] = JSON.parse(JSON.stringify(await run()));
  } catch (err) { results[name] = { harnessError: String(err && err.stack || err) }; }
}

const TIP = "KEY-A";
const REV = "REV-0";

// -- saved: the POST is the built request; then discard + reload, once.
await scenario("saved", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  const hiddenWhenClean = findButton(panelEl, "refdes-taskpane-save").hidden;
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  const visible = !save.hidden;
  queue = [{ status: 200, json: { kind: "applied", ok: true, message: "applied: continuation LOG-003 appended", revision: "REV-1", id: "LOG-003", handle: "bz99", path: "items/log.yaml" } }];
  save.click();
  const inFlight = { disabled: save.disabled, posts: posts.length };
  await settle();
  return {
    visible, hiddenWhenClean, inFlight,
    post: posts[0] || null,
    reloads,
    pending: drafts.pendingCount(TIP),
    alerts: alertTexts(panelEl),
  };
});

// -- refused (422): message in role=alert, draft kept, Save usable again.
await scenario("refused", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ status: 422, json: { kind: "refused", reason: "the fold refuses T-alpha on this tip", message: "the fold refuses T-alpha on this tip" } }];
  save.click();
  await settle();
  return {
    alerts: alertTexts(panelEl),
    reloads,
    pending: drafts.pendingCount(TIP),
    disabled: save.disabled,
    posts: posts.length,
  };
});

// -- transport failure: {status: 0} reads as the model's one safe line.
await scenario("transport", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ throws: true }];
  save.click();
  await settle();
  return {
    alerts: alertTexts(panelEl),
    reloads,
    pending: drafts.pendingCount(TIP),
    disabled: save.disabled,
  };
});

// -- conflict: the page GET happens; the panel shows the rows and the three.
await scenario("conflict", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setTick(TIP, "T-beta", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ status: 409, json: { kind: "conflict", ok: false, message: "conflict: items/log.yaml changed", path: "items/log.yaml", expected_revision: REV, current_revision: "REV-9", current_text: "raw yaml text", diff: "" } }];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  const buttons = panel ? buttonsIn(panel) : [];
  return {
    gets,
    parses: parseCount,
    hasPanel: Boolean(panel),
    text: panel ? panel.textContent : "",
    buttons,
    reloads,
    pending: drafts.pendingCount(TIP),
  };
});

// -- keep mine: MY pairs re-stamped on the CURRENT tip key + revision, reload.
await scenario("keepMine", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setTick(TIP, "T-beta", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ status: 409, json: { kind: "conflict", message: "conflict: the file moved", expected_revision: REV, current_revision: "REV-9", current_text: "raw", diff: "" } }];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  const mine = buttonsIn(panel);
  const button = panel.children.filter((c) => c.tagName === "BUTTON" && c.textContent === "Keep mine")[0];
  button.click();
  await settle();
  return {
    buttons: mine,
    reloaded: reloads,
    revision: drafts.revision(TIP),
    ticks: drafts.pendingTicks(TIP),
  };
});

// -- keep theirs: discard my draft, reload onto their list.
await scenario("keepTheirs", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ status: 409, json: { kind: "conflict", message: "conflict: the file moved", expected_revision: REV, current_revision: "REV-9", current_text: "raw", diff: "" } }];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  const button = panel.children.filter((c) => c.tagName === "BUTTON" && c.textContent === "Keep theirs")[0];
  button.click();
  await settle();
  return { reloaded: reloads, pending: drafts.pendingCount(TIP) };
});

// -- copy it out: a read-only transcript of MY ticks, clipboard tried.
await scenario("copyOut", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setTick(TIP, "T-beta", "open", "done");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ status: 409, json: { kind: "conflict", message: "conflict: the file moved", expected_revision: REV, current_revision: "REV-9", current_text: "raw", diff: "" } }];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  const button = panel.children.filter((c) => c.tagName === "BUTTON" && c.textContent === "Copy it out")[0];
  button.click();
  await settle();
  let box = null;
  const walk = (node) => { if (node.tagName === "TEXTAREA") box = box || node; for (const c of node.children) walk(c); };
  walk(panelEl);
  return {
    text: box ? box.value || box.textContent : null,
    readOnly: box ? box.readOnly === true || box.getAttribute("readonly") !== null : null,
    copies,
    reloads,
    pending: drafts.pendingCount(TIP),
  };
});

// -- the page moved on without this thread: say so, offer only two outcomes.
await scenario("noPanel", async () => {
  pageText = '<div class="refdes-taskpane-panel" data-refdes-tip-key="OTHER-KEY" data-refdes-revision="REV-Z"><input data-refdes-task="T-x" data-refdes-task-state="open" data-refdes-tick-states="done,dropped"></div></aside>';
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [{ status: 409, json: { kind: "conflict", message: "conflict: the file moved", expected_revision: REV, current_revision: "REV-9", current_text: "raw", diff: "" } }];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  return {
    hasPanel: Boolean(panel),
    text: panel ? panel.textContent : "",
    buttons: panel ? buttonsIn(panel) : [],
    reloads,
    pending: drafts.pendingCount(TIP),
  };
});

// -- the in-flight gate: disabled while a save runs, enabled after (saved path).
await scenario("inFlight", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  const cleanHidden = findButton(panelEl, "refdes-taskpane-save").hidden;
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // a checkbox change bubbling to the panel (see FakeNode.fire)
  const save = findButton(panelEl, "refdes-taskpane-save");
  const enabled = !save.hidden && !save.disabled;
  queue = [{ throws: true }];
  save.click();
  const mid = { disabled: save.disabled };
  await settle();
  return { cleanHidden, enabled, midFlightDisabled: mid.disabled, afterDisabled: save.disabled };
});

console.log(JSON.stringify(results));
"""

# The current page the DOMParser stub reads: the tip moved (REV-9), a row
# vanished (T-beta is gone), a new row joined (T-gamma) -- the conflict panel
# must show the CURRENT list in CURRENT order with my vanished row appended.
PAGE = (
    "<html><body>"
    '<div class="refdes-taskpane-panel" data-refdes-tip-key="KEY-A" data-refdes-revision="REV-9">'
    '<input data-refdes-task="T-alpha" data-refdes-task-state="open" data-refdes-tick-states="done,dropped">'
    '<input data-refdes-task="T-gamma" data-refdes-task-state="open" data-refdes-tick-states="done,dropped" checked="checked">'
    "</div></aside></body></html>"
)


@pytest.fixture(scope="module")
def node_results():
    if NODE is None:
        return {"__skipped__": "no node on PATH to run the served save module"}
    script = HARNESS.replace("__STATIC__", json.dumps(STATIC_DIR.replace(os.sep, "/"))).replace(
        "__PAGE__", json.dumps(PAGE)
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        return {"__red__": f"node exited {proc.returncode}:\n{proc.stderr[-4000:]}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"__red__": f"node printed no results:\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}"}


def _scenario(node_results, name):
    if "__skipped__" in node_results:
        pytest.skip(node_results["__skipped__"])
    if "__red__" in node_results:
        pytest.fail(f"RED today: the seam does not run under node.\n{node_results['__red__']}")
    assert name in node_results, f"the harness reported no {name!r} scenario"
    got = node_results[name]
    assert "harnessError" not in got, got["harnessError"]
    return got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_the_save_posts_the_built_request_with_the_token(node_results):
    """RED today: the POST goes to buildSaveRequest's path -- /api/item/<the
    panel's tip KEY>/continue (percent-encoded segment, the key the panel
    carries) -- with the JSON content type, X-Refdes-Token read from the
    page's meta at click time, credentials same-origin (the session cookie),
    and the body the model built: {ticks, expected_revision}, nothing else."""
    got = _scenario(node_results, "saved")
    assert got.get("visible") is True, got
    post = got["post"]
    assert post["url"] == "/api/item/KEY-A/continue"
    assert post["method"] == "POST"
    assert post["credentials"] == "same-origin"
    assert post["headers"]["Content-Type"] == "application/json"
    assert post["headers"]["X-Refdes-Token"] == "tok-1"
    assert post["body"] == {"ticks": [["T-alpha", "done"]], "expected_revision": "REV-0"}


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_saved_save_discards_the_draft_and_reloads_once(node_results):
    """RED today: the ratified landing -- the draft is discarded under the
    tip key (the mirror key goes with it), location.reload() runs ONCE (the
    new entry is the tip; the preview re-renders from the server), and no
    alert is shown."""
    got = _scenario(node_results, "saved")
    assert got["reloads"] == 1, got
    assert got["pending"] == 0, got
    assert got["alerts"] == [], got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_refused_save_shows_the_message_and_keeps_the_draft(node_results):
    """RED today (Q3's refusal contract, the author's verbs): the server's
    message lands in a role=alert element (via textContent -- the model
    ships plain strings), the draft SURVIVES untouched, no reload, and Save
    is enabled again (the author fixes and retries)."""
    got = _scenario(node_results, "refused")
    assert any("the fold refuses T-alpha on this tip" in t for t in got["alerts"]), got
    assert got["reloads"] == 0, got
    assert got["pending"] == 1, got
    assert got["disabled"] is False, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_transport_failure_is_reported_and_the_draft_survives(node_results):
    """RED today: a round trip that refuses to start (fetch throws) becomes
    the model's {status: 0} -- the one safe 'did not reach the server' line
    in the alert, draft kept, no reload, Save usable. No status was invented
    for a request that got no answer."""
    got = _scenario(node_results, "transport")
    assert any("did not reach the server" in t for t in got["alerts"]), got
    assert got["reloads"] == 0, got
    assert got["pending"] == 1, got
    assert got["disabled"] is False, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_conflict_refetches_the_page_and_offers_exactly_three(node_results):
    """RED today (Q3 RATIFIED (a), the centre of the slice): on 409 the seam
    GETs location.href -- same-origin, no token header -- parses it with
    DOMParser, and shows a .refdes-taskpane-conflict panel with the current
    tip's rows against MY ticks (describeConflict: current order first, my
    vanished T-beta appended), and EXACTLY the three ratified outcomes, in
    order, with nothing that merges. The draft survives the conflict itself."""
    got = _scenario(node_results, "conflict")
    assert got["gets"] == [{"url": "http://127.0.0.1:8123/preview/log-002.html", "method": "GET"}], got
    assert got["parses"], got
    assert got["hasPanel"], got
    text = got["text"]
    for row in ("T-alpha", "T-gamma", "T-beta"):
        assert row in text, (row, text)
    assert got["buttons"] == ["Keep mine", "Keep theirs", "Copy it out"], got
    assert got["reloads"] == 0, got
    assert got["pending"] == 2, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_keep_mine_stamps_the_current_tip_and_reloads(node_results):
    """RED today: Keep mine re-stamps MY ticks on the CURRENT identity --
    the current tip key (the page's panel: KEY-A) with the CURRENT revision
    (REV-9), T-beta dropped (its row is gone: a keep-mine never invents a
    row, and never merges), then reloads so the author sees the draft
    against the new list and can Save again."""
    got = _scenario(node_results, "keepMine")
    assert got["buttons"] == ["Keep mine", "Keep theirs", "Copy it out"], got
    assert got["reloaded"] == 1, got
    assert got["revision"] == "REV-9", got
    assert got["ticks"] == [["T-alpha", "done"]], got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_keep_theirs_discards_and_reloads(node_results):
    """RED today: Keep theirs is the explicit release (Q8's Discard verb at
    the conflict moment): my draft is discarded, the page reloads onto the
    current list. Nothing of mine survives."""
    got = _scenario(node_results, "keepTheirs")
    assert got["reloaded"] == 1, got
    assert got["pending"] == 0, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_copy_it_out_shows_a_readonly_transcript(node_results):
    """RED today: Copy it out shows copyOut.text -- MY lines, MY order,
    MY states -- in a READ-ONLY textarea, and tries the clipboard inside a
    try/catch (a refused clipboard costs the copy, never the pane: the
    textarea stands). No reload, the draft kept: the author copies before
    choosing."""
    got = _scenario(node_results, "copyOut")
    assert got["text"], got
    assert "T-alpha: done" in got["text"], got
    assert "T-beta: open" in got["text"], got
    assert got["readOnly"] is True, got
    assert got["copies"] == [got["text"]], got
    assert got["reloads"] == 0, got
    assert got["pending"] == 2, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_moved_thread_with_no_panel_offers_only_two(node_results):
    """RED today: when the re-fetched page has no panel for this thread (the
    thread's tips all moved away), the seam says so plainly and offers ONLY
    Copy it out + Keep theirs -- Keep mine would stamp onto a panel the page
    does not show, and inventing one is the merge the design refuses. The
    draft is kept for the author to copy."""
    got = _scenario(node_results, "noPanel")
    assert got["hasPanel"], got
    assert "no panel" in got["text"].lower() or "not" in got["text"].lower(), got["text"]
    assert got["buttons"] == ["Keep theirs", "Copy it out"], got
    assert got["reloads"] == 0, got
    assert got["pending"] == 1, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_the_save_gate_tracks_pending_ticks_and_flight(node_results):
    """RED today: the Save button is hidden while the panel is clean, shown
    once a tick is pending, disabled while a save is in flight, and enabled
    again after a failed one (the author's retry)."""
    got = _scenario(node_results, "inFlight")
    assert got["cleanHidden"] is True, got
    assert got["enabled"] is True, got
    assert got["midFlightDisabled"] is True, got
    assert got["afterDisabled"] is False, got
