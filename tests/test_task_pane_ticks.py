"""Thread workbench W5b.3 contract: ticks in the pane, serve response only.

docs/design/thread-workbench-w5b-plan.md §4 W5b.3 (gates Q9/Q6/Q4, risks
R1/R3) and docs/design/thread-workbench.md §7a.6. The pane model grows one
flag (`interactive`), the row's checkbox markup rides behind it, and
`serve/server.py:_decorate` injects the write-capable module (the
`_reload_probe` pattern) into preview responses only — so every test here
pairs both sides of the seam: the generation on disk stays exactly what
`refdes build` writes (R3, Q9 ratified 2026-11-06 "confirmed, enforced by
test"), and the served response carries the ticks. The build-side half of
each pair is the §7a.6 guard in the plan's own words: a `refdes build` of a
project with a threaded log emits no checkbox, no tick module, no token and
no write route into the generation (`docs/design/browser-editor.md:1255`:
"`_site/` built without `serve` contains no editor UI, token, or write
route"), with the W5a read-only glyph and toggle still present.

Markup contract pinned here (names follow the pane's existing `data-refdes-*`
conventions — taskpane.js keys off `data-refdes-taskpane`, server.py off
`data-refdes-src`/`data-refdes-calc`): the row's checkbox is

    <input type="checkbox" id="refdes-taskpane-tick-<tip>-<task id>"
           data-refdes-task="<task id>"
           data-refdes-task-state="<state>"
           data-refdes-tick-states="<comma-separated legal target states>"
           data-refdes-tip="<tip ref>">

with a `<label for>` carrying the row's text, inside
`<label class="refdes-taskpane-tick">`, and the module is
`/edit/static/taskpane-ticks.js`, injected response-only.

Q6 (ratified (b)): open rows are enabled and unchecked with target set
`done,dropped`; done rows are checked and enabled with target set `open`;
dropped rows are unchecked and enabled with target set `open` — never a
direct done<->dropped transition. Q4 (ratified, confirmed): every checkbox
names the TIP its tick writes against (the note and data-refdes-tip name the
tip on an older entry's page; on a fork each panel's checkboxes name their
own tip). `--no-write` serve is pinned conservative: the plan is silent on
the pane under `--no-write`, and the server refuses every write ("continuations
are disabled", serve/api.py), so no interactive checkboxes and no module —
offering a control the server refuses is the UI lying.
"""

from __future__ import annotations

import os
import re

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import cli as cli_mod
from refdes import render as render_mod
from refdes import task_pane as task_pane_mod
from refdes.serve import server as server_mod
from refdes.serve.server import EditorApp

HOSTILE = 'Model <script>alert("a&b")</script> copper.'

# A thread with one tip and the full Q6 state vocabulary, hostile text in one
# row, and a derived row (REQ-001 addressed, never verified), plus a lone
# entry with no thread at all.
ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"
    "      - {id: T-drop-one, text: Skip the spare board., state: dropped}\n"
    "      - id: T-hostile\n"
    f"        text: '{HOSTILE}'\n"
    "        state: open\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "    addresses: REQ-001\n"
    "  - id: REQ-001\n"
    "    type: requirement\n"
    "    title: Idle current budget\n"
    "    status: active\n"
    "    body: The idle rail must stay under 10 uA.\n"
    "  - id: LOG-006\n"
    "    type: log\n"
    "    summary: A lone entry with no thread.\n"
    "    date: 2026-09-06\n"
)

# ONE_TIP plus one Navi, so a build writes both gated stylesheets.
WITH_NAVI = ONE_TIP + (
    "  - id: LOG-900\n"
    "    summary: Navi reminder.\n"
    "    date: 2026-09-07\n"
    "    body: >\n"
    "      Check the board.\n"
    "      <!--navi: reminder-->\n"
)

# A real fork: LOG-001's pane shows two tabs, each tip with its own list.
FORK = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal branch.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "  - id: LOG-003\n"
    "    summary: Decoupling branch.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
)

# Missing ids, a repeated id, and an id outside the safe DOM-id charset:
# every checkbox/label pair must be addressable and keep the authored text.
DUPES = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-same, text: First same., state: open}\n"
    "      - {id: T-same, text: Second same., state: done}\n"
    "      - {text: No id one., state: open}\n"
    "      - {text: No id two., state: dropped}\n"
    '      - id: T "quote" <x>\n'
    "        text: Weird id.\n"
    "        state: open\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
)

# A thread nobody ever gave a task list: no checkboxes, no module (Q6's
# tickable states are rows of a list; there is no list).
UNDECLARED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Head, no tasks.\n"
    "    date: 2026-08-01\n"
    "  - id: LOG-002\n"
    "    summary: Continuation, no tasks.\n"
    "    date: 2026-08-02\n"
    "    follows: LOG-001\n"
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_REFDES = os.path.join(REPO_ROOT, "src", "refdes")
STATIC_DIR = os.path.join(SRC_REFDES, "serve", "static")
TASKPANE_JS = os.path.join(SRC_REFDES, "templates", "taskpane", "taskpane.js")
TASKPANE_CSS = os.path.join(SRC_REFDES, "templates", "taskpane", "taskpane.css")
TICK_MODULE = "taskpane-ticks.js"
PREVIEW_CSS_START = "/* refdes:preview-css-start */"
PREVIEW_CSS_END = "/* refdes:preview-css-end */"
PREVIEW_CSS_BYTES_RE = re.compile(
    re.escape(PREVIEW_CSS_START.encode("utf-8"))
    + b".*?"
    + re.escape(PREVIEW_CSS_END.encode("utf-8")),
    re.DOTALL,
)

INPUT_TAG = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
DATA_ATTR = re.compile(r'data-refdes-([\w-]+)="([^"]*)"')
LABEL_TAG = re.compile(r'<label\b[^>]*\bfor="([^"]*)"[^>]*>(.*?)</label>', re.IGNORECASE | re.DOTALL)
INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""from\s+['"]([^'"]+\.js)['"]""")

# Whole-file needles belong to the generation as a whole. The checkbox
# needle is pane-scoped below: the site's own navigation already has a
# read-only `<input type="checkbox">` (the sidenav toggle), and W5b.3's rule
# is about the task pane's controls, not the whole site's checkbox budget.
FORBIDDEN_IN_TREE = (
    TICK_MODULE,
    "X-Refdes-Token",
    "refdes-token",
    "?token=",
    "/api/item/",
    "/continue",
)
FORBIDDEN_IN_PANE = ('type="checkbox"', *FORBIDDEN_IN_TREE)


def _write(tmp_path, items_yaml):
    return _write_config(tmp_path, items_yaml, "Task Pane Ticks")


def _write_config(tmp_path, items_yaml, title):
    config = (
        f"site: {{ title: {title}, out: _site }}\n"
        "standard: { base: hardware, version: 3 }\n"
    )
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_bytes(items_yaml.encode("utf-8"))
    return str(tmp_path / "refdes-project.yaml")


def _serve(tmp_path, items_yaml, read_only=False):
    config = _write(tmp_path, items_yaml)
    app = EditorApp(config, poll_interval=0.05, read_only=read_only)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


def _write_fork_serve(tmp_path):
    """FORK, warmed and de-chained: a writable load freezes each bare
    `follows:` to the target's current tip, which turns two siblings into a
    chain. The spelled-out frozen edge names the head's key, the way
    test_serve_preview_task_pane.py::LOG_FILE keeps a fork under serve."""
    config = _write(tmp_path, FORK)
    cli_mod.main(["-c", config, "check"])
    path = tmp_path / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    (head_key,) = re.findall(r"- key: (\S+)\n    id: LOG-001", text)
    blocks = re.split(r"(?=  - key: )", text)
    text = "".join(
        re.sub(
            r"follows: LOG-\d+@\S+",
            f"follows: LOG-001@{head_key}",
            block,
            count=1,
        )
        if re.match(r"  - key: \S+\n    id: LOG-003", block)
        else block
        for block in blocks
    )
    path.write_bytes(text.encode("utf-8"))
    return config


def _page_of(app, item_id: str) -> str:
    return app.state.snapshot.project.item_by_id(item_id).slug + ".html"


def _body(client, app, item_id: str) -> str:
    status, _h, body = client.page(f"/preview/{_page_of(app, item_id)}")
    assert status == 200
    return body.decode("utf-8")


def pane(html: str) -> str:
    """The pane's own markup, or "" when the page carries no pane (the
    `test_task_pane.py` extractor, same marker)."""
    start = html.find('<aside class="refdes-taskpane"')
    if start < 0:
        return ""
    return html[start : html.find("</aside>", start)]


def pane_slice(html: str) -> str:
    """The pane's control surface: toggle plus aside. A page without a pane
    has no control surface, and the site's own sidenav checkbox is outside
    this slice."""
    start = html.find('<button type="button" class="refdes-taskpane-toggle"')
    if start < 0:
        return ""
    end = html.find("</aside>", start)
    if end < 0:
        return html[start:]
    return html[start : end + len("</aside>")]


def _inputs(markup: str) -> list[dict]:
    """Every tick checkbox in `markup`, as {tag, attrs} dicts (a checkbox
    qualifies by carrying `data-refdes-task`, the pane's data-* namespace)."""
    boxes = []
    for tag in INPUT_TAG.findall(markup):
        if 'type="checkbox"' not in tag:
            continue
        attrs = dict(DATA_ATTR.findall(tag))
        if "task" in attrs:
            boxes.append({"tag": tag, "attrs": attrs})
    return boxes


def _tick_pairs(markup: str) -> list[tuple[str, str, str]]:
    """Tick checkboxes as (DOM id, authored data-refdes-task, label text)."""
    labels = dict(LABEL_TAG.findall(markup))
    pairs = []
    for box in _inputs(markup):
        dom_id = re.search(r'\bid="([^"]*)"', box["tag"]).group(1)
        pairs.append((dom_id, box["attrs"]["task"], labels.get(dom_id, "")))
    return pairs


def _box(markup: str, task_id: str) -> dict:
    for box in _inputs(markup):
        if box["attrs"]["task"] == task_id:
            return box
    raise AssertionError(f"no checkbox for task {task_id!r} in the pane")


def _walk_text(root: str):
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                yield os.path.relpath(path, root).replace("\\", "/"), fh.read().decode(
                    "utf-8", errors="replace"
                )


@pytest.fixture
def served(tmp_path_factory):
    yield from _serve(tmp_path_factory.mktemp("served"), ONE_TIP)


@pytest.fixture
def served_fork(tmp_path):
    config = _write_fork_serve(tmp_path)
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


@pytest.fixture
def served_dupes(tmp_path_factory):
    yield from _serve(tmp_path_factory.mktemp("dupes"), DUPES)


@pytest.fixture
def served_undeclared(tmp_path_factory):
    yield from _serve(tmp_path_factory.mktemp("undeclared"), UNDECLARED)


@pytest.fixture
def served_no_write(tmp_path_factory):
    yield from _serve(tmp_path_factory.mktemp("no-write"), ONE_TIP, read_only=True)


# ------------------------------- §7a.6 / Q9 / R3: the build stays plain,
# ----------------------------------- the serve response is the seam

def test_the_build_writes_no_ticks_and_the_serve_response_carries_them(tmp_path):
    """The plan's §7a.6-by-test sentence pinned as ONE pair (plan §4 W5b.3
    "Verified against", §5 R3): walk every byte of `refdes build` -- no
    checkbox, no tick module, no token string, no write route text, the W5a
    read-only glyph and toggle intact -- and see the SAME project under serve
    grow the checkboxes and the module in the HTTP response. The build half is
    green and the serve half is green: this is the feature W5b.3 ships."""
    config = _write(tmp_path, ONE_TIP)
    assert cli_mod.main(["-c", config, "build"]) == 0
    out = os.path.join(str(tmp_path), "_site")
    seen_html = False
    for rel, text in _walk_text(out):
        for needle in FORBIDDEN_IN_TREE:
            assert needle not in text, (rel, needle)
        if rel == "log-002.html":
            seen_html = True
            pane_html = pane(text)
            control_surface = pane_slice(text)
            for needle in FORBIDDEN_IN_PANE:
                assert needle not in control_surface, (rel, needle)
            assert "[ ]" in pane_html  # the read-only glyph, as text
            assert 'id="refdes-taskpane-toggle"' in text  # the read-only toggle
            assert "T-thermal-model" in pane_html
    assert seen_html, "the build wrote no item page: the walk proved nothing"

    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        client = Client(app)
        page = _body(client, app, "LOG-002")
        # the response side of the seam: checkboxes, and the module tag.
        assert [box["attrs"]["task"] for box in _inputs(pane(page))] == [
            "T-thermal-model",
            "T-input-range",
            "T-drop-one",
            "T-hostile",
        ]
        assert f'src="/edit/static/{TICK_MODULE}"' in page
        assert 'type="module"' in page
        # ...and the generation on disk stays the published bytes.
        on_disk = os.path.join(app.preview.current, "log-002.html")
        with open(on_disk, "rb") as fh:
            disk = fh.read().decode("utf-8")
        assert 'type="checkbox"' not in pane_slice(disk)
        assert TICK_MODULE not in disk
    finally:
        app.stop()


def test_the_built_stylesheets_strip_the_preview_block_the_response_carries(tmp_path):
    """R3's CSS half: the build's own gated stylesheets carry neither marker
    nor tick selector, `taskpane.css` is its source minus the marked block
    (computed independently here), and the writable preview response injects
    the same block beside the interactive pane."""
    config = _write(tmp_path, WITH_NAVI)
    assert cli_mod.main(["-c", config, "build"]) == 0
    assets = os.path.join(str(tmp_path), "_site", "assets")
    names = set(os.listdir(assets))
    assert {"taskpane.css", "navis.css"} <= names
    for name in sorted(name for name in names if name.endswith(".css")):
        with open(os.path.join(assets, name), encoding="utf-8") as fh:
            text = fh.read()
        assert PREVIEW_CSS_START not in text, name
        assert PREVIEW_CSS_END not in text, name
        assert ".refdes-taskpane-tick" not in text, name
    with open(os.path.join(assets, "taskpane.css"), "rb") as fh:
        built_css = fh.read()
    with open(TASKPANE_CSS, "rb") as fh:
        expected_css = PREVIEW_CSS_BYTES_RE.sub(b"", fh.read(), count=1)
    assert built_css == expected_css

    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        page = _body(Client(app), app, "LOG-002")
        style_start = page.index("<style>")
        style = page[style_start : page.index("</style>", style_start)]
        assert PREVIEW_CSS_START in style
        assert PREVIEW_CSS_END in style
        assert ".refdes-taskpane-tick" in style
    finally:
        app.stop()


def test_the_css_strip_is_a_byte_copy_outside_the_marked_block(tmp_path):
    """The byte-identity guard preserves bytes it is not asked to remove. A
    BOM and CRLF stylesheet, written as bytes, round-trips exactly around the
    marker block; a text-mode rewrite would have normalized it away."""
    source = tmp_path / "sample.css"
    data = (
        "\ufeff/* refdes-bom-css-test */\r\n"
        "/* refdes:preview-css-start */\r\n"
        ".refdes-taskpane-tick { color: red; }\r\n"
        "/* refdes:preview-css-end */\r\n"
        "/* after */\r\n"
    ).encode("utf-8")
    source.write_bytes(data)
    out = str(tmp_path / "out")
    render_mod._write_assets(out, set(), True, ("sample.css",), str(tmp_path))
    with open(os.path.join(out, "assets", "sample.css"), "rb") as fh:
        built = fh.read()
    assert built == PREVIEW_CSS_BYTES_RE.sub(b"", data, count=1)
    assert built.startswith(b"\xef\xbb\xbf")
    assert b"/* refdes-bom-css-test */\r\n" in built
    assert b"/* after */\r\n" in built
    assert b".refdes-taskpane-tick" not in built


def test_the_built_tree_ships_no_tick_module_while_serve_serves_it(tmp_path):
    """R3 at the file level, pinned as a pair: the build never ships
    taskpane-ticks.js (the site keeps taskpane.js, its show/hide/tab script),
    while serve's static route serves the packaged module."""
    config = _write(tmp_path, ONE_TIP)
    assert cli_mod.main(["-c", config, "build"]) == 0
    names = set(os.listdir(os.path.join(str(tmp_path), "_site", "assets")))
    assert TICK_MODULE not in names
    assert "taskpane.js" in names  # W5a's asset is still there

    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        status, headers, data = Client(app).page(f"/edit/static/{TICK_MODULE}")
        assert status == 200
        assert headers["content-type"].startswith("text/javascript")
        with open(os.path.join(STATIC_DIR, TICK_MODULE), "rb") as fh:
            assert data == fh.read()
    finally:
        app.stop()


def test_the_preview_pane_on_disk_equals_the_built_pane_while_the_response_differs(tmp_path):
    """The plan's W5b.3 byte-pair: "the same project under serve gets the
    checkboxes in the response while the file on disk in the preview
    generation is byte-identical to what build wrote" -- pane slice compared
    (the draft banner is a preview-page difference outside the pane)."""
    config = _write(tmp_path, ONE_TIP)
    assert cli_mod.main(["-c", config, "build"]) == 0
    with open(os.path.join(str(tmp_path), "_site", "log-002.html"), encoding="utf-8") as fh:
        built_pane = pane(fh.read())
    assert built_pane
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        on_disk = os.path.join(app.preview.current, "log-002.html")
        with open(on_disk, encoding="utf-8") as fh:
            disk_pane = pane(fh.read())
        assert disk_pane == built_pane  # R3: the disk half of the pair
        page = pane(_body(Client(app), app, "LOG-002"))
        assert page != disk_pane  # the response grew the ticks
        assert 'type="checkbox"' in page
    finally:
        app.stop()


# -------------------------------------------------- the checkbox's own shape

def test_the_checkbox_is_a_real_input_with_a_label_and_no_handler(served):
    """Plan §4 W5b.3: "a checkbox is a real <input> with a label and no
    inline handler" (the test_serve_static.py rules: CSP is script-src
    'self' -- an inline handler would be a violation and a hole). The label
    carries the row's text; the age-line fact of the row stays beside it."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    box = _box(body, "T-thermal-model")
    assert 'type="checkbox"' in box["tag"]
    assert not INLINE_HANDLER.search(box["tag"]), box["tag"]
    id_at = box["tag"].find('id="')
    assert id_at != -1, box["tag"]
    box_id = box["tag"][id_at + 4 : box["tag"].find('"', id_at + 4)]
    labels = dict(LABEL_TAG.findall(body))
    assert box_id in labels, f"no <label for={box_id!r}> in the pane"
    assert "Model worst-case copper temperature." in labels[box_id]
    # W5b.3 adds the control, it does not delete the pane's read facts:
    # the row's age line is still in the pane (W5a's CLI-parity line).
    assert "(open since LOG-001, 2026-08-30)" in body


# ---------------------------------------------------------------- Q6 states

def test_open_rows_are_tickable_to_done_and_dropped(served):
    """Q6 (ratified (b)): open -> done/dropped -- enabled, unchecked, the
    legal target set spelled in the markup for the later phase to obey."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    box = _box(body, "T-thermal-model")
    assert "disabled" not in box["tag"], box["tag"]
    assert "checked" not in box["tag"], box["tag"]
    assert box["attrs"]["task-state"] == "open"
    assert box["attrs"]["tick-states"] == "done,dropped"


def test_done_rows_un_tick_back_to_open_only(served):
    """Q6: a done row is checked and enabled (un-tick to open) -- and its
    target set names only `open`: never a direct done -> dropped."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    box = _box(body, "T-input-range")
    assert "checked" in box["tag"], box["tag"]
    assert "disabled" not in box["tag"], box["tag"]
    assert box["attrs"]["task-state"] == "done"
    assert box["attrs"]["tick-states"] == "open"


def test_dropped_rows_un_tick_back_to_open_only(served):
    """Q6: a dropped row is unchecked and enabled (un-tick to open) -- its
    target set names only `open`: never a direct dropped -> done."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    box = _box(body, "T-drop-one")
    assert "checked" not in box["tag"], box["tag"]
    assert "disabled" not in box["tag"], box["tag"]
    assert box["attrs"]["task-state"] == "dropped"
    assert box["attrs"]["tick-states"] == "open"


def test_every_checkbox_names_the_tip_its_tick_writes_against(served):
    """Plan §3: the client holds intent against ONE named tip, never a list.
    Every row's checkbox names the tip, so a tick can only ever mean "this
    task, this state, this tip" -- the W5b.4 save's request shape."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    boxes = _inputs(body)
    assert boxes, "no checkboxes at all"
    for box in boxes:
        assert box["attrs"]["tip"] == "LOG-002", box["tag"]


def test_task_ids_are_unique_and_safe_only_in_the_dom_pair(served_dupes):
    """Missing/repeated task ids are validation-legal, and the page must not
    ship two checkboxes under one DOM id (the second label would activate the
    first). The authored data-refdes-task value stays as authored; id/for are
    sanitized and unique within the pane."""
    app, client = served_dupes
    body = pane(_body(client, app, "LOG-002"))
    pairs = _tick_pairs(body)
    assert len(pairs) == 5
    ids = [dom_id for dom_id, _task, _label in pairs]
    assert len(ids) == len(set(ids)), ids
    assert all(dom_id.startswith("refdes-taskpane-tick-") for dom_id in ids), ids
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", dom_id) for dom_id in ids), ids
    assert sorted(task for _dom, task, _label in pairs) == [
        "",
        "",
        "T &#34;quote&#34; &lt;x&gt;",
        "T-same",
        "T-same",
    ]
    labels_by_id = {dom_id: label for dom_id, _task, label in pairs}
    assert set(labels_by_id) == set(re.findall(r'<label\b[^>]*\bfor="([^"]*)"', body))
    first = next(pair for pair in pairs if "First same." in pair[2])
    second = next(pair for pair in pairs if "Second same." in pair[2])
    weird = next(pair for pair in pairs if "Weird id." in pair[2])
    assert first[0] != second[0]
    assert weird[1] == "T &#34;quote&#34; &lt;x&gt;"


# ------------------------------------------------------------------- Q4

def test_an_older_entry_shows_the_tips_checkboxes(served):
    """Q4 (ratified, confirmed): the operation names the tip; an older
    entry's page shows the TIP's list -- the note, and every data-refdes-tip,
    name the tip, never the entry being viewed. (W5b.1 continues the tip;
    the checkboxes must belong to the same list the save will copy.)"""
    app, client = served
    body = pane(_body(client, app, "LOG-001"))
    assert "viewing LOG-001 · tasks as of tip LOG-002" in body
    boxes = _inputs(body)
    assert [box["attrs"]["task"] for box in boxes] == [
        "T-thermal-model",
        "T-input-range",
        "T-drop-one",
        "T-hostile",
    ]
    for box in boxes:
        assert box["attrs"]["tip"] == "LOG-002", box["tag"]


def test_a_forks_panels_belong_to_their_own_tips(served_fork):
    """§7a 3 with Q4: each tab's checkboxes name that tab's tip -- the draft
    is keyed by tip (Q5 (a)), so the markup must not blur the panels. The
    head's own list is the LOG-002 branch's (inherited), not the page's."""
    app, client = served_fork
    body = pane(_body(client, app, "LOG-001"))
    first = _box(body, "T-thermal-model")
    second = _box(body, "T-decoupling")
    assert first["attrs"]["tip"] == "LOG-002", first["tag"]
    assert second["attrs"]["tip"] == "LOG-003", second["tag"]


# ---------------------------------------------- derived rows stay inert (§4)

def test_derived_rows_get_no_glyph_and_no_control_while_authored_rows_get_them(served):
    """§7a 4 with W5b.3 ("no control on derived rows"): the derived section
    keeps its label and rows, stays glyph-free, and grows no checkbox --
    while the authored list on the same pane DOES carry the checkboxes."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    assert "REQ-001  unverified" in body  # the derived row is present
    derived = body[body.find("<details") :]
    assert derived  # the section exists (addresses REQ-001, unverified)
    assert "<input" not in derived
    assert "[ ]" not in derived and "[x]" not in derived and "[-]" not in derived
    assert _inputs(body), "authored rows must carry the checkboxes the derived rows never get"


# ------------------------------------------- no thread / no list: no controls

def test_a_page_without_a_thread_grows_no_controls_while_the_threaded_page_does(served):
    app, client = served
    page = _body(client, app, "LOG-006")
    assert pane(page) == ""  # absent, not empty (W5a rule)
    assert TICK_MODULE not in page
    # the seam is per-page, not global: the threaded page in the same server
    # carries the control (the guard is load-bearing, not a dead path).
    threaded = _body(client, app, "LOG-002")
    assert _inputs(pane(threaded))
    assert TICK_MODULE in threaded


def test_a_thread_with_no_declared_list_grows_no_controls(served_undeclared, served):
    """The pane shows the undeclared posture (W5a); there is no list to tick,
    so no checkbox and no write-capable module -- while a threaded project on
    a server in the same test run carries them, so absence here is the feature
    (an empty checkbox row would invite a tick that names a list the fold
    refused)."""
    app, client = served_undeclared
    page = _body(client, app, "LOG-002")
    body = pane(page)
    assert body  # the pane is there, posture and all
    assert "<input" not in body
    assert TICK_MODULE not in page

    control_app, control_client = served
    control = _body(control_client, control_app, "LOG-002")
    assert _inputs(pane(control))
    assert TICK_MODULE in control


def test_a_state_outside_the_q6_target_table_gets_the_glyph_row_with_no_control():
    """Q6 gives open/done/dropped a tick. A row with any other state remains
    a read-only glyph row even when the pane model is interactive."""
    block = task_pane_mod._task_block(
        {
            "state": "declared",
            "rows": [{"id": "T-closed", "text": "Closed.", "state": "closed"}],
        },
        "LOG-002",
        True,
    )
    assert block["rows"][0]["tick"] is None
    html = render_mod.render_taskpane_fragment(
        {
            "ref": "LOG-002",
            "forked": False,
            "tabs": [
                {
                    "tip": "LOG-002",
                    "date": None,
                    "summary": None,
                    "heading": "Tasks at tip:",
                    "note": None,
                    "verdict": None,
                    "tasks": block,
                }
            ],
            "derived": [],
            "derived_heading": "Derived",
        }
    )
    assert task_pane_mod.threads_mod.TASK_GLYPH_UNKNOWN in html
    assert "<input" not in html


# ------------------------------------------------------------ escaped text

def test_hostile_task_text_is_escaped_in_the_checkbox_markup(served):
    """The task text is authored YAML; the response escapes it in the
    checkbox's label markup like everywhere else (no live <script>, quotes
    and ampersands entity-ed) -- and the row it labels exists, so the
    escaping is proven on the tick markup, not on an absent row."""
    app, client = served
    body = pane(_body(client, app, "LOG-002"))
    box = _box(body, "T-hostile")  # the row carries the hostile task text
    id_at = box["tag"].find('id="')
    box_id = box["tag"][id_at + 4 : box["tag"].find('"', id_at + 4)]
    labels = dict(LABEL_TAG.findall(body))
    label = labels[box_id]
    assert "<script>alert" not in label
    assert "&lt;script&gt;" in label
    assert "a&amp;b" in label


# --------------------------------------------------------- the module's rules

def test_the_tick_module_is_a_packaged_static_module():
    """A new static module in the serve static dir (plan W5b.3 "Files"):
    plain ES module, packaged, same-origin, next to the modules the shell's
    import-graph rules cover -- it must exist and every module it imports
    must exist (a typo'd import is a blank page nothing else notices)."""
    path = os.path.join(STATIC_DIR, TICK_MODULE)
    assert os.path.isfile(path), f"{TICK_MODULE} must be a packaged static module"
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for target in JS_IMPORT.findall(text):
        target = target.removeprefix("./")
        assert os.path.isfile(os.path.join(STATIC_DIR, target)), (
            f"{TICK_MODULE} imports a module that does not exist: {target}"
        )


def test_the_tick_module_follows_the_served_js_rules():
    """The same text checks tests/test_serve_static.py runs over every served
    module (no inline handlers, no eval/new Function, no javascript: URL),
    plus this module's own rules: it renders through the DOM (textContent),
    it does not paste markup (innerHTML), and it never assembles a task list
    (R1: "the pane computing the new list client-side would be a second
    authority over the fold" -- a patch that builds a list in JS is a bug
    report, so the module must not carry the list's YAML spelling)."""
    path = os.path.join(STATIC_DIR, TICK_MODULE)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert not INLINE_HANDLER.search(text)
    assert not DYNAMIC_CODE.search(text)
    assert "javascript:" not in text
    assert "innerHTML" not in text
    assert "textContent" in text
    assert "tasks:" not in text
    for needle in ("fetch(", "XMLHttpRequest", "X-Refdes-Token", "/api/"):
        assert needle not in text, f"{TICK_MODULE} grew {needle!r}: it is W5b.3 chrome"


def test_taskpane_js_stays_a_show_hide_tab_script(served):
    """W5b.3: "taskpane.js stays a show/hide/tab script" -- the site's script
    gains no fetch, no token, no write surface from this phase (it ships
    inside _site/, and the site stays read-only per Q9). The served page
    proves the phase is live, so a pass means taskpane.js stayed clean WHILE
    the ticks shipped -- not because the feature never came."""
    _app, client = served
    page = _body(client, _app, "LOG-002")
    assert _inputs(pane(page)), "the ticks did not ship: a clean taskpane.js proves nothing"
    with open(TASKPANE_JS, encoding="utf-8") as fh:
        text = fh.read()
    for needle in ("fetch(", "XMLHttpRequest", "X-Refdes-Token", "/api/"):
        assert needle not in text, f"taskpane.js grew {needle!r}: it is a show/hide/tab script"


# --------------------------------------------------------------- css, the pane's

def test_the_pane_css_styles_the_tick():
    """W5b.3's css lands in templates/taskpane/taskpane.css (the pane styles
    its own list -- K4's rule). The match must be the tick's own selector,
    not one merely naming it as a descendant or a `-note` class; comments are
    stripped first (the round-4 C4 lesson)."""
    with open(TASKPANE_CSS, encoding="utf-8") as fh:
        css = re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.DOTALL)
    rule = re.search(r"(?m)^[ \t]*\.refdes-taskpane-tick[ \t]*\{([^}]*)\}", css)
    assert rule, "taskpane.css has no .refdes-taskpane-tick rule"
    negative = (
        ".refdes-taskpane-row:has(.refdes-taskpane-tick) input { width: auto; }\n"
        ".refdes-taskpane-tick-note { color: red; }\n"
    )
    assert not re.search(r"(?m)^[ \t]*\.refdes-taskpane-tick[ \t]*\{([^}]*)\}", negative)


def test_the_tick_head_insertion_uses_the_original_head_end(tmp_path):
    """`str.lower()` is not length-preserving for U+0130. The insertion point
    is the last `</head>` in the original response, not an offset borrowed
    from a lowercased copy."""
    config = _write_config(tmp_path, ONE_TIP, "İstanbul work list")
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        with open(os.path.join(app.preview.current, "log-002.html"), encoding="utf-8") as fh:
            page = fh.read()
        title = re.search(r"<title>.*?</title>", page, re.DOTALL)
        assert title is not None
        assert "İ" in title.group(0)
        project = app.state.snapshot.project
        item = project.item_by_id("LOG-002")
        decorated = server_mod._decorate_task_ticks(
            page, project, item, app.state.snapshot.hashes
        )
        extra = (
            "<style>"
            + render_mod.preview_taskpane_css()
            + "</style>"
            + f'<script type="module" src="/edit/static/{TICK_MODULE}"></script>'
        )
        at = decorated.index(extra)
        tail = decorated[at + len(extra) : at + len(extra) + len("</head>")]
        assert tail == "</head>"
    finally:
        app.stop()


# ------------------------------------------------------------ --no-write (Q9)

def test_a_no_write_server_offers_no_tick_controls(served_no_write, tmp_path_factory):
    """--no-write, pinned conservative: the plan is silent on the pane under
    --no-write, and the server refuses every write ("--no-write: continuations
    are disabled", serve/api.py), so no interactive checkboxes and no module --
    offering a control the server refuses is the UI lying. The read-only pane
    stays exactly as W5a shipped it (Q9: glyph, toggle, pane present). The
    pair: a writable server on the same fixture DOES ship the controls, so
    the refusal is the --no-write flag, not a dead code path."""
    app, client = served_no_write
    page = _body(client, app, "LOG-002")
    body = pane(page)
    assert body  # the pane is there (Q9: the site's pane, read-only)
    assert "[ ]" in body  # the read-only glyph
    assert "<input" not in body
    assert TICK_MODULE not in page

    twin = _write(tmp_path_factory.mktemp("ticks-writable"), ONE_TIP)
    writable = EditorApp(twin, poll_interval=0.05)
    writable.start()
    try:
        twin_page = _body(Client(writable), writable, "LOG-002")
        assert _inputs(pane(twin_page))
        assert TICK_MODULE in twin_page
    finally:
        writable.stop()
