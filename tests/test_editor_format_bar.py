"""The formatting bar's shared Case A/B mutator, driven under node
(in-prog-logs/editor-format-toolbar-design-20261029.md §B, slice 1).

Same posture as ``test_editor_link_undo.py`` / ``test_editor_live_calc.py``:
no browser, the REAL served modules under node -- the real ``editor.js``
wiring (which builds the real ``formatbar.js`` bar in ``bodyControl``) over
``api.js``, ``drafts.js``, ``live-calc.js`` and stubs for DOM / sessionStorage
/ fetch. The ``execCommand`` stub mutates the fake textarea like a real one
and fires ``input``, so Case A proves "one insertion = one execCommand = one
undo step = the normal draft/panel path"; ``EXEC_FAILS`` pins the Case B
splice, its exactly-one synthetic ``input`` dispatch, and the shared
session fallback key (``refdes.live-calc.fallback`` -- the same key #388's
panel stands down on; the bar shares it, so one detection serves both).

Scenarios, one node process:

- core-row semantics for every §B button: wrap, placeholder-selection,
  toggle-unwrap (run-marker guard: an italic toggle never fires inside a
  ``**bold**`` pair), heading cycle through H6->none, multi-line list /
  numbered / quote prefix and strip, link URL-vs-text split + unwrap, the
  table skeleton with the first header cell selected, the HR as its own
  blank-line-padded paragraph, a block insert with the caret inside a calc
  fence lands AFTER the fence, fences balanced after every block op.
- caret placement and the UTF-16 trap: an astral (emoji) character before
  the selection must not shift a wrap (``#388``'s exact bug class).
- Case A: execCommand called exactly once per insertion, selection restored.
  Case B: splice, exactly one synthetic input, fallback key set and honored
  (the next op skips execCommand), the bar's one-line note shows.
- the isSaving() gate: a click and a shortcut mid-save mutate nothing.
- shortcuts: the SHORTCUTS array walks to exactly the §B bindings
  (Ctrl/Cmd+B/I/K, Alt+Shift+5, Ctrl/Cmd+Alt+C); nothing browser-reserved
  (Ctrl+Z, Ctrl+Shift+I, Ctrl+T, Ctrl+digits, bare letters) matches; a bound
  keydown fires the op and preventDefaults.
- a11y: every button is ``<button type="button">`` with a non-empty
  aria-label; a mousedown preventDefaults (focus/selection stay in the
  textarea); the keydown listener is taken over (not stacked) across a
  re-render of the same textarea.
- read-only: an editor whose body is not editable mounts no bar; item.js
  places the bar BEFORE the textarea in DOM order.
- insertIntoBody runs through the shared mutator (the image picker's insert
  path fires the normal input event -- the latent panel gap §B fixes) and is
  inert mid-save.
- live-calc coexistence: a bar insertion on a body with a calc span feeds
  the panel's normal debounced input path.
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
  removeItem: (k) => storeDelete,
};
function storeDelete(k) { localStore.delete(k); }

// ---------- fake DOM
let focusCalls = 0;
let EXEC_FAILS = false;
const execCalls = [];

class FakeEvent {
  constructor(type, init) {
    this.type = type;
    Object.assign(this, init || {});
    this.defaultPrevented = false;
  }
  preventDefault() { this.defaultPrevented = true; }
}
globalThis.Event = FakeEvent;

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
  getAttribute(name) { return this.attrs[name] === undefined ? null : this.attrs[name]; }
  removeAttribute(name) { delete this.attrs[name]; }
  get firstChild() { return this.children[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  dispatchEvent(ev) {
    for (const fn of (this.listeners[ev.type] || []).slice()) fn(ev);
    return !ev.defaultPrevented;
  }
  dispatch(type, ev) {
    const event = ev instanceof FakeEvent ? ev : Object.assign(new FakeEvent(type), ev);
    this.dispatchEvent(event);
    return event;
  }
  click() { this.dispatch('click'); }
  contains(node) {
    let p = node;
    while (p) { if (p === this) return true; p = p._parent; }
    return false;
  }
  querySelectorAll(sel) {
    const match = (n) => {
      if (sel.startsWith('.')) return hasCls(n, sel.slice(1));
      if (sel.startsWith('[')) {
        const camel = sel.slice(1, -1).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        return n.dataset[camel] !== undefined || n.attrs[sel.slice(1, -1)] !== undefined;
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

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector: (sel) => (sel.includes('refdes-token') ? { content: 'tok' } : null),
  activeElement: null,
  execCommand: (name, ui, text) => {
    execCalls.push(name);
    if (name !== 'insertText' || EXEC_FAILS) return false;
    const a = globalThis.document.activeElement;
    if (!a || a.tagName !== 'TEXTAREA') return false;
    // the real browser behavior the design's backbone depends on: the
    // replacement happens at the selection, the caret lands after the text,
    // and a native input event fires (that is what feeds the draft AND the
    // live-calc panel through their ordinary listeners)
    const s = Math.min(a.selectionStart, a.value.length);
    const e = Math.min(Math.max(a.selectionEnd, s), a.value.length);
    a.value = a.value.slice(0, s) + text + a.value.slice(e);
    a.selectionStart = a.selectionEnd = s + text.length;
    a.dispatchEvent(new FakeEvent('input', { bubbles: true }));
    return true;
  },
};
globalThis.window = { addEventListener: () => {} };

// ---------- fetch
const calcCalls = [];
const editPosts = [];
let editSettle = null;
const imageRows = [{
  name: 'rail.png', rel: 'assets/rail.png', bytes: 1234,
  markdown: '![rail](assets/rail.png)', insertable: true,
}];
globalThis.fetch = async (path, init) => {
  if (path.includes('/calc')) {
    const call = { path, body: JSON.parse(init.body), settle: null };
    call.promise = new Promise((resolve) => { call.settle = (payload) => resolve(
      { ok: true, status: 200, statusText: 'OK', json: async () => payload }); });
    calcCalls.push(call);
    return call.promise;
  }
  if (path.includes('/edit')) {
    editPosts.push(init && init.body ? JSON.parse(init.body) : null);
    return new Promise((resolve) => {
      editSettle = (payload, ok) => resolve(
        { ok, status: ok ? 200 : 422, statusText: 'OK', json: async () => payload });
    });
  }
  if (path.startsWith('/api/images')) {
    return { ok: true, status: 200, statusText: 'OK', json: async () => ({ images: imageRows }) };
  }
  if (path.startsWith('/api/items')) {
    return { ok: true, status: 200, statusText: 'OK', json: async () => ({ items: [], facets: {} }) };
  }
  if (path.startsWith('/api/item/')) {
    const h = decodeURIComponent(path.split('/api/item/')[1].split('?')[0]);
    return { ok: true, status: 200, statusText: 'OK', json: async () => itemRender(h) };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) };
};

const { createEditor } = await import(url('editor.js'));
const { createFormatBar, applyEdit, SHORTCUTS } = await import(url('formatbar.js'));
const drafts = await import(url('drafts.js'));

function editItem(handle) {
  return {
    id: handle,
    revision: 'rev-0',
    edit: { editable: true, file_revision: 'rev-0', fields: {}, body: { editable: true }, links: {} },
  };
}

function itemRender(handle) {
  return {
    id: handle, handle, title: 'Item.', type: 'decision',
    source_file: 'items/decisions.yaml', source_line: 3, page: `items/${handle}`,
    fields: {}, inherited_fields: [], body: 'plain body',
    edit: { editable: true, file_revision: 'rev-0', fields: {}, body: { editable: true } },
    links: { outgoing: [], incoming: [] },
    coverage: null, checks: [], diagnostics: [],
  };
}

const tick = (ms) => new Promise((r) => setTimeout(r, ms));
const settleEdit = async (payload, ok = true) => {
  const settle = editSettle;
  editSettle = null;
  if (settle) settle(payload, ok);
  await tick(5);
};

function openEditor(handle, body) {
  const editor = createEditor(editItem(handle), handle, () => {}, () => {});
  const area = editor.bodyControl(body, null);
  globalThis.document.activeElement = area;
  const bar = area._refdesFormatBar;
  const op = (name) => findAll(bar, `fmt-${name}`)[0];
  return {
    editor, area, bar,
    click: (name) => op(name).click(),
    select: (s, e) => area.setSelectionRange(s, e === undefined ? s : e),
  };
}

const results = {};

// ---------- core row: wrap / placeholder / toggle
{
  const h = 'FB-BOLD';
  const ed = openEditor(h, 'hello world');
  const n0 = execCalls.length;
  ed.select(0, 5);
  ed.click('bold');
  results.boldWrap = {
    value: ed.area.value, sel: [ed.area.selectionStart, ed.area.selectionEnd],
    execs: execCalls.length - n0, focused: focusCalls > 0,
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-PLACE';
  const ed = openEditor(h, '');
  ed.select(0, 0);
  ed.click('bold');
  const s = ed.area.value.indexOf('bold text');
  results.boldPlaceholder = {
    value: ed.area.value,
    sel: [ed.area.selectionStart, ed.area.selectionEnd],
    selIsPlaceholder: ed.area.selectionStart === s
      && ed.area.selectionEnd === s + 'bold text'.length,
  };
  ed.click('italic'); // placeholder replaced by a fresh caret op at the selection
  results.italicAfterBold = { value: ed.area.value };
  drafts.clearDraft(h);
}
{
  const h = 'FB-UNWRAP';
  const ed = openEditor(h, 'go **bold** end');
  ed.select(5, 5); // caret inside the pair
  ed.click('bold');
  results.boldUnwrap = {
    value: ed.area.value,
    sel: [ed.area.selectionStart, ed.area.selectionEnd],
    innerSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'bold',
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-RUNMARK';
  const ed = openEditor(h, '**bold**');
  ed.select(3, 3); // caret inside a BOLD pair: the italic toggle must NOT fire
  ed.click('italic');
  results.italicInsideBold = {
    value: ed.area.value,
    want: '**b*italic text*old**',
    inner: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-STRIKE';
  const ed = openEditor(h, 'a b');
  ed.select(2, 3);
  ed.click('strike');
  results.strikeWrap = { value: ed.area.value, sel: [ed.area.selectionStart, ed.area.selectionEnd] };
  drafts.clearDraft(h);
}
{
  const h = 'FB-CODE';
  const ed = openEditor(h, 'x = 1 is 4 V');
  ed.select(0, 5);
  ed.click('code');
  results.codeWrap = { value: ed.area.value, sel: [ed.area.selectionStart, ed.area.selectionEnd] };
  ed.select(0, 0);
  ed.click('code');
  drafts.clearDraft(h);
}

// ---------- heading cycle (caret line only, H6 -> none)
{
  const h = 'FB-HEAD';
  const ed = openEditor(h, 'Title here\n\nsecond para');
  const seq = [];
  for (let i = 0; i < 7; i += 1) {
    ed.click('heading');
    seq.push({ line: ed.area.value.split('\n')[0], caret: ed.area.selectionStart });
  }
  results.headingCycle = {
    seq,
    // line 1 stays untouched: the op is the caret line only
    secondLine: ed.area.value.split('\n')[2],
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-HEADSEL';
  const ed = openEditor(h, 'alpha\nbeta');
  ed.select(0, 10);
  ed.click('heading');
  results.headingWithSel = { value: ed.area.value };
  drafts.clearDraft(h);
}

// ---------- lists (multi-line selection = every line)
{
  const h = 'FB-LIST';
  const ed = openEditor(h, 'alpha\nbeta\ngamma');
  ed.select(0, 15);
  ed.click('list');
  const prefixed = { value: ed.area.value, sel: [ed.area.selectionStart, ed.area.selectionEnd] };
  ed.click('list'); // toggle-off: strip every line
  results.listMulti = { prefixed, stripped: ed.area.value };
  ed.select(0, 0);
  ed.click('list'); // caret line
  results.listCaret = { value: ed.area.value };
  drafts.clearDraft(h);
}
{
  const h = 'FB-LISTSTRIP';
  const ed = openEditor(h, '- a\n* b\n+ c');
  ed.select(0, 12);
  ed.click('list');
  results.listStripMixed = { value: ed.area.value };
  drafts.clearDraft(h);
}
{
  const h = 'FB-NUM';
  const ed = openEditor(h, 'one\ntwo\nthree');
  ed.select(0, 13);
  ed.click('numbered');
  const prefixed = ed.area.value;
  ed.select(0, prefixed.length);
  ed.click('numbered');
  results.numbered = { prefixed, stripped: ed.area.value };
  drafts.clearDraft(h);
}
{
  const h = 'FB-NUMSTRIP';
  const ed = openEditor(h, '3. a\n7. b');
  ed.select(0, 8);
  ed.click('numbered');
  results.numberedStrip = { value: ed.area.value };
  drafts.clearDraft(h);
}
{
  const h = 'FB-QUOTE';
  const ed = openEditor(h, 'q1\nq2');
  ed.select(0, 4);
  ed.click('quote');
  const prefixed = ed.area.value;
  ed.select(0, prefixed.length);
  ed.click('quote');
  results.quote = { prefixed, stripped: ed.area.value };
  drafts.clearDraft(h);
}

// ---------- link
{
  const h = 'FB-LINK0';
  const ed = openEditor(h, '');
  ed.select(0, 0);
  ed.click('link');
  results.linkCaret = {
    value: ed.area.value,
    urlSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'url',
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-LINKURL';
  const ed = openEditor(h, 'see https://x.dev/y now');
  ed.select(4, 19);
  ed.click('link');
  results.linkUrl = {
    value: ed.area.value,
    textSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'link text',
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-LINKTEXT';
  const ed = openEditor(h, 'see REQ-001 now');
  ed.select(4, 11);
  ed.click('link');
  results.linkText = {
    value: ed.area.value,
    urlSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'url',
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-LINKUNWRAP';
  const ed = openEditor(h, 'go [see REQ](url) end');
  ed.select(15, 15); // caret inside the parens
  ed.click('link');
  results.linkUnwrap = {
    value: ed.area.value,
    text: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}

// ---------- table / HR: paragraph padding, fence safety
{
  const h = 'FB-TABLE';
  const ed = openEditor(h, 'Intro text');
  ed.select(10, 10);
  const n0 = execCalls.length;
  ed.click('table');
  const a = ed.area.value.indexOf('| a');
  results.table = {
    value: ed.area.value,
    padded: ed.area.value === 'Intro text\n\n| a | b |\n|---|---|\n|   |   |',
    aSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'a'
      && ed.area.selectionStart === a + 2,
    fences: (ed.area.value.match(/^```/gm) || []).length,
    execs: execCalls.length - n0,
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-HR';
  const ed = openEditor(h, 'key: value');
  ed.select(0, 0);
  ed.click('hr');
  results.hrBeforeKey = {
    value: ed.area.value,
    // the rule is blank-line separated from the YAML-key-shaped line
    blankSeparated: ed.area.value === '---\n\nkey: value',
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-FENCE';
  const body = '```calc\nV = 2 V\n```\n';
  const ed = openEditor(h, body);
  ed.select(8, 8); // caret INSIDE the fence body
  ed.click('table');
  const lines = ed.area.value.split('\n');
  results.blockAfterFence = {
    value: ed.area.value,
    fenceKept: lines[0] === '```calc' && lines[1] === 'V = 2 V' && lines[2] === '```',
    tableAfter: ed.area.value.startsWith('```calc\nV = 2 V\n```\n\n| a | b |'),
    fences: (ed.area.value.match(/^```/gm) || []).length,
  };
  drafts.clearDraft(h);
}

// ---------- caret placement + the UTF-16 (astral) trap
{
  const h = 'FB-ASTRAL';
  const body = '\U0001F600 hello world';
  const ed = openEditor(h, body);
  ed.select(body.indexOf('hello'), body.indexOf('hello') + 5);
  ed.click('bold');
  results.astralWrap = {
    value: ed.area.value,
    want: '\U0001F600 **hello** world',
    ok: ed.area.value === '\U0001F600 **hello** world',
    sel: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}

// ---------- CRLF-free textarea semantics
{
  const h = 'FB-CRLF';
  const ed = openEditor(h, 'one\n\ntwo');
  ed.select(0, 3);
  ed.click('bold');
  ed.select(0, 0);
  ed.click('hr');
  results.crlfFree = { value: ed.area.value, noCR: !ed.area.value.includes('\r') };
  drafts.clearDraft(h);
}

// ---------- Case A: exactly one execCommand per insertion
{
  const h = 'FB-CASEA';
  const ed = openEditor(h, 'abc');
  ed.select(0, 3);
  const n0 = execCalls.length;
  ed.click('bold');
  const fns = execCalls.slice(n0);
  results.caseA = {
    inserts: fns.filter((n) => n === 'insertText').length,
    value: ed.area.value,
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}

// ---------- Case B: splice, one synthetic input, shared session flag
{
  const h = 'FB-CASEB';
  EXEC_FAILS = true;
  const ed = openEditor(h, 'hi there');
  let inputs = 0;
  ed.area.addEventListener('input', () => { inputs += 1; });
  ed.select(0, 2);
  const n0 = execCalls.length;
  ed.click('bold');
  const first = {
    value: ed.area.value,
    sel: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
    execTried: execCalls.length - n0,
    inputs,
    draft: drafts.getDraft(h).body,
    flag: globalThis.sessionStorage.getItem('refdes.live-calc.fallback'),
    note: findAll(ed.bar, 'format-bar-note').some((n) => n.hidden === false
      && n.textContent.includes('more than one step')),
  };
  ed.select(7, 12);
  const n1 = execCalls.length;
  ed.click('italic');
  const second = {
    value: ed.area.value,
    execTried: execCalls.length - n1, // honored: straight to Case B
    inputs,
  };
  results.caseB = { first, second };
  EXEC_FAILS = false;
  globalThis.sessionStorage.removeItem('refdes.live-calc.fallback');
  drafts.clearDraft(h);
}
{
  // a bar built with the session flag already set says so up front
  globalThis.sessionStorage.setItem('refdes.live-calc.fallback', 'on');
  const h = 'FB-CASEB2';
  const ed = openEditor(h, 'x');
  results.caseBSession = {
    noteShown: findAll(ed.bar, 'format-bar-note').some((n) => n.hidden === false
      && n.textContent.includes('more than one step')),
  };
  globalThis.sessionStorage.removeItem('refdes.live-calc.fallback');
  drafts.clearDraft(h);
}

// ---------- the isSaving() gate
{
  const h = 'FB-SAVE';
  const ed = openEditor(h, 'body x');
  ed.area.value = 'body x!';
  ed.area.dispatch('input'); // dirty the draft the ordinary way
  const save = find(ed.editor.node, 'save');
  save.disabled = false;
  save.click(); // saveAll: the in-flight flag goes up before the round-trip
  await tick(5);
  const n0 = execCalls.length;
  const sel0 = [ed.area.selectionStart, ed.area.selectionEnd];
  ed.click('bold');
  ed.area.dispatch('keydown', { key: 'b', code: 'KeyB', ctrlKey: true });
  results.savingGate = {
    value: ed.area.value,
    unchanged: ed.area.value === 'body x!',
    selUnchanged: ed.area.selectionStart === sel0[0] && ed.area.selectionEnd === sel0[1],
    execs: execCalls.length - n0,
    posts: editPosts.length,
  };
  // the image picker's insert (insertIntoBody) is gated too
  await settleEdit({ revision: 'rev-1' });
  drafts.clearDraft(h);
}

// ---------- shortcuts: the array walks, bound keys fire, reserved keys do not
{
  const mk = (o) => Object.assign({
    key: '', code: '', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false,
    preventDefault() { this.defaultPrevented = true; },
  }, o);
  const fired = (o) => SHORTCUTS.filter((s) => s.match(mk(o))).map((s) => s.op);
  const boundOps = SHORTCUTS.map((s) => s.op).sort();
  results.shortcuts = {
    boundOps,
    ctrlB: fired({ ctrlKey: true, key: 'b' }),
    metaB: fired({ metaKey: true, key: 'b' }),
    ctrlI: fired({ ctrlKey: true, key: 'i' }),
    ctrlShiftI: fired({ ctrlKey: true, shiftKey: true, key: 'I' }),
    ctrlShiftI2: fired({ ctrlKey: true, shiftKey: true, key: 'i' }),
    ctrlK: fired({ ctrlKey: true, key: 'k' }),
    ctrlZ: fired({ ctrlKey: true, key: 'z' }),
    ctrlY: fired({ ctrlKey: true, key: 'y' }),
    ctrlT: fired({ ctrlKey: true, key: 't' }),
    ctrlDigit: fired({ ctrlKey: true, key: '1' }),
    ctrlAltT: fired({ ctrlKey: true, altKey: true, key: 't' }),
    ctrlAltC: fired({ ctrlKey: true, altKey: true, key: 'c' }),
    altShift5: fired({ altKey: true, shiftKey: true, code: 'Digit5', key: '%' }),
    bareB: fired({ key: 'b' }),
    tab: fired({ key: 'Tab', ctrlKey: true }),
  };
}
{
  // a bound keydown on the textarea fires the op and preventDefaults
  const h = 'FB-KEY';
  const ed = openEditor(h, 'key body');
  ed.select(0, 3);
  const ev = { key: 'b', ctrlKey: true, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  const sent = ed.area.dispatch('keydown', ev);
  results.keydownFires = {
    value: ed.area.value,
    prevented: sent.defaultPrevented === true,
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}
{
  // the keydown handler is taken over across a re-render, never stacked
  const h = 'FB-TAKEOVER';
  const ed = openEditor(h, 'one');
  ed.editor.bodyControl('one', ed.area);
  results.keydownTakeover = {
    count: (ed.area.listeners.keydown || []).length,
  };
  drafts.clearDraft(h);
}

// ---------- a11y: real buttons, labels, mousedown keeps the selection
{
  const h = 'FB-A11Y';
  const ed = openEditor(h, 'a11y');
  const buttons = findAll(ed.bar, 'fmt-btn');
  results.a11y = {
    count: buttons.length,
    allButtons: buttons.every((b) => b.tagName === 'BUTTON'),
    allTyped: buttons.every((b) => b.type === 'button'),
    allLabeled: buttons.every((b) => (b.getAttribute('aria-label') || '').length > 0),
    barCls: hasCls(ed.bar, 'format-bar'),
  };
  const mdown = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  const b = buttons[0];
  const sentMdown = b.dispatch('mousedown', mdown);
  results.a11y.mousedownPrevented = sentMdown.defaultPrevented === true;
  results.a11y.ops = ['bold', 'italic', 'strike', 'code', 'heading', 'list', 'numbered',
    'quote', 'link', 'table', 'hr']
    .map((op) => Boolean(findAll(ed.bar, `fmt-${op}`).length));
  drafts.clearDraft(h);
}

// ---------- read-only: no bar; item.js: bar precedes the textarea
{
  const h = 'FB-RO';
  const editor = createEditor({
    id: h, revision: 'rev-0',
    edit: { editable: false, reason: 'sealed', fields: {}, body: { editable: false } },
  }, h, () => {}, () => {});
  const bodyControlResult = editor.bodyControl('text', null);
  results.readOnly = {
    control: bodyControlResult === null,
    noBar: findAll(editor.node, 'format-bar').length === 0,
  };
}
{
  const { renderItem } = await import(url('item.js'));
  const container = new FakeNode('div');
  await renderItem(container, 'FB-ITEM');
  const seq = [];
  const walk = (n) => { seq.push(n); for (const c of n.children) walk(c); };
  walk(container);
  const bar = find(container, 'format-bar');
  const area = find(container, 'body-edit');
  results.mount = {
    hasBar: Boolean(bar),
    hasArea: Boolean(area),
    barBeforeArea: seq.indexOf(bar) !== -1 && seq.indexOf(bar) < seq.indexOf(area),
    keydownOnArea: (area.listeners.keydown || []).length === 1,
  };
}

// ---------- insertIntoBody runs through the shared mutator (image picker)
{
  const h = 'FB-IMG';
  const ed = openEditor(h, 'body');
  ed.editor.node.appendChild(ed.editor.imagePicker);
  await tick(20); // the image rows promise
  ed.select('body'.length);
  const add = find(ed.editor.node, 'image-insert');
  const n0 = execCalls.length;
  add.click();
  results.imageInsert = {
    value: ed.area.value,
    want: 'body\n\n![rail](assets/rail.png)',
    execs: execCalls.filter((_, i) => i >= n0 && execCalls[i] === 'insertText').length,
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}

// ---------- live-calc coexistence: an insert feeds the panel's input path
{
  const h = 'FB-LIVE';
  const ed = openEditor(h, 'Rail `Vout := 2 V`');
  const calls = () => calcCalls.filter((c) => c.path.includes(encodeURIComponent(h)));
  const openReq = calls();
  openReq[0].settle({ revision: 'rev-0', spans: [] });
  await tick(5);
  ed.select(0, 0);
  ed.click('bold'); // Case A: the native input event fires
  await tick(450); // past the panel's 400 ms debounce
  const after = calls();
  results.liveCalcFeeds = {
    openFired: openReq.length === 1,
    recomputed: after.length === 2,
    sentText: after[1] ? after[1].body.text : null,
  };
  if (after[1]) after[1].settle({ revision: 'rev-0', spans: [] });
  await tick(5);
  drafts.clearDraft(h);
}

// ---------- the shared mutator, called directly (editor.js uses it too)
{
  const h = 'FB-MUT';
  const area = new FakeNode('textarea');
  area.value = 'mutate me';
  globalThis.document.activeElement = area;
  const r = applyEdit(area, 0, 7, 'CHANGE', 0, 6, {});
  results.mutator = {
    result: r === true,
    value: area.value,
    sel: [area.selectionStart, area.selectionEnd],
    focused: globalThis.document.activeElement === area,
  };
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_the_format_bar_mutates_the_body_through_the_shared_case_a_b_contract(tmp_path):
    script = HARNESS.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
    # Run from a file, not `node -e`: the harness outgrew the 32k Windows
    # command-line limit (WinError 206 in CI).
    harness = tmp_path / "harness.mjs"
    harness.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stdout}\n{proc.stderr}"
    results = json.loads(proc.stdout.strip().splitlines()[-1])

    # -- wrap: markers land, inner text is selected, one execCommand, the
    #    draft commits through the ordinary input path
    bw = results["boldWrap"]
    assert bw["value"] == "**hello** world", bw
    assert bw["sel"] == [2, 7], "the inner text must be selected after a wrap"
    assert bw["execs"] == 1, "one insertion must be exactly one execCommand (one undo step)"
    assert bw["focused"] is True, "the mutator focuses the textarea"
    assert bw["draft"] == "**hello** world", "Case A commits the draft through the input listener"

    bp = results["boldPlaceholder"]
    assert bp["value"] == "**bold text**", bp
    assert bp["selIsPlaceholder"] is True, "the placeholder must be selected (typing replaces it)"

    bu = results["boldUnwrap"]
    assert bu["value"] == "go bold end", bu
    assert bu["innerSelected"] is True, "toggle-off reselects the inner text"

    # the italic toggle must not fire inside a bold pair: a `*` run of two is
    # a bold marker, not a pair of italic ones, so the caret op inserts the
    # placeholder at the caret and selects it
    assert results["italicInsideBold"]["value"] == results["italicInsideBold"]["want"], (
        results["italicInsideBold"]
    )
    assert results["italicInsideBold"]["inner"] == "italic text", results["italicInsideBold"]

    sw = results["strikeWrap"]
    assert sw["value"] == "a ~~b~~", sw
    assert sw["sel"] == [4, 5], sw
    cw = results["codeWrap"]
    assert cw["value"] == "`x = 1` is 4 V", cw
    assert cw["sel"] == [1, 6], cw

    # -- heading: the exact §B cycle, caret at the line content start
    hc = results["headingCycle"]
    want = [f"{'#' * n} Title here" for n in range(1, 7)] + ["Title here"]
    assert [s["line"] for s in hc["seq"]] == want, hc["seq"]
    assert [s["caret"] for s in hc["seq"]] == [1, 3, 4, 5, 6, 7, 0], hc["seq"]
    assert hc["secondLine"] == "second para", "the heading op touches the caret line only"
    assert results["headingWithSel"]["value"] == "# alpha\nbeta", results["headingWithSel"]

    # -- lists: every selected line is prefixed (forum convention), toggle
    #    strips each marker form
    lm = results["listMulti"]
    assert lm["prefixed"]["value"] == "- alpha\n- beta\n- gamma", lm
    assert lm["prefixed"]["sel"] == [0, 22], "the transformed lines stay selected"
    assert lm["stripped"] == "alpha\nbeta\ngamma", lm
    assert results["listCaret"]["value"] == "- alpha\nbeta\ngamma", results["listCaret"]
    assert results["listStripMixed"]["value"] == "a\nb\nc", results["listStripMixed"]
    nm = results["numbered"]
    assert nm["prefixed"] == "1. one\n2. two\n3. three", nm
    assert nm["stripped"] == "one\ntwo\nthree", nm
    assert results["numberedStrip"]["value"] == "a\nb", results["numberedStrip"]
    q = results["quote"]
    assert q["prefixed"] == "> q1\n> q2", q
    assert q["stripped"] == "q1\nq2", q

    # -- link: caret inserts with the URL selected; a URL selection becomes
    #    the target with the text placeholder selected; a text selection
    #    becomes the text; the unwrap restores the text
    lc = results["linkCaret"]
    assert lc["value"] == "[link text](url)", lc
    assert lc["urlSelected"] is True, "the caret lands in the parens (url selected)"
    lu = results["linkUrl"]
    assert lu["value"] == "see [link text](https://x.dev/y) now", lu
    assert lu["textSelected"] is True, lu
    lt = results["linkText"]
    assert lt["value"] == "see [REQ-001](url) now", lt
    assert lt["urlSelected"] is True, lt
    unw = results["linkUnwrap"]
    assert unw["value"] == "go see REQ end", unw
    assert unw["text"] == "see REQ", unw

    # -- table / HR: block inserts keep blank-line padding, fences balanced
    tb = results["table"]
    assert tb["padded"] is True, tb
    assert tb["aSelected"] is True, "the first header cell is selected (forum convention)"
    assert tb["fences"] == 0
    assert tb["execs"] == 1
    assert results["hrBeforeKey"]["blankSeparated"] is True, results["hrBeforeKey"]
    fb = results["blockAfterFence"]
    assert fb["fenceKept"] is True, fb
    assert fb["tableAfter"] is True, "a block insert with the caret inside a fence lands AFTER it"
    assert fb["fences"] == 2, "the fence count is unchanged: inserts keep fences balanced"

    # -- the UTF-16 trap: the emoji is 2 code units, every offset must agree
    aw = results["astralWrap"]
    assert aw["ok"] is True, (aw["value"], aw["want"])
    assert aw["sel"] == "hello", aw

    # -- textarea semantics: only \n line endings
    assert results["crlfFree"]["noCR"] is True, results["crlfFree"]

    # -- Case A: one insertText, draft committed through the input listener
    ca = results["caseA"]
    assert ca["inserts"] == 1, ca
    assert ca["value"] == "**abc**" and ca["draft"] == "**abc**", ca

    # -- Case B: splice + exactly one synthetic input (draft AND panel see
    #    it), the shared session key is set, the bar says undo may take
    #    more than one step, and the flag is honored next time (no second
    #    execCommand attempt)
    cb = results["caseB"]
    assert cb["first"]["value"] == "**hi** there", cb
    assert cb["first"]["sel"] == "hi", cb
    assert cb["first"]["execTried"] == 1, "the first op tries Case A once and records the failure"
    assert cb["first"]["inputs"] == 1, "Case B dispatches exactly one synthetic input"
    assert cb["first"]["draft"] == "**hi** there", "the draft commits through the synthetic input"
    assert cb["first"]["flag"] == "on", "the shared fallback key (live-calc's) is set"
    assert cb["first"]["note"] is True, "the bar states the undo limitation (§B)"
    assert cb["second"]["execTried"] == 0, "with the session flag set, execCommand is not retried"
    assert cb["second"]["value"] == "**hi** *there*", cb["second"]
    assert cb["second"]["inputs"] == 2, "each Case B op dispatches exactly one input"
    assert results["caseBSession"]["noteShown"] is True, "a bar born into a fallen-back session says so"

    # -- the save window: a click and a shortcut land on nothing (§A: a
    #    mid-save insertion is destroyed by clearDraft + the post-save
    #    re-render -- the bar is inert for exactly that mechanical reason)
    sg = results["savingGate"]
    assert sg["unchanged"] is True, sg
    assert sg["selUnchanged"] is True, sg
    assert sg["execs"] == 0, "no mutation attempt at all mid-save"
    assert sg["posts"] == 1, "the gate does not mint a second save"

    # -- shortcuts: exactly the §B bindings; nothing the browser reserves
    sc = results["shortcuts"]
    assert sc["boundOps"] == sorted(["bold", "italic", "link", "strike", "code"]), sc["boundOps"]
    assert sc["ctrlB"] == ["bold"] and sc["metaB"] == ["bold"], sc
    assert sc["ctrlI"] == ["italic"], "Ctrl+I is bound (Jared's decision, §H-3)"
    assert sc["ctrlK"] == ["link"], sc
    assert sc["ctrlAltC"] == ["code"], sc
    assert sc["altShift5"] == ["strike"], sc
    for reserved in ("ctrlShiftI", "ctrlShiftI2", "ctrlZ", "ctrlY", "ctrlT",
                     "ctrlDigit", "ctrlAltT", "bareB", "tab"):
        assert sc[reserved] == [], f"{reserved} must not be bound: the browser reserves it"

    kf = results["keydownFires"]
    assert kf["value"] == "**key** body", kf
    assert kf["prevented"] is True, "a matched shortcut preventDefaults"
    assert kf["draft"] == "**key** body", "the shortcut commits through the ordinary input path"

    assert results["keydownTakeover"]["count"] == 1, (
        "the keydown handler stacked across a re-render: shortcuts would fire twice"
    )

    a = results["a11y"]
    assert a["count"] == 11 and all(a["ops"]), a
    assert a["allButtons"] is True and a["allTyped"] is True, "real <button type=button>"
    assert a["allLabeled"] is True, "every button carries a non-empty aria-label"
    assert a["barCls"] is True
    assert a["mousedownPrevented"] is True, "focus and selection stay in the textarea on mouse"

    ro = results["readOnly"]
    assert ro["control"] is True and ro["noBar"] is True, "read-only mounts nothing (§B)"

    m = results["mount"]
    assert m["hasBar"] and m["hasArea"], m
    assert m["barBeforeArea"] is True, "the bar precedes the textarea in DOM order (tab-reachable)"
    assert m["keydownOnArea"] is True, m

    img = results["imageInsert"]
    assert img["value"] == img["want"], img
    assert img["execs"] == 1, "insertIntoBody runs through the shared mutator (Case A)"
    assert img["draft"] == img["want"], "the insert fires the input path: the latent panel gap is fixed"

    live = results["liveCalcFeeds"]
    assert live["openFired"] is True, live
    assert live["recomputed"] is True, "a bar insertion feeds the panel's normal debounced input path"
    assert live["sentText"] == "**bold text**Rail `Vout := 2 V`", live

    mu = results["mutator"]
    assert mu["result"] is True and mu["value"] == "CHANGEme", mu
    assert mu["sel"] == [0, 6] and mu["focused"] is True, mu
