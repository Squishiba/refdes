"""The editor shell's read-only Navis panel (design §11, slice N5d-1).

The contract: app.js mounts `navis-panel.js`'s `mountNavisPanel(root, apiFn)`
once; the module fetches `GET /api/navis` through the shared api helper,
shows a fixed `Navis (N)` toggle (N = counts.active, aria-expanded) at the
top-right of the viewport, and a panel of the ACTIVE rows -- key6, the source
item's id linked to its editor route (`#/items/<ID>`, no link when the row
has no item), the text -- plus a `Show all (N)` <details> listing every row
like the site panel: archived rows tagged `[archived]` showing the snapshot
text the API returns, orphan rows labelled `marker not found (<file>)`,
changed rows noting `marker text has changed since archived`. No actions.
An empty project is `Navis (0)` + `No active Navis.`

Refresh rides the editor's ONE project-change signal (no second poller):
app.js's poller dispatches `refdes:rebuilt` when the served serial moves,
and a successful save lands in the same signal on the next poll -- so a
rebuild re-labels the toggle, re-renders an open panel, and re-fetches; the
panel also re-fetches every time it opens. A failed fetch keeps the last
good rows; with none, the open panel says `Navis unavailable`.

Safety: the panel builds its DOM with createElement/textContent only --
marker text is untrusted, so the hostile row must come back literal.

The behavioural half runs the REAL served module under node with the same
fake-DOM posture as test_editor_link_undo.py (the injected apiFn replaces
the network; window is an EventTarget so the harness can fire
`refdes:rebuilt` and the Escape keydown the way the shell does). The
served-file half is the real EditorApp: the module is fetched over HTTP
with the JS content type, and app.js references it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest
from serve_support import Client
from test_navis_site_panel import _navi_project

from refdes.serve.server import EditorApp

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "refdes", "serve", "static"
)

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120

HOSTILE = 'Dirty <script>alert("x")</script> & "quoted" bit'

# The rows as GET /api/navis returns them (test_serve_navis_read.py shape):
# active first (one linked, one item-null hostile), archived changed, archived
# orphan. Text and flags are the row fields; the panel must render exactly
# these, in this shape.
BASE_PAYLOAD = {
    "navis": [
        {
            "key": "aaaaaa11111", "key6": "aaaaaa", "text": "Active alpha reminder.",
            "item": "NOTE-001", "href": "note-001.html", "file": "items/note-a.md",
            "line": 5, "archived": False, "changed": False, "orphan": False,
        },
        {
            "key": "bbbbbb22222", "key6": "bbbbbb", "text": HOSTILE,
            "item": None, "href": None, "file": "items/note-x.md",
            "line": 7, "archived": False, "changed": False, "orphan": False,
        },
        {
            "key": "cccccc33333", "key6": "cccccc", "text": "Gamma before the edit",
            "item": "NOTE-003", "href": "note-003.html", "file": "items/note-c.md",
            "line": 5, "archived": True, "changed": True, "orphan": False,
        },
        {
            "key": "dddddd44444", "key6": "dddddd", "text": "Beta archived then deleted",
            "item": "NOTE-002", "href": "note-002.html", "file": "items/note-b.md",
            "line": 0, "archived": True, "changed": False, "orphan": True,
        },
    ],
    "counts": {"active": 2, "archived": 2},
}

# after an archive on disk: alpha moved to archived, so one active row left.
NEXT_PAYLOAD = {
    "navis": [BASE_PAYLOAD["navis"][1]] + BASE_PAYLOAD["navis"][2:] + [
        {
            "key": "aaaaaa11111", "key6": "aaaaaa", "text": "Active alpha reminder.",
            "item": "NOTE-001", "href": "note-001.html", "file": "items/note-a.md",
            "line": 5, "archived": True, "changed": False, "orphan": False,
        }
    ],
    "counts": {"active": 1, "archived": 3},
}

EMPTY_PAYLOAD = {"navis": [], "counts": {"active": 0, "archived": 0}}


HARNESS = r"""
const STATIC = __STATIC__;
const PAYLOADS = __PAYLOADS__;
const url = (name) => `file://${STATIC}/${name}`;

// ---------- fake DOM (the shape test_editor_link_undo.py uses)
class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this._text = '';
    this.value = '';
    this.dataset = {};
    this.disabled = false;
    this.hidden = false;
  }
  set className(v) { this._cls = v; }
  get className() { return this._cls || ''; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this.children.length
      ? this.children.map((c) => c.textContent).join('')
      : this._text;
  }
  appendChild(child) { child._parent = this; this.children.push(child); return child; }
  remove() {
    const parent = this._parent;
    if (parent) parent.children = parent.children.filter((c) => c !== this);
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name]; }
  get firstChild() { return this.children[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  dispatch(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
  click() { this.dispatch('click'); }
  focus() { globalThis.document.activeElement = this; }
  querySelectorAll() { return []; }
}

function hasCls(node, cls) {
  const tokens = (node.className || '').split(/\s+/);
  return cls.split(/\s+/).every((c) => tokens.includes(c));
}

function findAll(node, cls) {
  const out = [];
  if (node && hasCls(node, cls)) out.push(node);
  if (!node) return out;
  for (const child of node.children) out.push(...findAll(child, cls));
  return out;
}

function find(node, cls) { return findAll(node, cls)[0] || null; }

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector: (sel) => (sel.includes('refdes-token') ? { content: 'tok' } : null),
  activeElement: null,
};
// the shell's signal surface: navis-panel listens for `refdes:rebuilt` and
// for Escape; the harness fires both the way app.js/the browser do.
globalThis.window = new EventTarget();

const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

const { mountNavisPanel } = await import(url('navis-panel.js'));

function stubApi(payload, mode = 'ok') {
  const state = { calls: [], mode, payload };
  const apiFn = async (path) => {
    state.calls.push(path);
    if (state.mode === 'fail') throw new Error('serve went away');
    return structuredClone(state.payload);
  };
  return { apiFn, state };
}

function mount(payload, mode = 'ok') {
  const root = new FakeNode('div');
  const { apiFn, state } = stubApi(payload, mode);
  mountNavisPanel(root, apiFn);
  const toggle = find(root, 'navis-toggle');
  const panel = find(root, 'navis-panel');
  return { root, toggle, panel, apiState: state };
}

const [BASE_PAYLOAD, NEXT_PAYLOAD, EMPTY_PAYLOAD] = PAYLOADS;

const results = {};

// -- A: the rows scenario. Count, open/close, row content, links, hostile
// text, Escape+focus, refresh-on-open, refresh-on-rebuild, fetch failure.
{
  const { toggle, panel, apiState } = mount(BASE_PAYLOAD);
  await flush();
  results.toggleLabel = toggle.textContent;
  results.collapsedAria = toggle.getAttribute('aria-expanded');
  results.hiddenBeforeOpen = panel.hidden;

  const callsBeforeOpen = apiState.calls.length;
  toggle.click(); // open: the panel must be visible and re-fetch
  await flush();
  results.openAria = toggle.getAttribute('aria-expanded');
  results.hiddenAfterOpen = panel.hidden;
  results.allPathsFetchApiNavis = apiState.calls.every((p) => p === '/api/navis');
  results.refetchedOnOpen = apiState.calls.length === callsBeforeOpen + 1;

  const lists = findAll(panel, 'navis-list');
  const activeRows = lists.length ? lists[0].children : [];
  results.activeRowCount = activeRows.length;
  const row0 = activeRows[0];
  results.row0Key6 = find(row0, 'navis-key') ? find(row0, 'navis-key').textContent : null;
  const link0 = find(row0, 'navis-item');
  results.row0LinkText = link0 ? link0.textContent : null;
  // real <a> nodes carry href as a property (like item.js's link.href = ...)
  results.row0LinkHref = link0 ? (link0.href ?? link0.attrs.href ?? null) : null;
  results.row1HasLink = find(activeRows[1], 'navis-item') !== null;
  results.row0Text = find(row0, 'navis-text').textContent;

  // hostile text: literal, and it built NO element -- a <script> child
  // means the module parsed the text as markup.
  const hostileSpan = find(activeRows[1], 'navis-text');
  results.hostileLiteral = hostileSpan.textContent;
  results.hostileHasChildren = hostileSpan.children.length;
  results.scriptNodesInPanel = findAll(panel, 'navis-row').filter(
    (li) => li.children.some((c) => c.tagName === 'SCRIPT')
  ).length;

  // Show all: every row, site-panel labels, snapshot text for archived.
  const all = find(panel, 'navis-all');
  results.showAllPresent = all !== null;
  results.showAllSummary = all ? find(all, 'navis-all-summary').textContent : null;
  const allRows = all ? findAll(all, 'navis-list')[0].children : [];
  results.showAllRowCount = allRows.length;
  const archivedRow = allRows.find((li) => find(li, 'navis-tag'));
  results.archivedTag = archivedRow ? find(archivedRow, 'navis-tag').textContent : null;
  results.archivedRowText = archivedRow ? find(archivedRow, 'navis-text').textContent : null;
  const orphanRow = allRows.find((li) =>
    find(li, 'navis-note') && find(li, 'navis-note').textContent.startsWith('marker not found')
  );
  results.orphanNote = orphanRow ? find(orphanRow, 'navis-note').textContent : null;
  const changedRow = allRows.find((li) =>
    findAll(li, 'navis-note').some((n) => n.textContent.includes('changed'))
  );
  results.changedNote = changedRow
    ? findAll(changedRow, 'navis-note').find((n) => n.textContent.includes('changed')).textContent
    : null;

  // Escape: close and return focus to the toggle.
  document.activeElement = panel;
  const escape = new Event('keydown');
  escape.key = 'Escape';
  window.dispatchEvent(escape);
  results.hiddenAfterEscape = panel.hidden;
  results.ariaAfterEscape = toggle.getAttribute('aria-expanded');
  results.focusAfterEscape = document.activeElement === toggle;

  // second open/close by click; then the rebuild signal re-labels the
  // toggle, re-renders the open panel, and re-fetches.
  toggle.click(); // open
  await flush();
  toggle.click(); // close
  await flush();
  results.hiddenAfterSecondClick = panel.hidden;
  toggle.click(); // open (renders rows from last good data)
  await flush();
  apiState.payload = NEXT_PAYLOAD;
  window.dispatchEvent(new CustomEvent('refdes:rebuilt', { detail: {} }));
  await flush();
  results.toggleLabelAfterRebuild = toggle.textContent;
  results.panelActiveRowsAfterRebuild = findAll(panel, 'navis-list')[0].children.length;

  // a failed fetch: the last good rows survive; no error banner appears.
  apiState.mode = 'fail';
  window.dispatchEvent(new CustomEvent('refdes:rebuilt', { detail: {} }));
  await flush();
  results.toggleLabelAfterFailure = toggle.textContent;
  results.rowsSurviveFailure = panel.textContent.includes('Dirty <script>');
  results.failureMentionsUnavailable = panel.textContent.includes('unavailable');
}

// -- B: the empty project.
{
  const { toggle, panel } = mount(EMPTY_PAYLOAD);
  await flush();
  results.emptyToggle = toggle.textContent;
  toggle.click();
  await flush();
  results.emptyPanelText = panel.textContent;
  results.emptyHasShowAll = find(panel, 'navis-all') !== null;
}

// -- C: fetch fails from the start: no rows to keep -> the panel says so.
{
  const { toggle, panel } = mount(EMPTY_PAYLOAD, 'fail');
  await flush();
  results.failedToggleLabel = toggle.textContent;
  toggle.click();
  await flush();
  results.failedPanelText = panel.textContent;
}

console.log(JSON.stringify(results));
"""


def _run_harness(scenario_payloads):
    script = HARNESS.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/"))).replace(
        "__PAYLOADS__", json.dumps(scenario_payloads)
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_the_navis_panel_behaviour():
    r = _run_harness([BASE_PAYLOAD, NEXT_PAYLOAD, EMPTY_PAYLOAD])

    # toggle: the active count, aria-expanded, closed at mount
    assert r["toggleLabel"] == "Navis (2)"
    assert r["collapsedAria"] == "false"
    assert r["hiddenBeforeOpen"] is True

    # open: visible, aria-expanded true, and it fetched through the shared
    # api path shape (no hand-rolled fetch) -- and re-fetched on open
    assert r["openAria"] == "true"
    assert r["hiddenAfterOpen"] is False
    assert r["allPathsFetchApiNavis"] is True
    assert r["refetchedOnOpen"] is True

    # active rows: exactly the two non-archived rows, key6, text
    assert r["activeRowCount"] == 2
    assert r["row0Key6"] == "aaaaaa"
    assert r["row0Text"] == "Active alpha reminder."

    # the item row links to the item's editor route; the item-null row none
    assert r["row0LinkText"] == "NOTE-001"
    assert r["row0LinkHref"] == "#/items/NOTE-001"
    assert r["row1HasLink"] is False

    # hostile text is data: literal text, no markup built from it
    assert r["hostileLiteral"] == HOSTILE
    assert r["hostileHasChildren"] == 0
    assert r["scriptNodesInPanel"] == 0

    # Show all: every row, the archived tag with the snapshot text, the
    # orphan and changed notes, exactly like the site panel
    assert r["showAllPresent"] is True
    assert r["showAllSummary"] == "Show all (4)"
    assert r["showAllRowCount"] == 4
    assert r["archivedTag"] == "[archived]"
    assert r["archivedRowText"] == "Gamma before the edit"
    assert r["orphanNote"] == "marker not found (items/note-b.md)"
    assert r["changedNote"] == "marker text has changed since archived"

    # Escape closes the panel and returns focus to the toggle; click closes
    assert r["hiddenAfterEscape"] is True
    assert r["ariaAfterEscape"] == "false"
    assert r["focusAfterEscape"] is True
    assert r["hiddenAfterSecondClick"] is True

    # the rebuild signal: re-label from the fresh counts, re-render the
    # open panel (alpha left the active list)
    assert r["toggleLabelAfterRebuild"] == "Navis (1)"
    assert r["panelActiveRowsAfterRebuild"] == 1

    # a failed fetch: the last good rows stay, no error text spams the panel
    assert r["toggleLabelAfterFailure"] == "Navis (1)"
    assert r["rowsSurviveFailure"] is True
    assert r["failureMentionsUnavailable"] is False

    # empty project: Navis (0) and the empty line, no Show-all
    assert r["emptyToggle"] == "Navis (0)"
    assert r["emptyPanelText"] == "No active Navis."
    assert r["emptyHasShowAll"] is False

    # a fetch that never succeeded: the open panel says so, once
    assert r["failedToggleLabel"] == "Navis (0)"
    assert r["failedPanelText"] == "Navis unavailable"


# ----------------------------------------------------------------- served wiring


def test_the_panel_module_is_served_as_javascript(tmp_path):
    """The real EditorApp: the shell's new module reaches the browser over
    the static surface with the JS content type (the extension gate in
    server.py's `_static` is what decides that -- a new extension would
    404, and a blank panel with a 404 in the console is the failure this
    pins)."""
    config = _navi_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        client = Client(app)
        status, headers, body = client.page("/edit/static/navis-panel.js")
        assert status == 200, body
        assert headers["content-type"].startswith("text/javascript")
        assert b"export function mountNavisPanel" in body
    finally:
        app.stop()


def test_the_shell_mounts_the_panel():
    """app.js must import the module and mount it once with the shared api
    helper (the token lives in api.js; a panel that hand-rolls fetch is a
    403 panel)."""
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "from './navis-panel.js'" in app
    assert "mountNavisPanel(document.body, api)" in app
    assert app.count("mountNavisPanel") == 2  # import + the one mount


def test_the_panel_builds_dom_without_markup_apis():
    """createElement/textContent only: marker text is untrusted, so the
    module must never have a markup sink."""
    with open(os.path.join(STATIC, "navis-panel.js"), encoding="utf-8") as fh:
        panel = fh.read()
    for sink in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert sink not in panel
    # and it talks to the server through the shared helper, never its own fetch
    assert "from './api.js'" in panel
    assert "fetch(" not in panel
    assert "X-Refdes-Token" not in panel
