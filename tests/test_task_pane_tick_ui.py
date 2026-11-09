"""Thread workbench W5b.4c-1b contract: the pane's DOM glue.

docs/design/thread-workbench-w5b-plan.md §4 W5b.4 + §6 Q1/Q3/Q5/Q6/Q8 (all
RATIFIED 2026-11-06). W5b.4c-1a shipped the pure decision module
(`tick-pane.js`) and W5b.4b the pure store (`tick-drafts.js`); this slice
wires them to the served page: `taskpane-ticks.js` grows, with relative
imports of both, the glue that reads the pane's markup, restores a draft,
answers checkbox changes, shows the header count, offers Discard, and asks
`beforeunload`. The Save is W5b.4c-2, NOT this slice: the file keeps the
W5b.3 pin that it contains no fetch, no XMLHttpRequest, no token and no
/api/ route.

What a headless suite can pin, this file pins:

(a) the real server: all three modules are served as JavaScript at
    /edit/static/ (the relative imports resolve to served files), the
    threaded preview page carries the `type="module"` tag, and the built
    site carries none of it (the R3/Q9 byte-identity pair, W5b.3's
    approach);
(b) the source pins over the comment-stripped module: it imports both
    siblings by relative path, calls their named exports, touches
    `sessionStorage` only inside a try/catch (a storage that throws must
    degrade, never break the pane -- Q1b), registers exactly ONE
    `beforeunload` listener whose condition is the pure
    `needsUnloadPrompt`, renders through `textContent` only, and stays
    clean of network/token/eval/markup-parsing/inline-handler strings
    (the `tests/test_serve_static.py` rules, imported, not re-typed).

(c) runtime behaviour -- restore on load, pending-row classes, the
    indicator's live text, Discard, the unload prompt, disabled id-less
    rows, the keyless panel's preview-only wording -- needs a real DOM.
    A hand-built node tree under a faked querySelectorAll is not an honest
    fake, so NO node-DOM harness is written here: those behaviours are
    listed in in-prog-logs/w5b4c1b-tests.md for browser verification in
    Chromium and Firefox.

The DOM/markup contract pinned by test_the_glue_names_the_dom_contract
(names the browser harness finds the glue's elements by):

  read from the served markup (W5b.3/4a, unchanged):
    panel      .refdes-taskpane-panel + data-refdes-tip-key,
               data-refdes-revision (absent on a keyless tip)
    checkbox   data-refdes-task (EMPTY for an id-less row),
               data-refdes-task-state, data-refdes-tick-states,
               data-refdes-tip
    header     .refdes-taskpane-head; tabs .refdes-taskpane-tab

  created by the glue (this slice's names):
    indicator  class refdes-taskpane-tick-status, role="status",
               aria-live="polite", text via textContent, hidden when the
               pure indicator() says hidden
    pending    class refdes-taskpane-tick-pending on the row's label
    discard    button (type="button") class refdes-taskpane-discard,
               label "Discard" via textContent, visible only when the
               active panel has pending ticks
    id-less    row: checkbox `disabled` with the model's plain-string
               reason in `title`

Tests named (red/green against the pre-glue module):
  test_the_served_glue_module_imports_its_two_siblings             RED
  test_the_glue_imports_both_pure_modules_by_relative_path         RED
  test_the_glue_uses_the_whole_pure_surface                        RED
  test_the_glue_touches_session_storage_only_inside_a_try          RED
  test_the_glue_registers_exactly_one_beforeunload_listener        RED
  test_the_glue_names_the_dom_contract                             RED
  test_the_preview_css_block_carries_the_glue_styles               RED
  test_all_three_glue_modules_are_served_as_javascript          green guard
  test_the_built_site_ships_none_of_the_glue                    green guard
  test_the_built_stylesheets_strip_the_whole_preview_block      green guard
  test_the_glue_stays_clean_of_network_tokens_markup_and_handlers green guard
"""

from __future__ import annotations

import os
import re

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
from refdes.serve.server import EditorApp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_REFDES = os.path.join(REPO_ROOT, "src", "refdes")
STATIC_DIR = os.path.join(SRC_REFDES, "serve", "static")
TASKPANE_CSS = os.path.join(SRC_REFDES, "templates", "taskpane", "taskpane.css")

GLUE = "taskpane-ticks.js"
DRAFTS = "tick-drafts.js"
PANE = "tick-pane.js"
MODULE_TAG = f'<script type="module" src="/edit/static/{GLUE}"></script>'

PREVIEW_CSS_START = "/* refdes:preview-css-start */"
PREVIEW_CSS_END = "/* refdes:preview-css-end */"
PREVIEW_CSS_BYTES_RE = re.compile(
    re.escape(PREVIEW_CSS_START.encode("utf-8"))
    + b".*?"
    + re.escape(PREVIEW_CSS_END.encode("utf-8")),
    re.DOTALL,
)

# The pure modules' names the glue must call (the seam between 4c-1a/4b and
# this slice: a glue that re-implements a rule in the DOM layer is the drift
# the pure modules exist to prevent).
DRAFTS_API = (
    "createTickDrafts",
    "setTick",
    "setRevision",
    "pendingCount",
    "pendingTicks",
    "counts",
    "discard",
)
PANE_API = (
    "panelFromRows",
    "wantedState",
    "applyDraft",
    "indicator",
    "isStale",
    "tabLabel",
    "needsUnloadPrompt",
    "discardPlan",
)

# The names of (c): the strings a browser harness queries. The served
# markup's names are already pinned by test_task_pane_ticks.py /
# test_task_pane_tick_context.py; pinning them HERE keeps this file's
# contract list complete, and the new (glue-created) names make the test
# red against the pre-glue module.
DOM_CONTRACT = (
    "refdes-taskpane-panel",
    "data-refdes-tip-key",
    "data-refdes-revision",
    "data-refdes-task",
    "data-refdes-task-state",
    "data-refdes-tick-states",
    "data-refdes-tip",
    "refdes-taskpane-head",
    "refdes-taskpane-tab",
    "refdes-taskpane-tick-pending",
    "refdes-taskpane-tick-status",
    "refdes-taskpane-discard",
    "aria-live",
    "polite",
    "Discard",
    "disabled",
)

# W5b.4c-1b's file ships NO network and NO markup parsing: the Save is
# 4c-2, CSP is script-src 'self', and the pane renders authored text (task
# rows, model reasons) through textContent only.
FORBIDDEN = (
    "fetch(",
    "XMLHttpRequest",
    "X-Refdes-Token",
    "refdes-token",
    "?token=",
    "/api/",
    "/continue",
    "eval",
    "new Function",
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "javascript:",
)

BEFOREUNLOAD_LISTENER = re.compile(r"""addEventListener\(\s*['"]beforeunload['"]""")
IMPORT_OF = {
    name: re.compile(r"""from\s+['"]\./""" + re.escape(name) + r"""['"]""")
    for name in (DRAFTS, PANE)
}

# A thread with the Q6 state vocabulary, in the plain-write (keyless) shape:
# every panel is preview-only markup here, which is exactly the fixture
# where the served seam (tags, modules, build absence) is pinnable.
ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
)

WITH_NAVI = ONE_TIP + (
    "  - id: LOG-900\n"
    "    summary: Navi reminder.\n"
    "    date: 2026-09-07\n"
    "    body: >\n"
    "      Check the board.\n"
    "      <!--navi: reminder-->\n"
)


def _write(tmp_path, items_yaml):
    write_project_config(
        tmp_path,
        "site: { title: Tick Pane UI, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_bytes(items_yaml.encode("utf-8"))
    return str(tmp_path / "refdes-project.yaml")


@pytest.fixture
def served(tmp_path_factory):
    config = _write(tmp_path_factory.mktemp("tick-ui"), ONE_TIP)
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


def _glue_code() -> str:
    """The glue module, comments stripped: the surface the pins assert on
    (a prose comment naming `fetch` is not a call; see test_serve_static)."""
    with open(os.path.join(STATIC_DIR, GLUE), encoding="utf-8") as fh:
        return strip_js_comments(fh.read())


def _preview_page(client, app) -> str:
    page = app.state.snapshot.project.item_by_id("LOG-002").slug + ".html"
    status, _headers, body = client.page(f"/preview/{page}")
    assert status == 200
    return body.decode("utf-8")


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


def _storage_is_guarded(code: str, needle: str) -> bool:
    """Every occurrence of `needle` sits between a `try` and a later
    `catch`. Naive by design (this repo's js scans are regex scans, not
    parsers): it pins that the access is inside SOME guarded region, which
    is the rule -- the pane must degrade, never break, on a throwing
    storage. A precise bracket walk buys nothing a browser can't check."""
    try_at = [m.start() for m in re.finditer(r"\btry\b", code)]
    catch_at = [m.start() for m in re.finditer(r"\bcatch\b", code)]
    seen = False
    for m in re.finditer(re.escape(needle), code):
        seen = True
        at = m.start()
        if not any(t < at for t in try_at) or not any(c > at for c in catch_at):
            return False
    return seen


# ------------------------------------------- the real server: tags and files

def test_all_three_glue_modules_are_served_as_javascript(served):
    """GREEN GUARD (the seam W5b.3/4b opened, re-pinned for the three-module
    graph): the threaded preview response carries the `type="module"` tag,
    and GET /edit/static/<name> serves all three modules as JavaScript --
    so the glue's relative imports (`./tick-drafts.js`, `./tick-pane.js`,
    same directory) resolve to served files at the real URL, not to a 404
    blank page. The body served is the packaged file, byte for byte."""
    app, client = served
    page = _preview_page(client, app)
    assert MODULE_TAG in page
    assert 'type="module"' in page
    for name in (GLUE, DRAFTS, PANE):
        status, headers, data = client.page(f"/edit/static/{name}")
        assert status == 200, name
        assert headers["content-type"].startswith("text/javascript"), name
        with open(os.path.join(STATIC_DIR, name), "rb") as fh:
            assert data == fh.read(), name


def test_the_served_glue_module_imports_its_two_siblings(served):
    """RED today: the module the browser fetches IS the glue -- it imports
    the draft store and the decision model by relative path. Pinned on the
    SERVED bytes (what the browser parses), not a file read: the transport
    is part of the contract (a relative import only resolves because
    _static serves the siblings at the sibling URL, pinned above)."""
    _app, client = served
    status, _headers, data = client.page(f"/edit/static/{GLUE}")
    assert status == 200
    code = strip_js_comments(data.decode("utf-8"))
    for name in (DRAFTS, PANE):
        assert IMPORT_OF[name].search(code), f"{GLUE} does not import ./{name}"


# ------------------------------------------------- the R3/Q9 pair, build side

def test_the_built_site_ships_none_of_the_glue(tmp_path):
    """GREEN GUARD (Q9 ratified "confirmed, enforced by test", §7a.6): walk
    every byte of `refdes build` -- no glue module, no module tag, neither
    pure module, no token string, no write route. The write-capable pane
    lives in the serve response and nowhere in the generation."""
    config = _write(tmp_path, ONE_TIP)
    assert cli_mod.main(["-c", config, "build"]) == 0
    out = os.path.join(str(tmp_path), "_site")
    needles = (GLUE, DRAFTS, PANE, MODULE_TAG, "X-Refdes-Token", "?token=", "/api/")
    seen_html = False
    for rel, text in _walk_text(out):
        for needle in needles:
            assert needle not in text, (rel, needle)
        if rel.endswith("log-002.html"):
            seen_html = True
    assert seen_html, "the build wrote no item page: the walk proved nothing"


def test_the_built_stylesheets_strip_the_whole_preview_block(tmp_path):
    """GREEN GUARD (R3's CSS half, W5b.3's byte-identity approach): the
    built stylesheets carry neither marker nor tick selector -- and this
    includes the selectors THIS slice adds to the marked block (pending
    row, indicator, discard): the strip is whole-block, so the built page
    can never style a control the built page does not have. The built
    taskpane.css equals the source minus the marked block, byte for byte."""
    config = _write(tmp_path, WITH_NAVI)
    assert cli_mod.main(["-c", config, "build"]) == 0
    assets = os.path.join(str(tmp_path), "_site", "assets")
    names = set(os.listdir(assets))
    assert {"taskpane.css", "navis.css"} <= names
    glue_selectors = (
        ".refdes-taskpane-tick-pending",
        ".refdes-taskpane-tick-status",
        ".refdes-taskpane-discard",
    )
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


def test_the_preview_css_block_carries_the_glue_styles():
    """RED today: the glue's UI is styled in the PREVIEW-ONLY marked block
    of taskpane.css (between the refdes:preview-css markers -- the build
    strips it, the response injects it). The pending-row class, the
    header indicator, and the Discard button each get a rule there;
    comments stripped first so a comment merely naming a class is not a
    style (the round-4 C4 lesson from test_task_pane_ticks.py)."""
    with open(TASKPANE_CSS, encoding="utf-8") as fh:
        css = _preview_block(fh.read())
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for selector in (
        ".refdes-taskpane-tick-pending",
        ".refdes-taskpane-tick-status",
        ".refdes-taskpane-discard",
    ):
        rule = re.search(r"(?m)^[ \t]*" + re.escape(selector) + r"[ \t]*\{", css)
        assert rule, f"the preview CSS block has no {selector} rule"


# --------------------------------------------------------- the glue's own rules

def test_the_glue_imports_both_pure_modules_by_relative_path():
    """RED today: the glue imports ./tick-drafts.js and ./tick-pane.js
    (relative, same directory -- CSP is script-src 'self', same origin),
    and every module the import graph names exists next to it (a typo'd
    import is a blank pane nothing else notices -- the
    test_serve_static.py import-graph rule, applied to this entry)."""
    code = _glue_code()
    for name in (DRAFTS, PANE):
        assert IMPORT_OF[name].search(code), f"{GLUE} must import './{name}'"
    for target in JS_IMPORT.findall(code):
        target = target.removeprefix("./")
        assert os.path.isfile(os.path.join(STATIC_DIR, target)), (
            f"{GLUE} imports a module that does not exist: {target}"
        )


def test_the_glue_uses_the_whole_pure_surface():
    """RED today: the seam between 4c-1a/4b and this slice is the glue
    CALLING the pure modules, not re-deciding in the DOM layer: store
    (createTickDrafts/setTick/setRevision/pendingCount/pendingTicks/
    counts/discard) and model (panelFromRows ... discardPlan) by name.
    The rule that lives twice is the rule that drifts; the decision lives
    in the pure modules, the DOM only renders it."""
    code = _glue_code()
    for name in DRAFTS_API + PANE_API:
        assert re.search(r"\b" + re.escape(name) + r"\b", code), (
            f"{GLUE} never calls {name}: the rule it encodes must not be "
            f"re-implemented in the DOM layer"
        )


def test_the_glue_touches_session_storage_only_inside_a_try():
    """RED today: Q1 (ratified (b)) puts the mirror in sessionStorage; the
    glue reaches it through `window.sessionStorage`, and the access is
    wrapped -- a storage that throws (blocked, private mode, quota) must
    cost persistence, never the pane (tick-drafts' own rule, and the
    page-level access throws before the store is built). Pinned structurally:
    every sessionStorage mention sits inside a try/catch region."""
    code = _glue_code()
    assert "sessionStorage" in code, f"{GLUE} must read the page's sessionStorage"
    assert _storage_is_guarded(code, "sessionStorage"), (
        f"{GLUE} touches sessionStorage outside a try/catch: a throwing "
        "storage must degrade the pane, never break it"
    )


def test_the_glue_registers_exactly_one_beforeunload_listener():
    """RED today: Q8 (ratified (a)) adds the editor's generic unload
    prompt. One listener on the page (a second is a second prompt and a
    leak), its condition is evaluated at event time from the pure
    needsUnloadPrompt over the store's counts(), and the prompt is the
    standard preventDefault + returnValue = '' shape."""
    code = _glue_code()
    assert len(BEFOREUNLOAD_LISTENER.findall(code)) == 1, (
        f"{GLUE} must register exactly one beforeunload listener"
    )
    assert "needsUnloadPrompt" in code  # the condition is the model's, not ad hoc
    assert "counts" in code  # ...over the store's counts(), at event time
    assert "preventDefault" in code
    assert "returnValue" in code


def test_the_glue_names_the_dom_contract():
    """RED today: the exact names the browser harness (Chromium/Firefox)
    queries, pinned as source strings so the JS and the harness cannot
    drift: the markup it reads (panel/checkbox/header/tab names from
    W5b.3/4a) and the elements it CREATES (pending-row class on the label,
    the header indicator with its aria-live/status semantics, the Discard
    button, the disabled id-less row). The full contract, spelled in this
    file's docstring."""
    code = _glue_code()
    for name in DOM_CONTRACT:
        assert name in code, f"{GLUE} lost the contract name {name!r}"


def test_the_glue_stays_clean_of_network_tokens_markup_and_handlers():
    """GREEN GUARD today (the W5b.3 pin STAYS true in this slice, per the
    task): the Save is 4c-2, so this module ships NO network, NO token, NO
    eval, NO markup parsing (innerHTML/outerHTML/insertAdjacentHTML/
    document.write -- the pane renders authored task text through
    textContent only), NO javascript: URL, and passes the
    tests/test_serve_static.py rules (imported above): no inline event
    handler, no dynamic code -- CSP is script-src 'self' and an inline
    handler is a violation and a hole. Pairs with the served-page pin: a
    pass while the feature is live is the point."""
    code = _glue_code()
    for needle in FORBIDDEN:
        assert needle not in code, f"{GLUE} grew {needle!r}: the Save is W5b.4c-2"
    assert not INLINE_HANDLER.search(code), "an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(code)
    assert "javascript:" not in code
    assert "textContent" in code, "the pane renders text through textContent only"
    # test_serve_static.py's parseability rule, applied to this module:
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
            assert stack.pop() == ch, "unbalanced bracket in the glue"
    assert not stack, f"unclosed {stack}"
    top = re.findall(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", code, re.MULTILINE)
    assert len(top) == len(set(top)), "duplicate top-level declaration"
