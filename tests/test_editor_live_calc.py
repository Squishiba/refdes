"""The live inline-calc layer in the browser editor, driven under node
(in-prog-logs/inline-calc-live-editor-design-20261020.md §3.1-§3.8, slice B).

Same posture as ``test_editor_link_undo.py`` / ``test_editor_draft_mirror.py``:
no browser, the REAL served modules under node -- the real ``editor.js``
wiring (which builds the real ``live-calc.js`` controller and binds it to the
body textarea through ``bodyControl``) over ``api.js``, ``drafts.js`` and
stubs for DOM/sessionStorage/localStorage/fetch/timers. The fetch stub
resolves each ``/calc`` call on demand, so a response lands exactly when the
scenario needs it (mid-typing, unfocused, with a foreign revision); the fake
timer queue pins the 400 ms debounce without real waiting.

Scenarios, one node process:

- client pre-gate (§3.1): a body with no calc marker costs no request (open
  flush included) and leaves the panel hidden.
- debounce: a keystroke schedules one request 400 ms later; a second
  keystroke resets it (§3.1); the request carries the textarea text and the
  draft's ``fields`` bag (§3.3).
- supersede: typing after a request fires discards the response silently --
  no panel update, no text change -- and the next debounce re-requests (§3.6).
- revision guard: a payload whose ``revision`` is not the form's own is
  discarded silently; the matching one applies (§3.6, never ``openRevision``).
- abort: the superseding request aborts the in-flight one (§3.6 guard 1).
- blur evaluates only: blur flushes the pending request; the response
  refreshes the panel and arms Fill, mutates no text, steals no focus (§3.1,
  §3.5 focus rule); refocus re-fires the flush and the fills apply (§3.6).
- caret skip is inclusive of both result-range boundaries (§3.5), and a
  NON-collapsed selection overlapping a result range is skipped like a caret
  inside it, while a selection clear of the range fills.
- line-relative columns convert to document offsets -- a span below line 0
  fills its own range, not line 0's (§3.3).
- last-to-first application keeps earlier ranges valid (§3.5).
- the caret shifts only by applied ranges that END before it (§3.5).
- Case B: insertText false -> the .value splice fills, the no-undo line
  shows, auto-fill self-disables, the splice schedules its own
  recalculation, Fill keeps working (§3.5).
- the Case B stand-down is SESSION-scoped (§3.5): a controller constructed
  after the first splice starts stood down -- no auto-fill, rows render,
  the session line shows, the checkbox reads OFF.
- the auto-fill toggle persists in localStorage and gates exactly the text
  mutation: OFF renders rows and Fill still works (§3.5, §6.1).
- an ok-within-window literal (``4.4 V`` vs computed ``4.436 V``) is never
  rewritten under auto-fill ON (§3.5's stale gate -- the D1 pin).
- a span missing one half of its result pair is display-only: no Fill, no
  mutation (the guards enforce the PAIR).
- no request while a save round-trip is in flight (§3.1), and the post-save
  form revision passes the guard.
- item-switch teardown drives the real ``renderItem`` (§3.8): the pending
  timer dies, the in-flight request is aborted, live-calc's textarea
  listeners go, no /calc fires for the switched-away item -- and the same
  on a SAME-handle re-render whose fetch fails (the clear the pre-fetch
  pass never runs).
- Fill is idempotent: a second click on an applied span mutates nothing (§3.5).
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

# One node spawn for all scenarios; generous for a cold process start on a
# shared runner (see the timeout note in test_vscode_extension.py for why
# 10 s is not one).
NODE_TIMEOUT_S = 120

# One definition of the fixture texts, used by the harness (injected below)
# and by the Python assertions -- a drift between them is a silent test lie.
T1 = "Rail `Vbad := 2 V * 2 = 5 V`"
T1_FILLED = "Rail `Vbad := 2 V * 2 = 4 V`"

# Astral fixtures: the server's span columns are Python string indices =
# Unicode code points; textarea offsets are UTF-16 code units. Every text
# here puts astral characters on the span's line BEFORE the span, so a raw
# column addition lands off by one unit per astral character.
A1 = "\U0001F600 `Vbad := 2 V * 2 = 5 V`"
A1_FILLED = "\U0001F600 `Vbad := 2 V * 2 = 4 V`"
E1 = "\U0001F600\u0301\U0001F600 `Vbad := 2 V * 2 = 5 V`"
E1_FILLED = "\U0001F600\u0301\U0001F600 `Vbad := 2 V * 2 = 4 V`"
F1 = "\U0001F600 heading\n`Vbad := 2 V * 2 = 5 V`"
F1_FILLED = "\U0001F600 heading\n`Vbad := 2 V * 2 = 4 V`"

# Astral fixtures: the server's span columns are Python string indices =
# Unicode code points; textarea offsets are UTF-16 code units. Every text
# here puts astral characters on the span's line BEFORE the span, so a raw
# column addition lands off by one unit per astral character.
A1 = "\U0001F600 `Vbad := 2 V * 2 = 5 V`"
A1_FILLED = "\U0001F600 `Vbad := 2 V * 2 = 4 V`"
E1 = "\U0001F600\u00E9\U0001F600 `Vbad := 2 V * 2 = 5 V`"
E1_FILLED = "\U0001F600\u00E9\U0001F600 `Vbad := 2 V * 2 = 4 V`"
F1 = "\U0001F600 heading\n`Vbad := 2 V * 2 = 5 V`"
F1_FILLED = "\U0001F600 heading\n`Vbad := 2 V * 2 = 4 V`"

HARNESS = r"""
const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;

// ---------- storage stubs
const sessionStore = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (sessionStore.has(k) ? sessionStore.get(k) : null),
  setItem: (k, v) => sessionStore.set(k, String(v)),
  removeItem: (k) => sessionStore.delete(k),
};
const localStore = new Map();
globalThis.localStorage = {
  getItem: (k) => (localStore.has(k) ? localStore.get(k) : null),
  setItem: (k, v) => localStore.set(k, String(v)),
  removeItem: (k) => localStore.delete(k),
};

// ---------- fake DOM
let focusCalls = 0;
let EXEC_FAILS = false;

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
    this.checked = false;
    this.type = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
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
  setAttribute(name, value) { this.attrs[name] = value; }
  get firstChild() { return this.children[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  dispatch(type) { for (const fn of this.listeners[type] || []) fn({}); }
  click() { this.dispatch('click'); }
  contains(node) {
    let p = node;
    while (p) { if (p === this) return true; p = p._parent; }
    return false;
  }
  querySelectorAll(sel) {
    // the two selector shapes the item view uses: `.class` and `[data-attr]`
    const match = (n) => {
      if (sel.startsWith('.')) return hasCls(n, sel.slice(1));
      if (sel.startsWith('[')) {
        const camel = sel.slice(1, -1).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        return n.dataset[camel] !== undefined;
      }
      return n.tagName === sel.toUpperCase();
    };
    const out = [];
    const walk = (n) => {
      for (const c of n.children) {
        if (match(c)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  setSelectionRange(s, e) { this.selectionStart = s; this.selectionEnd = e; }
  focus() { globalThis.document.activeElement = this; focusCalls += 1; }
  select() {}
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

const __byId = {};
globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  getElementById: (id) => (__byId[id] || (__byId[id] = new FakeNode('div'))),
  querySelector: (sel) => (sel.includes('refdes-token') ? { content: 'tok' } : null),
  activeElement: null,
  execCommand: (name, ui, text) => {
    if (name !== 'insertText' || EXEC_FAILS) return false;
    const a = globalThis.document.activeElement;
    if (!a || a.tagName !== 'TEXTAREA') return false;
    const s = Math.min(a.selectionStart, a.value.length);
    const e = Math.min(Math.max(a.selectionEnd, s), a.value.length);
    a.value = a.value.slice(0, s) + text + a.value.slice(e);
    a.selectionStart = a.selectionEnd = s + text.length;
    return true;
  },
};
globalThis.window = { addEventListener: () => {} };

// ---------- fake timers (the debounce is pinned, never real-waited)
let now = 0;
let timerSeq = 0;
const timers = new Map();
globalThis.setTimeout = (fn, ms) => {
  const id = ++timerSeq;
  timers.set(id, { at: now + ms, fn });
  return id;
};
globalThis.clearTimeout = (id) => { timers.delete(id); };

const flushMicro = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
async function advance(ms) {
  now += ms;
  for (;;) {
    const due = [...timers.entries()].filter(([, t]) => t.at <= now).sort((a, b) => a[1].at - b[1].at);
    if (!due.length) break;
    for (const [id, t] of due) {
      timers.delete(id);
      t.fn();
      await flushMicro();
    }
  }
  await flushMicro();
}

// ---------- fetch: /calc resolves on demand, /edit is scripted per scenario
const calcCalls = [];
// The serve answers GETs on parallel handler threads: a scenario that needs
// the interleaving of a watcher rebuild with the two boot fetches defers
// those handlers into this queue and runs them one at a time.
const __serverQueue = [];
// Serve threads are scheduled independently of request order: the scenario
// picks WHICH queued handler runs next (the adversarial interleaving), and
// each handler reads the build current at the moment it runs.
async function __flushPath(p) {
  const i = __serverQueue.findIndex((h) => h.__path.includes(p));
  if (i === -1) throw new Error(`no queued handler matching ${p}`);
  const [h] = __serverQueue.splice(i, 1);
  h();
  await flushMicro();
}
let editSettle = null;
globalThis.fetch = async (path, init) => {
  if (path.includes('/calc')) {
    const call = { path, body: JSON.parse(init.body), signal: init && init.signal, settle: null };
    call.promise = new Promise((resolve, reject) => { call.settle = { resolve, reject }; });
    if (call.signal) call.signal.addEventListener('abort', () => call.settle.reject(new Error('AbortError')));
    calcCalls.push(call);
    return call.promise;
  }
  if (path.includes('/edit')) {
    editPosts.push(init && init.body ? JSON.parse(init.body) : null);
    return new Promise((resolve) => { editSettle = (payload, ok) => resolve(
      { ok, status: ok ? 200 : 422, statusText: 'OK', json: async () => payload });
    });
  }
  if (path.startsWith('/api/revision')) {
    return new Promise((resolve) => {
      const h = () => resolve(
        { ok: true, status: 200, statusText: 'OK',
          json: async () => (globalThis.__revisionHook
            ? globalThis.__revisionHook()
            : { serial: 1, revision: 'rev-0', git: null }) });
      h.__path = path;
      __serverQueue.push(h);
    });
  }
  if (path.startsWith('/api/items')) {
    return { ok: true, status: 200, statusText: 'OK', json: async () => ({ items: [], facets: {} }) };
  }
  if (path.startsWith('/api/item/') && !path.includes('/calc') && !path.includes('/edit')) {
    if (globalThis.fetch.__failItem) throw new Error('network down');
    const h = decodeURIComponent(path.split('/api/item/')[1].split('?')[0]);
    if (globalThis.__itemViewHook) {
      return new Promise((resolve) => {
        const hh = () => resolve(
          { ok: true, status: 200, statusText: 'OK', json: async () => globalThis.__itemViewHook(h) });
        hh.__path = path;
        __serverQueue.push(hh);
      });
    }
    return { ok: true, status: 200, statusText: 'OK', json: async () => itemRender(h) };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) };
};
const editPosts = [];

const settleCalc = async (call, payload, ok = true, status = 200) => {
  call.settle.resolve({ ok, status, statusText: 'OK', json: async () => payload });
  await flushMicro();
};
const settleEdit = async (payload, ok = true) => {
  const settle = editSettle;
  editSettle = null;
  settle(payload, ok);
  await flushMicro();
};

const { createEditor } = await import(url('editor.js'));
const { createLiveCalc } = await import(url('live-calc.js'));
const { renderItem } = await import(url('item.js'));
const drafts = await import(url('drafts.js'));

function itemRender(handle) {
  return {
    id: handle, handle, title: 'Item.', type: 'decision',
    source_file: 'items/decisions.yaml', source_line: 3, page: `items/${handle}`,
    fields: {}, inherited_fields: [], body: T1,
    edit: { editable: true, file_revision: 'rev-0', fields: {}, body: { editable: true } },
    links: { outgoing: [], incoming: [] },
    coverage: null, checks: [], diagnostics: [],
  };
}

function editItem(handle) {
  return {
    id: handle,
    revision: 'rev-0',
    edit: { editable: true, file_revision: 'rev-0', fields: {}, body: { editable: true }, links: {} },
  };
}

// opening the editor runs bodyControl -> live-calc attach -> the open flush
// (design §3.1: an opened item with stale spans shows the panel immediately)
function openEditor(handle, body) {
  const editor = createEditor(editItem(handle), handle, () => {}, () => {});
  const area = editor.bodyControl(body, null);
  const calls = () => calcCalls.filter((c) => c.path.includes(encodeURIComponent(handle)));
  const panel = editor.liveCalcPanel;
  return {
    editor, area, panel, calls,
    rowCount: () => findAll(panel, 'live-calc-row').length,
    fills: () => findAll(panel, 'live-calc-fill'),
    type: (text) => { area.value = text; area.dispatch('input'); },
    focus: () => { globalThis.document.activeElement = area; area.dispatch('focus'); },
    blur: () => { globalThis.document.activeElement = null; area.dispatch('blur'); },
  };
}

// a stale span over the first occurrence of `stored` on `line` of `text`
function spanOn(text, stored, computed, name = 'Vbad', line = 0) {
  const col = text.split('\n')[line].indexOf(stored);
  return {
    line,
    start: 0, end: text.split('\n')[line].length,
    result_start: col, result_end: col + stored.length,
    name, status: 'stale', computed,
    message: `inline calc ${name}: stored result says ${stored}, now computes ${computed}`,
  };
}
const payload = (spans, revision = 'rev-0') => ({ revision, spans });

const results = {};
const T1 = __T1__;
const T1_FILLED = __T1_FILLED__;
const A1 = __A1__;
const A1_FILLED = __A1_FILLED__;
const E1 = __E1__;
const E1_FILLED = __E1_FILLED__;
const F1 = __F1__;
const F1_FILLED = __F1_FILLED__;

// The server's columns are PYTHON string indices = Unicode code points;
// textarea offsets are UTF-16 code units. The plain spanOn above is only
// honest for BMP text -- on astral lines it emits UTF-16 offsets, which is
// exactly the client bug this family tests, never the server's truth. This
// helper emits CODE-POINT columns, as the real server does.
function cpSpan(text, stored, computed, name = 'Vbad', line = 0) {
  const cps = Array.from(text.split('\n')[line]);
  const sp = Array.from(stored);
  let col = -1;
  for (let i = 0; i + sp.length <= cps.length; i++) {
    if (cps.slice(i, i + sp.length).join('') === stored) { col = i; break; }
  }
  return {
    line,
    start: 0, end: cps.length,
    result_start: col, result_end: col + sp.length,
    name, status: 'stale', computed,
    message: `inline calc ${name}: stored result says ${stored}, now computes ${computed}`,
  };
}

// -- astral text (emoji before the span on the SAME line): every consumer of
//    a server column -- Fill, auto-fill insertText, the Case B splice, the
//    caret-skip boundaries -- must convert code-point columns to UTF-16
//    offsets before touching the textarea
{
  const h = 'DEC-ASTRAL-FILL';
  const ed = openEditor(h, A1);
  await settleCalc(ed.calls()[0], payload([]));
  const box = find(ed.panel, 'live-calc-autofill');
  box.checked = false;
  box.dispatch('change');
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([cpSpan(A1, '5 V', '4 V')]));
  ed.fills()[0].click();
  results.astralFill = { whole: ed.area.value };
  globalThis.localStorage.removeItem('refdes.live-calc.autofill');
  drafts.clearDraft(h);
}
{
  const h = 'DEC-ASTRAL-AUTO';
  const ed = openEditor(h, A1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([cpSpan(A1, '5 V', '4 V')]));
  results.astralAutoFill = { whole: ed.area.value };
  drafts.clearDraft(h);
}
{
  const h = 'DEC-ASTRAL-CASEB';
  EXEC_FAILS = true;
  const ed = openEditor(h, A1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([cpSpan(A1, '5 V', '4 V')]));
  results.astralCaseB = { whole: ed.area.value };
  EXEC_FAILS = false;
  globalThis.sessionStorage.removeItem('refdes.live-calc.fallback');
  drafts.clearDraft(h);
}
{
  // emoji costs one EXTRA UTF-16 unit before the span: the true range is
  // 22..25, the raw code-point columns say 21..24. A caret just BEFORE the
  // true start (21) must fill; at a true boundary (22, 25) it must skip.
  const u = A1.indexOf('5 V');
  const cases = [];
  for (const [label, caret, expectFilled] of [
    ['just-before', u - 1, true],
    ['start-edge', u, false],
    ['end-edge', u + 3, false],
  ]) {
    const base = calcCalls.length;
    const h = 'DEC-ASTRAL-CARET';
    const ed = openEditor(h, A1);
    await settleCalc(calcCalls[base], payload([]));
    ed.area.setSelectionRange(caret, caret);
    ed.focus();
    await settleCalc(calcCalls[base + 1], payload([cpSpan(A1, '5 V', '4 V')]));
    cases.push({ label, expectFilled, filled: ed.area.value === A1_FILLED });
    ed.blur();
    ed.editor.liveCalcPanel._refdesLiveCalc.destroy();
    drafts.clearDraft(h);
  }
  results.astralCaret = {
    cases,
    pass: cases.every((c) => c.filled === c.expectFilled),
  };
}
{
  // two astral emoji with a BMP accent between them: only the emoji shift
  const h = 'DEC-ASTRAL-MIX';
  const ed = openEditor(h, E1);
  await settleCalc(ed.calls()[0], payload([]));
  const box = find(ed.panel, 'live-calc-autofill');
  box.checked = false;
  box.dispatch('change');
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([cpSpan(E1, '5 V', '4 V')]));
  ed.fills()[0].click();
  results.astralMix = { whole: ed.area.value };
  globalThis.localStorage.removeItem('refdes.live-calc.autofill');
  drafts.clearDraft(h);
}
{
  // the emoji is on line 0, the span on line 1: line starts are computed in
  // JS (UTF-16), so this must keep working -- a regression guard
  const h = 'DEC-ASTRAL-NL';
  const ed = openEditor(h, F1);
  await settleCalc(ed.calls()[0], payload([]));
  const box = find(ed.panel, 'live-calc-autofill');
  box.checked = false;
  box.dispatch('change');
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([cpSpan(F1, '5 V', '4 V', 'Vbad', 1)]));
  ed.fills()[0].click();
  results.astralLaterLine = { whole: ed.area.value };
  globalThis.localStorage.removeItem('refdes.live-calc.autofill');
  drafts.clearDraft(h);
}

// -- client pre-gate (§3.1): text without a calc marker costs no request
//    and no panel -- a plain paragraph body stays silent
{
  const h = 'DEC-PREGATE';
  const ed = openEditor(h, 'Rail Vbad is 2 V times 2, about 4 V.');
  const afterOpen = ed.calls().length; // the open flush is pre-gated too: zero
  await advance(450);
  ed.type('Rail Vbad is 2 V times 2, about 4.4 V.');
  await advance(450);
  results.preGate = {
    afterOpen,
    afterType: ed.calls().length,
    panelHidden: ed.panel.hidden === true,
  };
  drafts.clearDraft(h);
}

// -- a NON-collapsed selection that overlaps a result range is treated like
//    a caret inside it: the author is working on those bytes (§3.5 caret
//    rule); a selection clear of the range fills
{
  const h = 'DEC-SELOVERLAP';
  const at = T1.indexOf('5 V');
  const cases = [];
  for (const [label, s, e, expectFilled] of [
    ['overlaps-left', at - 3, at + 1, false],
    ['overlaps-right', at + 1, at + 5, false],
    ['clear-outside', T1.indexOf('Rail'), T1.indexOf('`'), true],
  ]) {
    const base = calcCalls.length; // the handle repeats: settle by global index
    const ed = openEditor(h, T1);
    await settleCalc(calcCalls[base], payload([]));
    ed.area.setSelectionRange(s, e);
    ed.focus();
    await settleCalc(calcCalls[base + 1], payload([spanOn(T1, '5 V', '4 V')]));
    cases.push({ label, filled: ed.area.value === T1_FILLED });
    ed.blur();
    ed.editor.liveCalcPanel._refdesLiveCalc.destroy();
    drafts.clearDraft(h);
  }
  results.selectionOverlap = {
    cases,
    pass: cases[0].filled === false && cases[1].filled === false && cases[2].filled === true,
  };
}

// -- debounce: one request 400 ms after the last keystroke; the second
//    keystroke resets; the request carries the text and the fields bag (§3.1, §3.3)
{
  const h = 'DEC-DB';
  // a real draft field edit (the same writes a field control makes): the
  // request must carry the draft's fields verbatim, not a constant bag
  drafts.setDraftField(h, 'status', 'open');
  const ed = openEditor(h, T1);
  const openReq = ed.calls();
  await settleCalc(openReq[0], payload([]));
  ed.type(T1 + ' x');
  await flushMicro();
  const firedOnKeystroke = ed.calls().length;
  await advance(399);
  const at399 = ed.calls().length;
  await advance(2);
  const at401 = ed.calls().length;
  ed.type(T1 + ' xy');
  await advance(200);
  ed.type(T1 + ' xyz');
  await advance(250);
  const midReset = ed.calls().length;
  await advance(200);
  const afterReset = ed.calls().length;
  const sent = ed.calls()[2].body;
  results.debounce = {
    firedOnKeystroke, at399, at401, midReset, afterReset,
    sentText: sent.text, sentFields: sent.fields,
  };
  drafts.clearDraft(h);
}

// -- supersede guard: typing beats the network; the response is discarded
//    silently (no panel update) and the next debounce re-requests (§3.6)
{
  const h = 'DEC-SUP';
  const ed = openEditor(h, T1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.type(T1 + ' tail');
  await advance(401);
  const inflight = ed.calls()[1];
  ed.type(T1 + ' tail typed');
  await settleCalc(inflight, payload([spanOn(T1 + ' tail', '5 V', '4 V')]));
  results.supersede = {
    panelHidden: ed.panel.hidden,
    rowCount: ed.rowCount(),
    textKept: ed.area.value === T1 + ' tail typed',
  };
  await advance(401);
  await settleCalc(ed.calls()[2], payload([spanOn(T1 + ' tail typed', '5 V', '4 V')]));
  results.supersede.reRequestedRows = ed.rowCount();
  drafts.clearDraft(h);
}

// -- revision guard: a response computed against an old model is discarded
//    silently; the form's own revision passes and renders (§3.6)
{
  const h = 'DEC-REV';
  const ed = openEditor(h, T1);
  await settleCalc(ed.calls()[0], payload([spanOn(T1, '5 V', '4 V')], 'rev-9'));
  const guarded = { hidden: ed.panel.hidden, rows: ed.rowCount(), text: ed.area.value };
  ed.type(T1 + '.');
  await advance(401);
  await settleCalc(ed.calls()[1], payload([spanOn(T1 + '.', '5 V', '4 V')]));
  results.revisionGuard = {
    ...guarded,
    matchedHidden: ed.panel.hidden,
    matchedRows: ed.rowCount(),
  };
  drafts.clearDraft(h);
}

// -- abort: the superseding request aborts the in-flight one (§3.6 guard 1)
{
  const h = 'DEC-ABT';
  const ed = openEditor(h, T1);
  const first = ed.calls()[0];
  ed.focus(); // the focus flush is a trigger: it supersedes the open flush
  results.abort = {
    secondFired: ed.calls().length === 2,
    firstAborted: first.signal.aborted === true,
  };
  drafts.clearDraft(h);
}

// -- blur evaluates only; refocus re-fires and applies (§3.1, §3.5, §3.6)
{
  const h = 'DEC-BLUR';
  const ed = openEditor(h, T1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.focus();
  await settleCalc(ed.calls()[1], payload([]));
  ed.type(T1);
  const focusCallsBefore = focusCalls;
  ed.blur(); // mid-debounce: flush the pending request through the same closure
  const firedOnBlur = ed.calls().length === 3;
  await settleCalc(ed.calls()[2], payload([spanOn(T1, '5 V', '4 V')]));
  const blurPhase = {
    firedOnBlur,
    panelRows: ed.rowCount(),
    fillArmed: ed.fills().length,
    textUnchanged: ed.area.value === T1,
    focusStolen: focusCalls > focusCallsBefore,
    activeUnfocused: globalThis.document.activeElement === null,
  };
  ed.focus(); // refocus: the focus flush re-fires; text unchanged, guards pass
  const refired = ed.calls().length === 4;
  await settleCalc(ed.calls()[3], payload([spanOn(T1, '5 V', '4 V')]));
  results.blurFocus = { ...blurPhase, refired, filled: ed.area.value === T1_FILLED };
  drafts.clearDraft(h);
}

// -- caret skip is inclusive of BOTH result-range boundaries (§3.5)
{
  const RES = T1.indexOf('5 V');
  const cases = {};
  for (const [label, at] of [['start', RES], ['end', RES + 3], ['inside', RES + 1], ['outside', 0]]) {
    const h = `DEC-CARET-${label}`;
    const ed = openEditor(h, T1);
    await settleCalc(ed.calls()[0], payload([]));
    ed.area.setSelectionRange(at, at);
    ed.focus();
    await settleCalc(ed.calls()[1], payload([spanOn(T1, '5 V', '4 V')]));
    cases[label] = {
      text: ed.area.value,
      caret: ed.area.selectionStart,
      rows: ed.rowCount(),
    };
    drafts.clearDraft(h);
  }
  results.caret = cases;
}

// -- a span below line 0 (a fence above it) fills its own result range:
//    the line/column -> document-offset conversion (§3.3)
{
  const h = 'DEC-LINE';
  const text = '```calc\nV_in = 3.3 V\n```\n\nRail `Vbad := 2 V * 2 = 5 V`\n';
  const ed = openEditor(h, text);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([spanOn(text, '5 V', '4 V', 'Vbad', 4)]));
  const lines = ed.area.value.split('\n');
  results.lineOffset = {
    fenceKept: lines[0] === '```calc' && lines[1] === 'V_in = 3.3 V' && lines[2] === '```',
    filledLine: lines[4],
    whole: ed.area.value,
  };
  drafts.clearDraft(h);
}

// -- two stale spans on one line apply last-to-first, so the earlier
//    offsets stay valid in the same pass (§3.5)
{
  const h = 'DEC-LAST';
  const text = 'A `V1 := 2 V * 2 = 5 V` B `V2 := 3 V * 2 = 9 V`';
  const ed = openEditor(h, text);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([
    spanOn(text, '5 V', '40 V', 'V1'),
    spanOn(text, '9 V', '6 V', 'V2'),
  ]));
  results.lastToFirst = {
    whole: ed.area.value,
    want: 'A `V1 := 2 V * 2 = 40 V` B `V2 := 3 V * 2 = 6 V`',
  };
  drafts.clearDraft(h);
}

// -- the caret shifts only by applied ranges that END before it: V1 (range
//    ends before the caret, delta +1) shifts; V2 (range after the caret)
//    contributes zero (§3.5)
{
  const h = 'DEC-SHIFT';
  const text = 'A `V1 := 2 V * 2 = 5 V` B `V2 := 3 V * 2 = 9 V`';
  const caret0 = text.indexOf(' B');
  const ed = openEditor(h, text);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(caret0, caret0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([
    spanOn(text, '5 V', '44 V', 'V1'),
    spanOn(text, '9 V', '66 V', 'V2'),
  ]));
  results.caretShift = { caret0, caret: ed.area.selectionStart, whole: ed.area.value };
  drafts.clearDraft(h);
}

// -- Case B: insertText proven false -> splice fills, the no-undo line
//    shows, auto-fill self-disables for the session, Fill keeps working (§3.5)
{
  const h = 'DEC-CASEB';
  EXEC_FAILS = true;
  const ed = openEditor(h, T1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.focus();
  await settleCalc(ed.calls()[1], payload([spanOn(T1, '5 V', '4 V')]));
  const spliced = ed.area.value === T1_FILLED;
  const notes = findAll(ed.panel, 'live-calc-note');
  const warn = notes.find((n) => hasCls(n, 'warn'));
  const noUndoLine = Boolean(warn) && warn.hidden === false;
  // auto-fill is off for the session: the next stale response renders rows
  // and mutates nothing
  ed.type(T1_FILLED);
  await advance(401);
  await settleCalc(ed.calls()[2], payload([spanOn(T1_FILLED, '4 V', '8 V')]));
  const selfDisabled = { text: ed.area.value, rows: ed.rowCount() };
  // Fill (the author's own click) applies through the splice
  ed.fills()[0].click();
  const splicedText = ed.area.value;
  const splicedTo = splicedText === 'Rail `Vbad := 2 V * 2 = 8 V`';
  // a splice fires no input event: the panel must schedule the recalculation
  // itself, so it stops showing the pre-fill verdict (and Fill stops being
  // inert against a stale snapshot of its own row)
  await advance(401);
  const recycled = ed.calls().length === 4;
  const recalcSent = recycled ? ed.calls()[3].body.text === splicedText : false;
  results.caseB = {
    spliced, noUndoLine,
    selfDisabledText: selfDisabled.text,
    selfDisabledRows: selfDisabled.rows,
    fillWorks: splicedTo,
    recycled,
    recalcSent,
  };
  EXEC_FAILS = false;
  drafts.clearDraft(h);
}

// -- the session scope of the Case B stand-down (§3.5, session-scoped flag):
//    a controller constructed AFTER the first splice -- the shell builds a
//    new one on every save/poll rebuild/item switch -- starts out stood
//    down: focused, pref ON, a stale row renders, the text does NOT mutate,
//    the panel says the session is off, and the checkbox shows OFF (the
//    EFFECTIVE state). The consented Fill keeps working (Case B scenario).
{
  EXEC_FAILS = true;
  const h = 'DEC-CASEB2';
  const area = new FakeNode('textarea');
  area.value = T1;
  const calc = createLiveCalc(h, {
    getRevision: () => 'rev-0',
    isSaving: () => false,
    getFields: () => ({}),
  });
  calc.attach(area); // the open flush fires
  globalThis.document.activeElement = area; // focused: autofill would apply
  const callsFor = () => calcCalls.filter((c) => c.path.includes(encodeURIComponent(h)));
  await settleCalc(callsFor()[0], payload([spanOn(T1, '5 V', '4 V')]));
  const notes = findAll(calc.node, 'live-calc-note');
  const offLine = notes.find((n) => n.textContent.includes('off for this session'));
  results.caseBSession = {
    noMutation: area.value === T1,
    rowsShown: findAll(calc.node, 'live-calc-row').length === 1,
    offShown: Boolean(offLine) && offLine.hidden === false,
    checkboxOff: findAll(calc.node, 'live-calc-autofill')[0].checked === false,
    flagPersisted: globalThis.sessionStorage.getItem('refdes.live-calc.fallback') === 'on',
  };
  calc.destroy();
  EXEC_FAILS = false;
  // the session-scoped flag must not leak into the scenarios that follow
  globalThis.sessionStorage.removeItem('refdes.live-calc.fallback');
}

// -- an ok-within-window literal is never rewritten under auto-fill ON:
//    status ok, computed 4.436 V, stored 4.4 V stays byte-for-byte (§3.5)
{
  const h = 'DEC-OKWIN';
  const text = 'Rail `Vout := 2.218 V * 2 = 4.4 V`';
  const ed = openEditor(h, text);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  const okSpan = spanOn(text, '4.4 V', '4.436 V', 'Vout');
  okSpan.status = 'ok';
  okSpan.message = '';
  await settleCalc(ed.calls()[1], payload([okSpan]));
  results.okWithinWindow = {
    textUnchanged: ed.area.value === text,
    rows: ed.rowCount(),
    fillButtons: ed.fills().length,
  };
  drafts.clearDraft(h);
}

// -- a save in flight: no calc request; after the save the form's advanced
//    revision passes the guard and the panel renders (§3.1, §3.6)
{
  const h = 'DEC-SAVE';
  const ed = openEditor(h, T1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.focus(); // focus flush: request #2, settles clean
  await settleCalc(ed.calls()[1], payload([]));
  ed.type(T1); // the keystroke dirties the draft; the debounce is pending
  const save = find(ed.editor.node, 'save'); // the button lives in the editor block
  save.disabled = false;
  save.click(); // saveAll: the in-flight flag goes up before the round-trip
  await flushMicro();
  await advance(900); // past the debounce: the flag must have suppressed it
  const duringSave = ed.calls().length; // open + focus flush, nothing more
  await settleEdit({ revision: 'rev-1' });
  ed.focus(); // the post-save re-render re-arms: the focus flush re-requests
  const afterSave = ed.calls().length === 3;
  const text = ed.calls()[2].body.text;
  await settleCalc(ed.calls()[2], payload([spanOn(text, '5 V', '4 V')], 'rev-1'));
  results.saveInFlight = {
    duringSave, afterSave,
    panelHidden: ed.panel.hidden,
    filled: ed.area.value === T1_FILLED,
    posts: editPosts.map((p) => `${p.op}@${p.expected_revision}`),
  };
  drafts.clearDraft(h);
}

// -- the toggle: default ON applies; OFF persists in localStorage, renders
//    the rows, mutates nothing, and Fill still works; a reload restores it (§3.5, §6.1)
{
  const hOn = 'DEC-TGL-ON';
  const edOn = openEditor(hOn, T1);
  await settleCalc(edOn.calls()[0], payload([]));
  edOn.area.setSelectionRange(0, 0);
  edOn.focus();
  await settleCalc(edOn.calls()[1], payload([spanOn(T1, '5 V', '4 V')]));
  const defaultApplied = edOn.area.value === T1_FILLED;
  const checkbox = find(edOn.panel, 'live-calc-autofill');
  checkbox.checked = false;
  checkbox.dispatch('change');
  const stored = globalThis.localStorage.getItem('refdes.live-calc.autofill');
  edOn.type(T1_FILLED);
  await advance(401);
  await settleCalc(edOn.calls()[2], payload([spanOn(T1_FILLED, '4 V', '8 V')]));
  const offRendered = { text: edOn.area.value, rows: edOn.rowCount() };
  edOn.fills()[0].click();
  const fillOnOff = edOn.area.value === 'Rail `Vbad := 2 V * 2 = 8 V`';
  // a fresh editor (the reload/item-switch posture) reads the preference
  const h2 = 'DEC-TGL-OFF';
  const ed2 = openEditor(h2, T1);
  const reloadChecked = find(ed2.panel, 'live-calc-autofill').checked;
  results.toggle = {
    defaultApplied, stored,
    offTextUnchanged: offRendered.text === T1_FILLED,
    offRows: offRendered.rows,
    fillOnOff, reloadChecked,
  };
  // the preference store is global to the harness: clear it so later
  // scenarios start from the default-ON posture like a fresh browser
  globalThis.localStorage.removeItem('refdes.live-calc.autofill');
  drafts.clearDraft(hOn);
  drafts.clearDraft(h2);
}

// -- a span missing one half of its result pair is display-only: no Fill,
//    no mutation (the guards enforce the PAIR, not just result_start) (§3.3)
{
  const h = 'DEC-PAIR';
  const ed = openEditor(h, T1);
  await settleCalc(ed.calls()[0], payload([]));
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  const half = spanOn(T1, '5 V', '4 V');
  delete half.result_end; // a route that sent only one boundary
  await settleCalc(ed.calls()[1], payload([half]));
  results.halfPair = { text: ed.area.value, fills: ed.fills().length, rows: ed.rowCount() };
  drafts.clearDraft(h);
}

// -- an item switch tears the panel down: the pending 400 ms timer dies,
//    the in-flight request is aborted, the textarea listeners are removed,
//    and a failing fetch clears the container the same way (§3.8)
{
  const h = 'DEC-TEA';
  const container = new FakeNode('div');
  await renderItem(container, h);
  const area = find(container, 'body-edit');
  area.value = T1;
  area.dispatch('input'); // a pending debounce on the OLD item
  const inflight = calcCalls.filter((c) => c.path.includes(h));
  await renderItem(container, 'DEC-TEB'); // switch items
  // the textarea also carries the editor's own commit listener (it is meant
  // to survive); only live-calc's three handlers must be gone
  const liveHandlers = ['scheduleFromInput', 'flushOnBlur', 'focusFlush'];
  const leaked = ['input', 'blur', 'focus'].some((t) =>
    (area.listeners[t] || []).some((fn) => liveHandlers.includes(fn.name)));
  const afterSwitch = {
    calls: calcCalls.filter((c) => c.path.includes(h)).length,
    aborted: inflight.length >= 1 && inflight.every((c) => c.signal.aborted === true),
    leaked,
  };
  await advance(500); // the dead timer must not fire a /calc for the old item
  const afterAdvance = calcCalls.filter((c) => c.path.includes(h)).length;
  // the fetch-error path, the REAL case: a same-handle re-render (what the
  // revision poll drives). renderedHandle already matches and the container
  // has children, so the pre-fetch clear never runs -- the catch-path
  // destroy is the only thing between a live panel (pending timer,
  // in-flight request, textarea listeners) and an emptied container.
  const failBox = new FakeNode('div');
  await renderItem(failBox, h); // normal render: panel mounted, renderedHandle = h
  const failArea = find(failBox, 'body-edit');
  failArea.value = T1;
  failArea.dispatch('input'); // pending debounce on THIS panel
  await advance(401); // the request is now in flight
  const failInflight = calcCalls.filter((c) => c.path.includes(encodeURIComponent(h)));
  globalThis.fetch.__failItem = true;
  await renderItem(failBox, h); // same handle, children present -> the fetch rejects
  const failLeaked = ['input', 'blur', 'focus'].some((t) =>
    (failArea.listeners[t] || []).some((fn) => liveHandlers.includes(fn.name)));
  await advance(500); // nothing left may fire for this item
  const failCallsAfter = calcCalls.filter((c) => c.path.includes(encodeURIComponent(h))).length;
  globalThis.fetch.__failItem = false;
  const failCleared = failBox.children.length === 1 && hasCls(failBox.children[0], 'banner');
  results.teardown = {
    ...afterSwitch,
    afterAdvance,
    noLeak: afterAdvance === afterSwitch.calls,
    failCleared,
    failInflight: failInflight.length,
    failAborted: failInflight.length >= 1 && failInflight.every((c) => c.signal.aborted === true),
    failLeaked,
    failNoNewCalls: failCallsAfter === failInflight.length,
  };
  drafts.clearDraft(h);
  drafts.clearDraft('DEC-TEB');
}

// -- idempotent Fill (toggle OFF so the first Fill does the applying):
//    the second click mutates nothing and commits nothing (§3.5)
{
  const h = 'DEC-FILL';
  const ed = openEditor(h, T1);
  const commits = { n: 0 };
  const original = ed.area._refdesCommit;
  ed.area._refdesCommit = () => { commits.n += 1; original(); };
  await settleCalc(ed.calls()[0], payload([]));
  const box = find(ed.panel, 'live-calc-autofill');
  box.checked = false;
  box.dispatch('change');
  ed.area.setSelectionRange(0, 0);
  ed.focus();
  await settleCalc(ed.calls()[1], payload([spanOn(T1, '5 V', '4 V')]));
  ed.fills()[0].click();
  const afterFirst = { text: ed.area.value, commits: commits.n };
  ed.fills()[0].click();
  results.fillIdempotent = {
    afterFirstText: afterFirst.text === T1_FILLED,
    afterFirstCommits: afterFirst.commits,
    secondNoop: ed.area.value === T1_FILLED && commits.n === afterFirst.commits,
  };
  drafts.clearDraft(h);
}

// -- the shell's boot race (app.js): a watcher rebuild landing between the
//    two boot GETs must never leave the captured serial AHEAD of the view's
//    revision. The serve answers the boot GETs on parallel handler threads,
//    so arrival order, not issue order, decides who reads which build; the
//    adversarial interleaving runs the detail-view handler on build 1 and
//    the revision handler on build 2. The form then carries rev-1, the
//    baseline says serial 2, no refdes:rebuilt event ever fires, and
//    live-calc's revision guard drops every response -- the recovery signal
//    (refdes:stale-calc) must re-sync the shell so the panel comes back.
{
  globalThis.location = { hash: '#/items/DEC-BOOT' };
  globalThis.window = new EventTarget();
  globalThis.setInterval = () => 0;
  let build = { serial: 1, revision: 'rev-1' };
  globalThis.__revisionHook = () => ({ serial: build.serial, revision: build.revision, git: null });
  globalThis.__itemViewHook = (req) => {
    if (String(req).includes('/sources')) return { sources: [] };
    const v = itemRender(req);
    return { ...v, revision: build.revision, edit: { ...v.edit, file_revision: build.revision } };
  };
  const app = await import(url('app.js'));
  await flushMicro(); // boot issued its GETs; the handlers sit in the queue
  const q = (p) => __serverQueue.some((h) => h.__path.includes(p));
  // the view handler runs first (on build 1): the form carries rev-1
  if (q('/api/item/DEC-BOOT')) await __flushPath('/api/item/DEC-BOOT');
  else await __flushPath('/api/revision'); // (poll-first boot: nothing queued yet)
  if (q('/api/item/DEC-BOOT')) await __flushPath('/api/item/DEC-BOOT'); // sources
  build = { serial: 2, revision: 'rev-2' }; // the watcher rebuild lands
  if (q('/api/revision')) await __flushPath('/api/revision'); // baseline reads build 2
  const sent = calcCalls.filter((c) => c.path.includes('/api/item/DEC-BOOT/calc'));
  for (const call of sent) {
    await settleCalc(call, payload([spanOn(T1, '5 V', '4 V')], build.revision));
  }
  const dropped = findAll(__byId.detail, 'live-calc-row').length === 0;
  app.poll(); // the 2 s interval tick sees serial 2 == the baseline: silent
  let guard = 0;
  while (q('api/') && guard++ < 50) await __flushPath('api/'); // poll + recovery
  const late = calcCalls.filter((c) => c.path.includes('/api/item/DEC-BOOT/calc'));
  for (const call of late.slice(sent.length)) {
    await settleCalc(call, payload([spanOn(T1, '5 V', '4 V')], build.revision));
  }
  results.appBootRace = {
    formCarriedPreRebuildRevision: sent.length > 0 && sent[0].body.revision === 'rev-1',
    dropped,
    recoveredRows: findAll(__byId.detail, 'live-calc-row').length,
  };
  globalThis.__revisionHook = null;
  globalThis.__itemViewHook = null;
  drafts.clearDraft('DEC-BOOT'); // the shell wrote a draft during the race
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_the_live_calc_layer_debounces_guards_fills_and_persists_under_node(tmp_path):
    script = (
        HARNESS.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
        .replace("__T1__", json.dumps(T1))
        .replace("__T1_FILLED__", json.dumps(T1_FILLED))
        .replace("__A1__", json.dumps(A1))
        .replace("__A1_FILLED__", json.dumps(A1_FILLED))
        .replace("__E1__", json.dumps(E1))
        .replace("__E1_FILLED__", json.dumps(E1_FILLED))
        .replace("__F1__", json.dumps(F1))
        .replace("__F1_FILLED__", json.dumps(F1_FILLED))
    )
    # Run from a file, not `node -e`: the harness outgrew the 32k Windows
    # command-line limit (WinError 206 in CI).
    harness = tmp_path / "harness.mjs"
    harness.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the astral fixtures on the way back in.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    results = json.loads(proc.stdout.strip().splitlines()[-1])

    db = results["debounce"]
    assert db["firedOnKeystroke"] == 1, "a keystroke fired the request itself: it must only schedule it"
    assert db["at399"] == 1 and db["at401"] == 2, (
        "the request fired at the wrong time: the debounce is 400 ms after the "
        "last keystroke (§3.1)"
    )
    assert db["midReset"] == 2 and db["afterReset"] == 3, (
        "the second keystroke did not reset the debounce window"
    )
    assert db["sentText"].endswith("xyz") and db["sentFields"] == {"status": "open"}, (
        "the request must carry the textarea text and the draft's fields bag "
        "verbatim (§3.3): a constant empty bag passes the old shape check"
    )

    sup = results["supersede"]
    assert sup["panelHidden"] is True and sup["rowCount"] == 0, (
        "a response for superseded text updated the panel: the text-snapshot "
        "guard discards it silently (§3.6)"
    )
    assert sup["textKept"] is True, "the apply rewrote text typed after the request"
    assert sup["reRequestedRows"] == 1, "the next debounce did not re-request and render"

    rev = results["revisionGuard"]
    assert rev["hidden"] is True and rev["rows"] == 0, (
        "a response whose revision is not the form's own applied: the revision "
        "guard discards it silently (§3.6)"
    )
    assert rev["text"] == T1, (
        "the guarded response applied text: the revision guard must discard it "
        "silently, leaving the textarea exactly as typed (§3.6)"
    )
    assert rev["matchedHidden"] is False and rev["matchedRows"] == 1, (
        "the response matching the form's own revision did not render"
    )

    boot = results["appBootRace"]
    assert boot["dropped"] is True, (
        "the adversarial boot interleaving did not produce a stale-model "
        "drop: the scenario no longer exercises the revision guard"
    )
    assert boot["recoveredRows"] == 1, (
        "the stale-model drop left the panel silent for the life of the "
        "draft: the shell must re-sync the view on refdes:stale-calc "
        "(the observed failure: a cold-start panel that never warns)"
    )

    af = results["astralFill"]
    assert af["whole"] == A1_FILLED, (
        "Fill on a line with a preceding emoji replaced the wrong range: "
        "the server's columns are code points, textarea offsets are UTF-16 "
        "units -- spanOffsets must convert"
    )
    aa = results["astralAutoFill"]
    assert aa["whole"] == A1_FILLED, (
        "auto-fill (insertText) on a line with a preceding emoji replaced "
        "the wrong range: the same code-point conversion is required"
    )
    ac = results["astralCaseB"]
    assert ac["whole"] == A1_FILLED, (
        "the Case B .value splice on a line with a preceding emoji spliced "
        "the wrong range: the same code-point conversion is required"
    )
    acaret = results["astralCaret"]
    assert acaret["pass"] is True, (
        f"caret-skip boundaries on a line with a preceding emoji: {acaret['cases']} "
        "-- the skip test must run on converted offsets, not raw code-point "
        "columns (emoji shifts the range by one unit)"
    )
    am = results["astralMix"]
    assert am["whole"] == E1_FILLED, (
        "two emoji with a combining accent before the span: Fill replaced "
        "the wrong range (one unit of shift per astral code point)"
    )
    an = results["astralLaterLine"]
    assert an["whole"] == F1_FILLED, (
        "Fill on a later line after an emoji line regressed: line starts "
        "are UTF-16 already, only same-line columns need conversion"
    )

    assert results["abort"] == {"secondFired": True, "firstAborted": True}, (
        "the superseding request did not abort the in-flight one (§3.6 guard 1)"
    )

    bf = results["blurFocus"]
    assert bf["firedOnBlur"] is True, "blur did not flush the pending request through the closure"
    assert bf["panelRows"] == 1 and bf["fillArmed"] == 1, (
        "the blur-fired response did not refresh the panel and arm the Fill row"
    )
    assert bf["textUnchanged"] is True, "a blur-fired response mutated text while unfocused"
    assert bf["focusStolen"] is False and bf["activeUnfocused"] is True, (
        "the unfocused response called focus: the focus rule forbids stealing it (§3.5)"
    )
    assert bf["refired"] is True, "the focus flush did not re-fire the request (§3.1)"
    assert bf["filled"] is True, (
        "the refocused request did not apply under the normal rules (§3.6 refocus path)"
    )

    carets = results["caret"]
    for name in ("start", "end", "inside"):
        assert carets[name]["text"] == T1, (
            f"caret {name}: a result range containing the caret (inclusive of both "
            "boundaries) was overwritten (§3.5)"
        )
        assert carets[name]["rows"] == 1, "the skipped span lost its panel row"
    assert carets["inside"]["caret"] == T1.index("5 V") + 1, "the caret parked inside a skipped range moved"
    assert carets["outside"]["text"] == T1_FILLED, (
        "a span whose result range does not contain the caret was not filled"
    )

    line = results["lineOffset"]
    assert line["fenceKept"] is True, "the conversion disturbed the lines above the span"
    assert line["filledLine"] == "Rail `Vbad := 2 V * 2 = 4 V`", (
        "a span on line 4 was not filled at its own converted offsets: the "
        "line/column -> document-offset conversion (§3.3)"
    )

    ltf = results["lastToFirst"]
    assert ltf["whole"] == ltf["want"], (
        f"spans did not apply last-to-first with earlier ranges valid: {ltf}"
    )

    shift = results["caretShift"]
    assert shift["caret"] == shift["caret0"] + 1, (
        "the caret shift counted a range ending after it (or missed one ending "
        f"before it): {shift}"
    )

    caseb = results["caseB"]
    assert caseb["spliced"] is True, "Case B did not fill through the .value splice"
    assert caseb["noUndoLine"] is True, "the no-undo panel line is missing while Case B is active"
    assert caseb["selfDisabledText"] == T1_FILLED and caseb["selfDisabledRows"] == 1, (
        "auto-fill kept mutating after insertText proved to fail: it must "
        "self-disable for the session and keep rendering rows (§3.5)"
    )
    pair = results["halfPair"]
    assert pair == {"text": T1, "fills": 0, "rows": 1}, (
        "a span with only one result boundary got a Fill button or a mutation: "
        "the guards must enforce the full pair, not just result_start"
    )
    assert caseb["fillWorks"] is True, "Fill stopped working in Case B"
    assert caseb["recycled"] is True and caseb["recalcSent"] is True, (
        "after a Case B splice nothing re-requested: a .value splice fires no "
        "input event, so the panel must schedule its own recalculation"
    )

    okw = results["okWithinWindow"]
    assert okw["textUnchanged"] is True, (
        "an ok-within-window literal (4.4 V, computed 4.436 V) was rewritten: the "
        "auto-fill gate is `stale`, never `computed != stored` (§3.5, D1)"
    )
    assert okw["rows"] == 1 and okw["fillButtons"] == 0, (
        "ok rows must render display-only: no Fill button on an ok row"
    )

    save = results["saveInFlight"]
    assert save["duringSave"] == 2, (
        f"a calc request fired while a save round-trip was in flight: {save} "
        "(2 = the open flush + the focus flush that preceded the save)"
    )
    assert save["posts"] == ["set_body@rev-0"]
    assert save["afterSave"] is True, "the post-save re-arm did not re-request"
    assert save["panelHidden"] is False and save["filled"] is True, (
        "the form's revision advanced with the save and the guard discarded the "
        "response: it must pass on the saved model (§3.6)"
    )
    td = results["teardown"]
    assert td["aborted"] is True, (
        "an item switch left the old panel's in-flight request running: every "
        "container clear must destroy the controller first (§3.8)"
    )
    assert td["leaked"] is False, (
        "the detached textarea kept a live-calc listener after the switch: the "
        "panel's listeners die with the view (§3.8)"
    )
    assert td["noLeak"] is True and td["afterAdvance"] == td["calls"], (
        "the pending 400 ms timer fired a /calc for the item that was switched away"
    )
    assert td["failCleared"] is True, (
        "the fetch-error path did not run the teardown: it clears the container "
        "and must destroy the panel like every other clear"
    )
    assert td["failInflight"] >= 1, (
        "the fetch-error scenario reached the failed fetch with no request in "
        "flight: every abort assert below would be true of an empty list"
    )
    assert td["failAborted"] is True, (
        "the same-handle re-render whose fetch failed left its in-flight /calc "
        "running: the catch-path clear must destroy the panel it is emptying"
    )
    assert td["failLeaked"] is False, (
        "the failed fetch cleared the container but left live-calc listeners "
        "on the textarea"
    )
    assert td["failNoNewCalls"] is True, (
        "a timer kept running after the failed fetch: the destroyed panel must "
        "fire no further /calc (the timer dies with the view)"
    )

    pg = results["preGate"]
    assert pg["afterOpen"] == 0 and pg["afterType"] == 0, (
        f"a body without a calc marker cost a request: {pg} (§3.1 pre-gate)"
    )
    assert pg["panelHidden"] is True, "the pre-gate cleared the panel of an empty body"

    so = results["selectionOverlap"]
    assert so["pass"] is True, (
        f"a non-collapsed selection overlapping a result range was not treated "
        f"like a caret inside it: {so['cases']}"
    )

    cs = results["caseBSession"]
    assert cs["noMutation"] is True, (
        "a controller built AFTER the first Case B splice auto-filled again: "
        "the stand-down is session-scoped (§3.5), not per-controller"
    )
    assert cs["rowsShown"] is True and cs["offShown"] is True, (
        "the rebuilt controller must still render rows AND say the session "
        "stand-down is in force (§3.5)"
    )
    assert cs["checkboxOff"] is True, (
        "the checkbox showed ON while the session stand-down suppressed "
        "mutation: it must display the effective state"
    )
    assert cs["flagPersisted"] is True, "the stand-down did not persist for the session"



    tgl = results["toggle"]
    assert tgl["defaultApplied"] is True, "auto-fill is default ON (§6.1)"
    assert tgl["stored"] == "off", "the toggle does not persist to localStorage"
    assert tgl["offTextUnchanged"] is True and tgl["offRows"] == 1, (
        "toggle OFF must gate exactly the text mutation: rows keep rendering (§3.5)"
    )
    assert tgl["fillOnOff"] is True, "Fill stopped working with auto-fill OFF"
    assert tgl["reloadChecked"] is False, "the persisted preference did not survive the reload"

    fill = results["fillIdempotent"]
    assert fill["afterFirstText"] is True and fill["afterFirstCommits"] == 1
    assert fill["secondNoop"] is True, (
        "a second Fill on an applied span mutated text: Fill is idempotent (§3.5)"
    )


