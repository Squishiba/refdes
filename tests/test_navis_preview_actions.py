"""N5c: the Navis panel on SERVED PREVIEW pages gains Archive/Restore actions.

The published panel (slice 4a, PR #407) is read-only by design. `refdes
serve` decorates its preview responses with `preview.js`; this slice adds
`navis-preview.js`, exported as `wireNavisPanel(doc, apiFn)` and called
from preview.js next to `wireValueToggles`. It talks only to the serve
API (N5a `GET /api/navis`, N5b `POST /api/navis/archive|restore`) through
the one `api()` helper, and it maps DOM rows to API rows POSITIONALLY --
the list markup carries only the 6-char key, so text is never a selector.

No browser here: the REAL served module runs headless under node over a
fake DOM (the posture of test_editor_refdes_buttons.py), covering the
wiring rules (Archive on active rows, Restore enabled on archived rows
except the orphan, keyless rows get nothing), the click contract (full key
in the POST body, 200 -> reload, non-200 -> inline textContent-only error
+ re-enable, 403 -> every action disabled), the stale-page guard (DOM/API
count mismatch aborts silently), the hostile-text rule (marker text is
never parsed as markup), and the fetch-failure rule (panel stays exactly
as published). The Python test at the bottom pins the delivery chain on a
real EditorApp: preview page -> preview.js -> navis-preview.js.
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
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "refdes",
    "serve",
    "static",
)

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120

# ---------------------------------------------------------------- node harness

HARNESS = r"""
const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;

// ---------- minimal fake DOM (the slice's own: class/id/tag selectors, tree,
// textContent, attributes, click listeners -- nothing the module needs is
// missing, nothing it does not need is modelled)
class FNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this._text = '';
    this.disabled = false;
    this.type = '';
  }
  set className(v) { this._cls = v; }
  get className() { return this._cls || ''; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this.children.length
      ? this.children.map((c) => c.textContent).join('')
      : this._text;
  }
  appendChild(c) { c._parent = this; this.children.push(c); return c; }
  insertBefore(n, ref) {
    const i = this.children.indexOf(ref);
    if (i < 0) this.children.push(n);
    else this.children.splice(i, 0, n);
    n._parent = this;
    return n;
  }
  get firstChild() { return this.children[0] || null; }
  get parentNode() { return this._parent || null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  getAttribute(n) { return this.attrs[n] === undefined ? null : this.attrs[n]; }
  removeAttribute(n) {
    delete this.attrs[n];
    if (n === 'disabled') this.disabled = false;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatchEvent(ev) {
    for (const fn of (this.listeners[ev.type] || []).slice()) fn(ev);
    return true;
  }
  click() { return this.dispatchEvent({ type: 'click' }); }
  querySelectorAll(sel) {
    const parts = sel.split(',').map((s) => s.trim()).filter(Boolean);
    const out = [];
    const walk = (n) => {
      for (const c of n.children) {
        if (parts.some((p) => matchOne(c, p))) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) {
    for (const part of sel.split(',')) {
      const found = this.querySelectorAll(part.trim());
      if (found.length) return found[0];
    }
    return null;
  }
}

function matchOne(n, sel) {
  const idm = sel.match(/^#([\w-]+)$/);
  if (idm) return n.attrs.id === idm[1];
  const bits = sel.split('.');
  const tag = bits.shift();
  if (tag && n.tagName !== tag.toUpperCase()) return false;
  const toks = (n.className || '').split(/\s+/);
  return bits.every((c) => toks.includes(c));
}

const root = new FNode('body');
globalThis.document = {
  createElement: (tag) => new FNode(tag),
  querySelector: (sel) =>
    sel.includes('refdes-token') ? { content: 'tok' } : root.querySelector(sel),
};
const results = { reload: 0 };
globalThis.location = { reload: () => { results.reload += 1; } };

const { wireNavisPanel } = await import(url('navis-preview.js'));

// ---------- the fixture data: API rows in projection order (active first),
// and the published panel markup that rides the page beside them.
function rowsFixture() {
  return [
    { key: 'aaaa1111aaaa', key6: 'aaaa11', text: 'Alpha active.', item: 'NOTE-001',
      href: 'note-001.html', file: 'items/note-a.md', line: 5,
      archived: false, changed: false, orphan: false },
    { key: '', key6: '', text: 'Keyless marker.', item: 'NOTE-004',
      href: 'note-004.html', file: 'items/note-d.md', line: 5,
      archived: false, changed: false, orphan: false },
    { key: 'bbbb2222bbbb', key6: 'bbbb22', text: 'Beta archived.', item: 'NOTE-002',
      href: 'note-002.html', file: 'items/note-b.md', line: 5,
      archived: true, changed: false, orphan: false },
    { key: 'cccc3333cccc', key6: 'cccc33', text: 'Gamma orphan.', item: 'NOTE-003',
      href: 'note-003.html', file: 'items/note-c.md', line: 5,
      archived: true, changed: false, orphan: true },
  ];
}

function makePanel(opts = {}) {
  const doc = {
    createElement: (tag) => new FNode(tag),
    querySelector: (sel) => root.querySelector(sel),
  };
  const panel = new FNode('details');
  panel.className = 'refdes-navis';
  const body = new FNode('div');
  body.className = 'refdes-navis-panel';
  panel.appendChild(body);

  const topUl = new FNode('ul');
  topUl.className = 'refdes-navis-list';
  const addTop = (text) => {
    const li = new FNode('li');
    li.appendChild(textNode(text));
    topUl.appendChild(li);
  };
  const topTexts = opts.topTexts || ['Alpha active.', 'Keyless marker.'];
  for (const t of topTexts) addTop(t);
  body.appendChild(topUl);

  const showAll = new FNode('details');
  showAll.className = 'refdes-navis-all';
  showAll.setAttribute('id', 'refdes-navis-all');
  const showUl = new FNode('ul');
  showUl.className = 'refdes-navis-list';
  const addShow = (row) => {
    const li = new FNode('li');
    li.appendChild(textNode(row.text));
    if (row.archived) {
      const restore = new FNode('button');
      restore.className = 'refdes-navis-restore';
      restore.disabled = true;
      restore.setAttribute('title', 'the published site is read-only');
      restore.textContent = 'Restore';
      li.appendChild(restore);
    }
    showUl.appendChild(li);
  };
  for (const row of (opts.showRows || rowsFixture())) addShow(row);
  showAll.appendChild(showUl);
  body.appendChild(showAll);

  root.children.length = 0;
  root.appendChild(panel);
  return { doc, panel };
}

function textNode(text) {
  const span = new FNode('span');
  span.textContent = text;
  return span;
}

function fakeApi(payload, post = null) {
  const calls = [];
  const fn = async (path, init = {}) => {
    calls.push({ path, init });
    if ((init.method || 'GET') === 'GET') return payload;
    if (post) return post(path, init);
    return { kind: 'ok', verb: 'archive', key: 'x', changed: true };
  };
  fn.calls = calls;
  return fn;
}

const tick = () => new Promise((r) => setTimeout(r, 0));

function apiPayload(rows) {
  return {
    navis: rows,
    counts: {
      active: rows.filter((r) => !r.archived).length,
      archived: rows.filter((r) => r.archived).length,
    },
  };
}

// ---------- scenario 1: the wiring rules
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel();
  await wireNavisPanel(doc, fakeApi(apiPayload(rows)));
  const archives = panel.querySelectorAll('.refdes-navis-archive');
  const restores = panel.querySelectorAll('.refdes-navis-restore');
  results.wired = {
    archiveCount: archives.length,
    archiveLabels: archives.map((b) => b.getAttribute('aria-label')),
    archiveTexts: archives.map((b) => b.textContent),
    archiveInTopList: archives.every((b) => !b.querySelectorAll('.none').length),
    restoreStates: restores.map((b) => ({
      disabled: b.disabled,
      title: b.getAttribute('title'),
    })),
  };
}

// ---------- scenario 2: Archive click posts the FULL key, 200 reloads
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel();
  const api = fakeApi(apiPayload(rows));
  await wireNavisPanel(doc, api);
  const btn = panel.querySelectorAll('.refdes-navis-archive')[0];
  const reload0 = results.reload;
  btn.click();
  const disabledDuring = btn.disabled;
  await tick();
  await tick();
  results.archive = {
    disabledDuring,
    calls: api.calls
      .filter((c) => (c.init.method || 'GET') === 'POST')
      .map((c) => ({ path: c.path, body: c.init.body })),
    reload: results.reload - reload0,
  };
}

// ---------- scenario 3: Restore click posts the full key to /restore
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel();
  const api = fakeApi(apiPayload(rows));
  await wireNavisPanel(doc, api);
  const restore = panel.querySelectorAll('.refdes-navis-restore')[0];
  restore.click();
  await tick();
  await tick();
  results.restore = {
    calls: api.calls
      .filter((c) => (c.init.method || 'GET') === 'POST')
      .map((c) => ({ path: c.path, body: c.init.body })),
  };
}

// ---------- scenario 4: a failed POST re-enables and shows the server text
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel();
  const api = fakeApi(apiPayload(rows), (path, init) => {
    const err = new Error('store exploded');
    err.status = 500;
    err.payload = { kind: 'error', error: 'store exploded' };
    throw err;
  });
  await wireNavisPanel(doc, api);
  const btn = panel.querySelectorAll('.refdes-navis-archive')[0];
  const reload0 = results.reload;
  btn.click();
  await tick();
  await tick();
  const errs = panel.querySelectorAll('.refdes-navis-error');
  results.failedPost = {
    disabledAfter: btn.disabled,
    errors: errs.map((p) => ({ role: p.getAttribute('role'), text: p.textContent })),
    reload: results.reload - reload0,
  };
  // a second failure updates the one paragraph in place, it does not stack
  btn.click();
  await tick();
  await tick();
  results.failedPost.second = panel.querySelectorAll('.refdes-navis-error').length;
}

// ---------- scenario 5: a 403 (--no-write) disables every action, keeps the message
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel();
  const api = fakeApi(apiPayload(rows), () => {
    const err = new Error('refused');
    err.status = 403;
    err.payload = {
      kind: 'refused',
      error: 'this server was started with --no-write: navis archive and restore are disabled',
    };
    throw err;
  });
  await wireNavisPanel(doc, api);
  const btn = panel.querySelectorAll('.refdes-navis-archive')[0];
  const reload0 = results.reload;
  btn.click();
  await tick();
  await tick();
  const actions = panel
    .querySelectorAll('.refdes-navis-archive, .refdes-navis-restore')
    .filter((b) => b.className.includes('refdes-navis-'));
  results.refused = {
    allDisabled: actions.every((b) => b.disabled === true),
    message: panel.querySelector('.refdes-navis-error').textContent,
    reload: results.reload - reload0,
  };
}

// ---------- scenario 6: a stale page (DOM/API counts disagree) aborts
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel({ topTexts: ['Alpha active.'] });
  await wireNavisPanel(doc, fakeApi(apiPayload(rows)));
  results.stale = {
    archives: panel.querySelectorAll('.refdes-navis-archive').length,
    restores: panel
      .querySelectorAll('.refdes-navis-restore')
      .map((b) => ({ disabled: b.disabled, title: b.getAttribute('title') })),
  };
}

// ---------- scenario 7: hostile marker text never becomes markup
{
  const rows = rowsFixture();
  rows[0].text = '<img src=x onerror="steal()"><b>bold</b>';
  const { doc, panel } = makePanel({
    topTexts: ['<img src=x onerror="steal()"><b>bold</b>', 'Keyless marker.'],
    showRows: rows,
  });
  await wireNavisPanel(doc, fakeApi(apiPayload(rows)));
  const img = root.querySelectorAll('img');
  const b = root.querySelectorAll('b');
  const labels = panel.querySelectorAll('.refdes-navis-archive').map((x) => x.getAttribute('aria-label'));
  results.hostile = {
    imgs: img.length,
    bolds: b.length,
    labels,
  };
}

// ---------- scenario 8: the GET fails -> the panel stays exactly as published
{
  const rows = rowsFixture();
  const { doc, panel } = makePanel();
  const api = async (path, init = {}) => {
    api.calls.push({ path, init });
    throw new Error('offline');
  };
  api.calls = [];
  await wireNavisPanel(doc, api);
  const restores = panel.querySelectorAll('.refdes-navis-restore');
  const reload0 = results.reload;
  results.fetchFail = {
    calls: api.calls.length,
    archives: panel.querySelectorAll('.refdes-navis-archive').length,
    restoresAllDisabled: restores.every((b) => b.disabled === true),
    errors: panel.querySelectorAll('.refdes-navis-error').length,
    reload: results.reload - reload0,
  };
}

// ---------- scenario 9: no panel -> the API is never asked
{
  root.children.length = 0;
  root.appendChild(new FNode('div'));
  const api = fakeApi(apiPayload(rowsFixture()));
  await wireNavisPanel({
    createElement: (t) => new FNode(t),
    querySelector: (sel) => root.querySelector(sel),
  }, api);
  results.noPanel = { calls: api.calls.length };
}

console.log(JSON.stringify(results));
"""


def _node_json(tmp_path, harness_source, timeout=NODE_TIMEOUT_S):
    script = harness_source.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
    harness = tmp_path / "navis-preview-node-harness.mjs"
    harness.write_text(script, encoding="utf-8")
    try:
        proc = subprocess.run(
            [NODE, str(harness)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "navis-preview node harness hung: "
            f"exit={exc.returncode}\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        )
    assert proc.returncode == 0, f"navis-preview node harness failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served preview module")
def test_the_preview_panel_wiring(tmp_path):
    r = _node_json(tmp_path, HARNESS)

    # 1. the wiring rules
    w = r["wired"]
    assert w["archiveCount"] == 1, w
    assert w["archiveLabels"] == ["Archive Navi aaaa11"], w
    assert w["archiveTexts"] == ["Archive"], w
    assert w["restoreStates"] == [
        {"disabled": False, "title": "Restore this Navi"},
        {"disabled": True, "title": "Marker not found -- hand-restore the marker, then it re-links by key"},
    ], w

    # 2. Archive: full key, archive route, reload on 200
    a = r["archive"]
    assert a["disabledDuring"] is True, a
    assert a["calls"] == [{"path": "/api/navis/archive", "body": {"navi": "aaaa1111aaaa"}}], a
    assert a["reload"] == 1, a

    # 3. Restore: full key, restore route
    assert r["restore"]["calls"] == [
        {"path": "/api/navis/restore", "body": {"navi": "bbbb2222bbbb"}}
    ], r["restore"]

    # 4. a failed POST: re-enabled, one inline alert, no reload
    f = r["failedPost"]
    assert f["disabledAfter"] is False, f
    assert f["errors"] == [{"role": "alert", "text": "store exploded"}], f
    assert f["reload"] == 0, f
    assert f["second"] == 1, "the alert is reused in place, never stacked"

    # 5. 403: every action disabled, the message kept
    x = r["refused"]
    assert x["allDisabled"] is True, x
    assert x["message"].startswith("this server was started with --no-write"), x
    assert x["reload"] == 0, x

    # 6. stale page (counts disagree): the published panel survives untouched
    s = r["stale"]
    assert s["archives"] == 0, s
    assert [d["disabled"] for d in s["restores"]] == [True, True], s
    assert all(d["title"] == "the published site is read-only" for d in s["restores"]), s

    # 7. hostile marker text stays literal
    assert r["hostile"]["imgs"] == 0, r["hostile"]
    assert r["hostile"]["bolds"] == 0, r["hostile"]
    assert r["hostile"]["labels"] == ["Archive Navi aaaa11"], r["hostile"]

    # 8. the GET fails: no error UI, restore stays disabled, no reload
    ff = r["fetchFail"]
    assert ff["calls"] == 1, ff
    assert ff["archives"] == 0, ff
    assert ff["restoresAllDisabled"] is True, ff
    assert ff["errors"] == 0, ff
    assert ff["reload"] == 0, ff

    # 9. no panel on the page: the API is never asked
    assert r["noPanel"]["calls"] == 0, r["noPanel"]


# ------------------------------------------------- delivery chain on a real server


def test_the_preview_page_ships_the_wiring_chain(tmp_path):
    """The module is decoration: the served page reaches it through the same
    injected chain that already carries the W1 poll -- page -> preview.js ->
    navis-preview.js -- and the module is served with the panel markup the
    page already carries. Nothing new is injected into the page."""
    config = _navi_project(tmp_path)
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        client = Client(app)
        status, _h, body = client.page("/preview/note-001.html")
        assert status == 200
        html = body.decode("utf-8")
        assert 'class="refdes-navis"' in html
        assert "/edit/static/preview.js" in html

        status, _h, preview = client.page("/edit/static/preview.js")
        assert status == 200
        text = preview.decode("utf-8")
        assert "navis-preview.js" in text
        assert "wireNavisPanel()" in text

        status, _h, module = client.page("/edit/static/navis-preview.js")
        assert status == 200
        assert "wireNavisPanel" in module.decode("utf-8")
    finally:
        app.stop()


# --------------------------------------------- entry-point wiring (review round 1, F1)

ENTRY_HARNESS = r"""
// The REAL preview.js entry point (not a function in isolation) runs against
// a minimal document: its top level must wire BOTH the W3 show-values toggle
// and the N5c Navis panel. Review round 1 of PR #420 caught a head whose top
// level called wireNavisPanel() in place of wireValueToggles() -- string
// tests on the function bodies could not see that; this harness runs the
// entry point, so it can.
const STATIC = __STATIC__;
const queries = [];
const toggle = {
  listeners: {},
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); },
  setAttribute() {},
  click() { for (const fn of this.listeners.click || []) fn({ type: 'click' }); },
};
let off = false;
globalThis.document = {
  querySelector(sel) {
    queries.push(sel);
    if (sel === 'meta[name="refdes-token"]') return { content: 'tok' };
    return null;
  },
  querySelectorAll(sel) {
    queries.push(sel);
    return sel === '.refdes-values-toggle' ? [toggle] : [];
  },
  documentElement: {
    classList: {
      toggle(cls) {
        if (cls === 'refdes-values-off') off = !off;
        return off;
      },
    },
  },
  createElement() {
    return { setAttribute() {}, getAttribute() { return null; } };
  },
};
globalThis.location = { reload() {} };
globalThis.fetch = async () => { throw new Error('no network in the harness'); };

await import(`file://${STATIC}/preview.js`);
const navisQueried = queries.includes('details.refdes-navis');
toggle.click();
const offAfterFirst = off;
toggle.click();
const offAfterSecond = off;
console.log(JSON.stringify({ navisQueried, offAfterFirst, offAfterSecond }));
process.exit(0);
"""


@pytest.mark.skipif(
    NODE is None, reason="no node on PATH to run the served preview entry point"
)
def test_the_preview_entry_point_wires_both_toggle_and_panel(tmp_path):
    """preview.js's top level wires the W3 show-values toggle AND the N5c
    panel. A head where wireNavisPanel() replaces wireValueToggles() leaves
    every served page's toggle dead (the button is injected, the function
    exists, no listener attaches); this test runs the entry point, so that
    replacement fails it."""
    r = _node_json(tmp_path, ENTRY_HARNESS)
    assert r == {"navisQueried": True, "offAfterFirst": True, "offAfterSecond": False}, r
