"""N5d-2: the editor shell's Navis panel gains Archive/Restore actions.

The panel is the read-only surface merged in N5d-1 (test_editor_navis_panel.py);
this slice wires its rows to the serve API that is already on main
(`GET /api/navis`, `POST /api/navis/archive` / `/api/navis/restore`, contract
in serve/navis_write.py) through the one shared api helper -- the same client
rules the preview panel adopted in N5c (test_navis_preview_actions.py): the
POST body carries the FULL key, an error's `payload.error` renders as
textContent-only into one `p.navis-error[role=alert]` at the top of the
panel, a non-200 re-enables the clicked button, and a 403 (`--no-write`)
disables every action button and keeps the message. The wording, the orphan
title, and the keyless rule match the preview panel.

The editor's panel differs from the preview's in two ways by design:
the rows are built here (navis-panel.js), so the data is in hand and each
button closes over its own row -- no positional DOM mapping; and success
does NOT reload the page (this is the SPA): a 200 re-fetches through the
module's own refresh() and the panel stays open. The message clears on the
next success and when the panel reopens.

No browser here: the REAL served module runs headless under node over the
same fake DOM as test_editor_navis_panel.py (plus insertBefore), with the
injected apiFn replacing the network. The real-browser pass ran on Chromium
and Firefox (in-prog-logs/navis-editor-actions.md).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "refdes", "serve", "static"
)

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120

HOSTILE = 'store exploded <img src=x onerror="steal()">'
NO_WRITE = (
    "this server was started with --no-write: navis archive and restore are disabled"
)

# rows: keyed active, keyless active, archived changed, archived orphan,
# and a keyless ARCHIVED row -- the API never emits one (archive needs a
# key), it pins the defensive rule that keyless rows get no button.
BASE_ROWS = [
    {
        "key": "aaaaaa11111", "key6": "aaaaaa", "text": "Active alpha reminder.",
        "item": "NOTE-001", "href": "note-001.html", "file": "items/note-a.md",
        "line": 5, "archived": False, "changed": False, "orphan": False,
    },
    {
        "key": "", "key6": "", "text": "Keyless marker.",
        "item": "NOTE-004", "href": "note-004.html", "file": "items/note-d.md",
        "line": 5, "archived": False, "changed": False, "orphan": False,
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
    {
        "key": "", "key6": "", "text": "Keyless archived marker.",
        "item": "NOTE-005", "href": "note-005.html", "file": "items/note-e.md",
        "line": 3, "archived": True, "changed": False, "orphan": False,
    },
]

# after alpha is archived on the server: one active row, alpha last.
AFTER_ROWS = BASE_ROWS[1:] + [dict(BASE_ROWS[0], archived=True, changed=False)]


def _payload(rows):
    return {
        "navis": rows,
        "counts": {
            "active": sum(1 for r in rows if not r["archived"]),
            "archived": sum(1 for r in rows if r["archived"]),
        },
    }


BASE_PAYLOAD = _payload(BASE_ROWS)
AFTER_PAYLOAD = _payload(AFTER_ROWS)

HARNESS = r"""
const STATIC = __STATIC__;
const PAYLOADS = __PAYLOADS__;
const HOSTILE = __HOSTILE__;
const NO_WRITE = __NO_WRITE__;
const url = (name) => `file://${STATIC}/${name}`;

// ---------- fake DOM: the shape test_editor_navis_panel.py uses, plus the
// insertBefore the error paragraph needs (real DOM has it; the harness
// models it so the module can prepend the alert above the rows).
class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this._text = '';
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
  insertBefore(n, ref) {
    const i = this.children.indexOf(ref);
    if (i < 0) this.children.push(n);
    else this.children.splice(i, 0, n);
    n._parent = this;
    return n;
  }
  remove() {
    const parent = this._parent;
    if (parent) parent.children = parent.children.filter((c) => c !== this);
  }
  removeChild(child) {
    this.children = this.children.filter((c) => c !== child);
    child._parent = null;
    return child;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  get firstChild() { return this.children[0] || null; }
  get parentNode() { return this._parent || null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
  click() { this.dispatch('click'); }
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
};
globalThis.window = new EventTarget();
// the SPA rule: the panel must NOT reload the page on success. Count every
// attempted reload; every scenario must leave it at 0.
const results = { reloads: 0 };
globalThis.location = { reload: () => { results.reloads += 1; } };

const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

const { mountNavisPanel } = await import(url('navis-panel.js'));

function stubApi(payload) {
  const state = { calls: [], payload, post: null };
  const apiFn = async (path, init = {}) => {
    const method = (init && init.method) || 'GET';
    state.calls.push({ path, method, body: init && init.body });
    if (method === 'POST') {
      if (state.post) return state.post(path, init);
      return { kind: 'ok', verb: 'archive', key: 'x', changed: true };
    }
    return structuredClone(state.payload);
  };
  return { apiFn, state };
}

const [BASE_PAYLOAD, AFTER_PAYLOAD] = PAYLOADS;

function openPanel(payload) {
  const root = new FakeNode('div');
  const { apiFn, state } = stubApi(payload);
  mountNavisPanel(root, apiFn);
  const toggle = find(root, 'navis-toggle');
  const panel = find(root, 'navis-panel');
  toggle.click(); // open: rows are in the DOM only after a draw
  return { root, toggle, panel, apiState: state };
}

const posts = (state) => state.calls.filter((c) => c.method === 'POST');
const gets = (state) => state.calls.filter((c) => c.method === 'GET');

// -- A: the wiring rules. Archive on keyed active rows (top list only),
// Restore on archived rows (orphan disabled + hint), nothing on keyless.
{
  const { toggle, panel } = openPanel(BASE_PAYLOAD);
  await flush();
  const lists = findAll(panel, 'navis-list');
  const topList = lists[0];
  const archives = findAll(panel, 'navis-archive');
  const restores = findAll(panel, 'navis-restore');
  const showAll = find(panel, 'navis-all');
  const keylessTop = topList.children.find(
    (li) => find(li, 'navis-text') && find(li, 'navis-text').textContent === 'Keyless marker.'
  );
  results.wired = {
    toggleLabel: toggle.textContent,
    archiveCount: archives.length,
    archiveLabels: archives.map((b) => b.getAttribute('aria-label')),
    archiveTexts: archives.map((b) => b.textContent),
    archivesInTopList: archives.every(
      (b) => topList.children.some((li) => li.children.includes(b))
    ),
    archivesInShowAll: findAll(showAll, 'navis-archive').length,
    keylessRowButtons: findAll(keylessTop, 'navis-archive').length,
    restoreCount: restores.length,
    restoreStates: restores.map((b) => ({
      disabled: b.disabled,
      title: b.getAttribute('title'),
      label: b.getAttribute('aria-label'),
    })),
  };
}

// -- B: Archive click posts the FULL key to the archive route; a 200
// re-fetches through refresh(), keeps the panel OPEN, and never reloads.
{
  const { toggle, panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    apiState.payload = AFTER_PAYLOAD; // the server rebuilt before answering
    return { kind: 'ok', verb: 'archive', key: 'aaaaaa11111', changed: true };
  };
  const btn = findAll(panel, 'navis-archive')[0];
  const getsBefore = gets(apiState).length;
  btn.click();
  const disabledDuring = btn.disabled;
  await flush();
  const lists = findAll(panel, 'navis-list');
  results.archive = {
    disabledDuring,
    posts: posts(apiState).map((c) => ({ path: c.path, body: c.body })),
    refetched: gets(apiState).length === getsBefore + 1,
    panelHidden: panel.hidden,
    toggleLabel: toggle.textContent,
    activeRows: lists[0].children.length,
  };
}

// -- C: Restore click posts the full key to the restore route.
{
  const { panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    apiState.payload = BASE_PAYLOAD;
    return { kind: 'ok', verb: 'restore', key: 'cccccc33333', changed: true };
  };
  const restore = findAll(panel, 'navis-restore')[0]; // gamma (not the orphan)
  restore.click();
  await flush();
  results.restore = {
    posts: posts(apiState).map((c) => ({ path: c.path, body: c.body })),
    panelHidden: panel.hidden,
  };
}

// -- D: a 500 re-enables the button and shows the payload's error, once,
// literal, at the top of the panel; a second failure does not stack it.
{
  const { panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    const err = new Error('store exploded');
    err.status = 500;
    err.payload = { kind: 'error', error: HOSTILE };
    throw err;
  };
  const btn = findAll(panel, 'navis-archive')[0];
  btn.click();
  await flush();
  const notices = findAll(panel, 'navis-error');
  results.failed = {
    disabledAfter: btn.disabled,
    noticeCount: notices.length,
    cls: notices[0] ? notices[0].className : null,
    role: notices[0] ? notices[0].getAttribute('role') : null,
    text: notices[0] ? notices[0].textContent : null,
    noticeChildren: notices[0] ? notices[0].children.length : null,
    atTop: notices[0] ? panel.children[0] === notices[0] : null,
    panelHidden: panel.hidden,
  };
  btn.click();
  await flush();
  results.failed.secondNotices = findAll(panel, 'navis-error').length;
}

// -- E: a 403 (--no-write) disables every action button, keeps the message.
{
  const { panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    const err = new Error('refused');
    err.status = 403;
    err.payload = { kind: 'refused', error: NO_WRITE };
    throw err;
  };
  const btn = findAll(panel, 'navis-archive')[0];
  btn.click();
  await flush();
  const actions = [...findAll(panel, 'navis-archive'), ...findAll(panel, 'navis-restore')];
  results.refused = {
    actionCount: actions.length,
    allDisabled: actions.every((b) => b.disabled === true),
    message: findAll(panel, 'navis-error')[0].textContent,
    panelHidden: panel.hidden,
  };
}

// -- F: the next success clears the message (and lands the new rows).
{
  const { toggle, panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    const err = new Error('store exploded');
    err.status = 500;
    err.payload = { kind: 'error', error: 'store exploded' };
    throw err;
  };
  const btn = findAll(panel, 'navis-archive')[0];
  btn.click();
  await flush();
  const sawError = findAll(panel, 'navis-error').length === 1;
  apiState.post = () => {
    apiState.payload = AFTER_PAYLOAD;
    return { kind: 'ok', verb: 'archive', key: 'aaaaaa11111', changed: true };
  };
  btn.click();
  await flush();
  results.cleared = {
    sawError,
    notices: findAll(panel, 'navis-error').length,
    toggleLabel: toggle.textContent,
    panelHidden: panel.hidden,
  };
}

// -- G: closing and reopening the panel clears the message.
{
  const { toggle, panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    const err = new Error('store exploded');
    err.status = 500;
    err.payload = { kind: 'error', error: 'store exploded' };
    throw err;
  };
  findAll(panel, 'navis-archive')[0].click();
  await flush();
  const sawError = findAll(panel, 'navis-error').length === 1;
  toggle.click(); // close
  toggle.click(); // open
  await flush();
  results.reopened = {
    sawError,
    notices: findAll(panel, 'navis-error').length,
    panelHidden: panel.hidden,
  };
}

// -- I: the race the browser makes real: a GET issued on open lands AFTER
// the 403 catch. The alert is the mount's, not one render's -- it must
// survive the redraw, and the redrawn buttons must come out disabled.
{
  const { toggle, panel, apiState } = openPanel(BASE_PAYLOAD);
  await flush();
  apiState.post = () => {
    const err = new Error('refused');
    err.status = 403;
    err.payload = { kind: 'refused', error: NO_WRITE };
    throw err;
  };
  findAll(panel, 'navis-archive')[0].click();
  await flush();
  const beforeRows = findAll(panel, 'navis-archive').length;
  apiState.payload = AFTER_PAYLOAD;
  window.dispatchEvent(new Event('refdes:rebuilt')); // late refresh redraws
  await flush();
  const actions = [...findAll(panel, 'navis-archive'), ...findAll(panel, 'navis-restore')];
  results.afterRedraw = {
    rowsRedrawn: findAll(panel, 'navis-archive').length === 0 && beforeRows === 1,
    notices: findAll(panel, 'navis-error').length,
    message: findAll(panel, 'navis-error')[0]?.textContent ?? null,
    atTop: findAll(panel, 'navis-error').length === 1
      && panel.children[0] === findAll(panel, 'navis-error')[0],
    actionCount: actions.length,
    allDisabled: actions.length > 0 && actions.every((b) => b.disabled === true),
    panelHidden: panel.hidden,
  };
}

// the SPA rule holds across every scenario above
results.reloadsTotal = results.reloads;

console.log(JSON.stringify(results));
"""


def _run_harness():
    script = (
        HARNESS.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
        .replace("__PAYLOADS__", json.dumps([BASE_PAYLOAD, AFTER_PAYLOAD]))
        .replace("__HOSTILE__", json.dumps(HOSTILE))
        .replace("__NO_WRITE__", json.dumps(NO_WRITE))
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


ORPHAN_TITLE = "Marker not found -- hand-restore the marker, then it re-links by key"


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_the_panel_actions_behaviour():
    r = _run_harness()

    # A. wiring: Archive on the keyed active row only, top list only; the
    # keyless row gets none; Restore enabled on the changed archived row,
    # the orphan disabled with the preview panel's exact hint.
    w = r["wired"]
    assert w["toggleLabel"] == "Navis (2)", w
    assert w["archiveCount"] == 1, w
    assert w["archiveLabels"] == ["Archive Navi aaaaaa"], w
    assert w["archiveTexts"] == ["Archive"], w
    assert w["archivesInTopList"] is True, w
    assert w["archivesInShowAll"] == 0, "Show-all repeats active rows: Archive lives in ONE place"
    assert w["keylessRowButtons"] == 0, w
    assert w["restoreCount"] == 2, "gamma + beta; the keyless archived row gets none"
    assert w["restoreStates"] == [
        {"disabled": False, "title": "Restore this Navi", "label": "Restore Navi cccccc"},
        {"disabled": True, "title": ORPHAN_TITLE, "label": "Restore Navi dddddd"},
    ], w

    # B. Archive: full key to the archive route; 200 -> refetch through the
    # module's own refresh(), panel stays open, rows re-render.
    a = r["archive"]
    assert a["disabledDuring"] is True, a
    assert a["posts"] == [{"path": "/api/navis/archive", "body": {"navi": "aaaaaa11111"}}], a
    assert a["refetched"] is True, a
    assert a["panelHidden"] is False, "the panel stays open (this is the SPA)"
    assert a["toggleLabel"] == "Navis (1)", a
    assert a["activeRows"] == 1, a

    # C. Restore: full key to the restore route.
    c = r["restore"]
    assert c["posts"] == [{"path": "/api/navis/restore", "body": {"navi": "cccccc33333"}}], c
    assert c["panelHidden"] is False, c

    # D. a 500: the clicked button re-enables; one inline alert at the top,
    # textContent-only (the hostile server text stays literal); panel open.
    d = r["failed"]
    assert d["disabledAfter"] is False, d
    assert d["noticeCount"] == 1, d
    assert d["cls"] == "navis-error", d
    assert d["role"] == "alert", d
    assert d["text"] == HOSTILE, d
    assert d["noticeChildren"] == 0, "the alert text is never parsed as markup"
    assert d["atTop"] is True, d
    assert d["panelHidden"] is False, d
    assert d["secondNotices"] == 1, "the alert is reused in place, never stacked"

    # E. 403: every action disabled, the message kept, panel open.
    e = r["refused"]
    assert e["actionCount"] == 3, e
    assert e["allDisabled"] is True, e
    assert e["message"] == NO_WRITE, e
    assert e["panelHidden"] is False, e

    # F. the next success clears the message.
    f = r["cleared"]
    assert f["sawError"] is True, f
    assert f["notices"] == 0, f
    assert f["toggleLabel"] == "Navis (1)", f

    # G. reopening clears the message.
    g = r["reopened"]
    assert g["sawError"] is True, g
    assert g["notices"] == 0, g
    assert g["panelHidden"] is False, g

    # I. a refresh landing AFTER the 403 catch (the browser-real race): the
    # redraw keeps the alert at the top and draws its buttons disabled.
    i = r["afterRedraw"]
    assert i["rowsRedrawn"] is True, i
    assert i["notices"] == 1, "the alert is the mount's, not one render's"
    assert i["message"] == NO_WRITE, i
    assert i["atTop"] is True, i
    assert i["actionCount"] >= 1, i
    assert i["allDisabled"] is True, "the lockout outlives the redraw"
    assert i["panelHidden"] is False, i

    # H. the SPA rule: no scenario reloaded the page.
    assert r["reloadsTotal"] == 0, "success re-fetches through refresh(); never a page reload"


def test_the_module_acts_over_the_serve_api_only():
    """The module talks POST to the two serve routes through the shared
    helper (the token lives in api.js), addresses rows by FULL key, and
    reloads nothing -- a hand-rolled fetch, an innerHTML, or a location
    reload in this file is exactly the regression this pins."""
    with open(os.path.join(STATIC, "navis-panel.js"), encoding="utf-8") as fh:
        panel = fh.read()
    assert "'/api/navis/archive'" in panel
    assert "'/api/navis/restore'" in panel
    assert "{ navi: key }" in panel, "the POST body carries the full key"
    for sink in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert sink not in panel
    assert "fetch(" not in panel
    assert "X-Refdes-Token" not in panel
    assert "location" not in panel, "the editor panel is the SPA: refresh(), never a reload"
