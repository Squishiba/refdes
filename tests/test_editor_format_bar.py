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
  caret-inside toggle-unwrap, selected-inner toggle-unwrap, marker-inclusive
  toggle-unwrap (run-marker guards keep italic from stripping one star out of
  ``**bold**`` and bold from matching a lone ``*``), heading cycle through
  H6->none, multi-line list / numbered / quote prefix and strip, link
  URL-vs-text split + unwrap, the table skeleton with the first header cell
  selected, the HR as its own blank-line-padded paragraph, a block insert with
  the caret inside a calc fence lands AFTER the fence, fences balanced after
  every block op.
- caret placement and the UTF-16 trap: an astral (emoji) character before
  the selection must not shift a wrap (``#388``'s exact bug class).
- Case A: execCommand called exactly once per insertion, selection restored.
  Case B: splice, exactly one synthetic input, fallback key set and honored
  (the next op skips execCommand), the bar's one-line note shows.
- the isSaving() gate: a click and a shortcut mid-save mutate nothing.
- shortcuts: the SHORTCUTS array walks to exactly the slice 1 bindings
  (Ctrl/Cmd+B/I/K, Alt+Shift+5); nothing browser-reserved
  (Ctrl+Z, Ctrl+Shift+I, Ctrl+T, Ctrl digits, Ctrl/Cmd+Alt letters, bare
  letters) matches; a bound keydown fires the op and preventDefaults.
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
const hasSurrogatePair = (value) => value.length !== [...value].length;

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
  removeItem: (k) => { localStore.delete(k); },
};

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
    this.style = {
      _props: {},
      setProperty(name, value) { this._props[name] = String(value); },
      getPropertyValue(name) { return this._props[name] || ''; },
    };
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
  ed.click('italic'); // the selected placeholder receives the italic markers
  results.italicAfterBold = {
    value: ed.area.value,
    sel: [ed.area.selectionStart, ed.area.selectionEnd],
    inner: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-ITALICPLACE';
  const ed = openEditor(h, '');
  ed.select(0, 0);
  ed.click('italic');
  const s = ed.area.value.indexOf('italic text');
  results.italicPlaceholder = {
    value: ed.area.value,
    placeholderSelected: ed.area.selectionStart === s
      && ed.area.selectionEnd === s + 'italic text'.length,
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-STRIKEPLACE';
  const ed = openEditor(h, '');
  ed.select(0, 0);
  ed.click('strike');
  const s = ed.area.value.indexOf('text');
  results.strikePlaceholder = {
    value: ed.area.value,
    placeholderSelected: ed.area.selectionStart === s
      && ed.area.selectionEnd === s + 'text'.length,
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-CODEPLACE';
  const ed = openEditor(h, '');
  ed.select(0, 0);
  ed.click('code');
  const s = ed.area.value.indexOf('code');
  results.codePlaceholder = {
    value: ed.area.value,
    placeholderSelected: ed.area.selectionStart === s
      && ed.area.selectionEnd === s + 'code'.length,
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-ITALICUNWRAP';
  const ed = openEditor(h, 'go *ital* end');
  ed.select(5, 5);
  ed.click('italic');
  results.italicUnwrap = {
    value: ed.area.value,
    inner: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-STRIKEUNWRAP';
  const ed = openEditor(h, 'go ~~strike~~ end');
  ed.select(5, 5);
  ed.click('strike');
  results.strikeUnwrap = {
    value: ed.area.value,
    inner: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-CODEUNWRAP';
  const ed = openEditor(h, 'go `code` end');
  ed.select(4, 4);
  ed.click('code');
  results.codeUnwrap = {
    value: ed.area.value,
    inner: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
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
  const h = 'FB-SELUNWRAP';
  const ed = openEditor(h, 'ab');
  ed.select(1, 1);
  ed.click('bold');
  const placeholder = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  ed.click('bold');
  results.selectedBoldUnwrap = {
    placeholder,
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-WORD';
  const ed = openEditor(h, 'a **bold** b');
  ed.select(4, 8);
  ed.click('bold');
  results.boldWordUnwrap = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-INCLMARKERS';
  const ed = openEditor(h, 'a **bold** b');
  ed.select(2, 10);
  ed.click('bold');
  results.boldMarkersUnwrap = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-TRIPLEBOLD';
  const ed = openEditor(h, '***x***');
  ed.select(0, 7);
  ed.click('bold');
  results.tripleBold = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-TRIPLEITALIC';
  const ed = openEditor(h, '***x***');
  ed.select(0, 7);
  ed.click('italic');
  results.tripleItalic = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-ITALICBOLDSEL';
  const ed = openEditor(h, 'a **bold** b');
  ed.select(2, 10);
  ed.click('italic');
  results.italicBoldMarkersWrap = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-BOLDITALICSEL';
  const ed = openEditor(h, 'a *ital* b');
  ed.select(2, 8);
  ed.click('bold');
  results.boldItalicMarkersWrap = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-MARKERSACROSSLINE';
  const ed = openEditor(h, '**a\nb**');
  ed.select(0, 7);
  ed.click('bold');
  results.markersAcrossLine = {
    value: ed.area.value,
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'FB-ASTRALPAIR';
  const body = '\u{1F600} **bold** x';
  const ed = openEditor(h, body);
  ed.select(body.indexOf('bold'), body.indexOf('bold') + 4);
  ed.click('bold');
  results.astralPairUnwrap = {
    value: ed.area.value,
    want: '\u{1F600} bold x',
    surrogatePair: hasSurrogatePair(ed.area.value),
    selected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
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
  results.codeAtCaret = {
    value: ed.area.value,
    placeholderSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'code',
  };
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
{
  const cases = {
    heading: ['alpha\nbeta', '# alpha\nbeta'],
    list: ['alpha\nbeta', '- alpha\nbeta'],
    numbered: ['alpha\nbeta', '1. alpha\nbeta'],
    quote: ['alpha\nbeta', '> alpha\nbeta'],
  };
  const blankCases = {
    heading: ['\nbeta', '# \nbeta'],
    list: ['\nbeta', '- \nbeta'],
    numbered: ['\nbeta', '1. \nbeta'],
    quote: ['\nbeta', '> \nbeta'],
  };
  for (const [op, [body, want]] of Object.entries(cases)) {
    const h = `FB-LEADING-${op}`;
    const ed = openEditor(h, body);
    ed.select(0, 0);
    ed.click(op);
    results[`lineOpAtCaret0-${op}`] = { value: ed.area.value, want };
    drafts.clearDraft(h);
  }
  for (const [op, [body, want]] of Object.entries(blankCases)) {
    const h = `FB-BLANK-${op}`;
    const ed = openEditor(h, body);
    ed.select(0, 0);
    ed.click(op);
    results[`blankLineOpAtCaret0-${op}`] = { value: ed.area.value, want };
    drafts.clearDraft(h);
  }
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
{
  const cases = [
    ['wikiRefUrl', '[[REF]](url)', 9, '[[REF]](u[link text](url)rl)', true, true],
    ['nestedLink', '[a [b] c](url)', 11, 'a [b] c', false, false],
    ['plainLink', '[x](url)', 5, 'x', false, false],
  ];
  for (const [name, body, caret, want, wikiKept, inserted] of cases) {
    const h = `FB-LINK-${name}`;
    const ed = openEditor(h, body);
    ed.select(caret, caret);
    ed.click('link');
    results[`linkRange-${name}`] = {
      value: ed.area.value,
      want,
      wikiKept: ed.area.value.includes('[[REF]]'),
      inserted: ed.area.value.includes('[link text](url)'),
      expectedWikiKept: wikiKept,
      expectedInserted: inserted,
    };
    drafts.clearDraft(h);
  }
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
    fences: (ed.area.value.match(/^```/gm) || []).length,
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
  const body = '\u{1F600} hello world';
  const ed = openEditor(h, body);
  ed.select(body.indexOf('hello'), body.indexOf('hello') + 5);
  ed.click('bold');
  results.astralWrap = {
    value: ed.area.value,
    want: '\u{1F600} **hello** world',
    ok: ed.area.value === '\u{1F600} **hello** world',
    surrogatePair: hasSurrogatePair(ed.area.value),
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
  const draft0 = drafts.getDraft(h).body;
  ed.click('bold');
  ed.area.dispatch('keydown', { key: 'b', code: 'KeyB', ctrlKey: true });
  results.savingGate = {
    value: ed.area.value,
    unchanged: ed.area.value === 'body x!',
    selUnchanged: ed.area.selectionStart === sel0[0] && ed.area.selectionEnd === sel0[1],
    draft: drafts.getDraft(h).body,
    draftUnchanged: drafts.getDraft(h).body === draft0,
    execs: execCalls.length - n0,
    posts: editPosts.length,
  };
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
    ctrlAltB: fired({ ctrlKey: true, altKey: true, key: 'b' }),
    ctrlAltI: fired({ ctrlKey: true, altKey: true, key: 'i' }),
    ctrlAltK: fired({ ctrlKey: true, altKey: true, key: 'k' }),
    ctrlAltDigit: fired({ ctrlKey: true, altKey: true, key: '1' }),
    metaAltC: fired({ metaKey: true, altKey: true, key: 'c' }),
    ctrlAltShiftC: fired({ ctrlKey: true, altKey: true, shiftKey: true, key: 'c' }),
    altShift5: fired({ altKey: true, shiftKey: true, code: 'Digit5', key: '%' }),
    ctrlAltShift5: fired({ ctrlKey: true, altKey: true, shiftKey: true, code: 'Digit5' }),
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

// ---------- the image picker's insertIntoBody is inert mid-save
{
  const h = 'FB-IMGS';
  const ed = openEditor(h, 'body');
  ed.editor.node.appendChild(ed.editor.imagePicker);
  await tick(20);
  ed.area.value = 'body!';
  ed.area.dispatch('input');
  const save = find(ed.editor.node, 'save');
  save.disabled = false;
  save.click();
  await tick(5);
  const n0 = execCalls.length;
  const posts0 = editPosts.length;
  const d0 = drafts.getDraft(h).body;
  ed.select(5, 5);
  const sel0 = [ed.area.selectionStart, ed.area.selectionEnd];
  const add = find(ed.editor.node, 'image-insert');
  add.click();
  results.imageSavingGate = {
    value: ed.area.value,
    unchanged: ed.area.value === 'body!',
    selUnchanged: ed.area.selectionStart === sel0[0] && ed.area.selectionEnd === sel0[1],
    draft: drafts.getDraft(h).body,
    draftUnchanged: drafts.getDraft(h).body === d0,
    execs: execCalls.filter((_, i) => i >= n0 && execCalls[i] === 'insertText').length,
    newPosts: editPosts.length - posts0,
  };
  await settleEdit({ revision: 'rev-1' });
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
    results = _node_json(tmp_path, HARNESS)

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

    iab = results["italicAfterBold"]
    assert iab["value"] == "***bold text***", iab
    assert iab["inner"] == "bold text", iab

    for name, value, text in (
        ("italicPlaceholder", "*italic text*", "italic text"),
        ("strikePlaceholder", "~~text~~", "text"),
        ("codePlaceholder", "`code`", "code"),
    ):
        result = results[name]
        assert result["value"] == value, result
        assert result["placeholderSelected"] is True, result

    for name, value, text in (
        ("italicUnwrap", "go ital end", "ital"),
        ("strikeUnwrap", "go strike end", "strike"),
        ("codeUnwrap", "go code end", "code"),
    ):
        result = results[name]
        assert result["value"] == value, result
        assert result["inner"] == text, result

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

    su = results["selectedBoldUnwrap"]
    assert su["placeholder"]["value"] == "a**bold text**b", su
    assert su["placeholder"]["selected"] == "bold text", su
    assert su["value"] == "abold textb", su
    assert su["selected"] == "bold text", su

    bwu = results["boldWordUnwrap"]
    assert bwu["value"] == "a bold b", bwu
    assert bwu["selected"] == "bold", bwu

    imu = results["boldMarkersUnwrap"]
    assert imu["value"] == "a bold b", imu
    assert imu["selected"] == "bold", imu

    tb = results["tripleBold"]
    assert tb["value"] == "*x*", tb
    assert tb["selected"] == "*x*", tb

    ti = results["tripleItalic"]
    assert ti["value"] == "**x**", ti
    assert ti["selected"] == "**x**", ti

    ibm = results["italicBoldMarkersWrap"]
    assert ibm["value"] == "a ***bold*** b", ibm
    assert ibm["selected"] == "**bold**", ibm

    bim = results["boldItalicMarkersWrap"]
    assert bim["value"] == "a ***ital*** b", bim
    assert bim["selected"] == "*ital*", bim

    mal = results["markersAcrossLine"]
    assert mal["value"] == "****a\nb****", mal
    assert mal["selected"] == "**a\nb**", mal

    ap = results["astralPairUnwrap"]
    assert ap["surrogatePair"] is True, ap
    assert ap["value"] == ap["want"], ap
    assert ap["selected"] == "bold", ap

    sw = results["strikeWrap"]
    assert sw["value"] == "a ~~b~~", sw
    assert sw["sel"] == [4, 5], sw
    cw = results["codeWrap"]
    assert cw["value"] == "`x = 1` is 4 V", cw
    assert cw["sel"] == [1, 6], cw
    cac = results["codeAtCaret"]
    assert cac["value"] == "`code``x = 1` is 4 V", cac
    assert cac["placeholderSelected"] is True, cac

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
    for name in ("wikiRefUrl", "nestedLink", "plainLink"):
        lr = results[f"linkRange-{name}"]
        assert lr["value"] == lr["want"], (name, lr)
        assert lr["wikiKept"] is lr["expectedWikiKept"], (name, lr)
        assert lr["inserted"] is lr["expectedInserted"], (name, lr)
    for op in ("heading", "list", "numbered", "quote"):
        caret0 = results[f"lineOpAtCaret0-{op}"]
        assert caret0["value"] == caret0["want"], (op, caret0)
        blank = results[f"blankLineOpAtCaret0-{op}"]
        assert blank["value"] == blank["want"], (op, blank)

    # -- table / HR: block inserts keep blank-line padding, fences balanced
    tb = results["table"]
    assert tb["padded"] is True, tb
    assert tb["aSelected"] is True, "the first header cell is selected (forum convention)"
    assert tb["fences"] == 0
    assert tb["execs"] == 1
    assert results["hrBeforeKey"]["blankSeparated"] is True, results["hrBeforeKey"]
    assert results["hrBeforeKey"]["fences"] == 0, results["hrBeforeKey"]
    fb = results["blockAfterFence"]
    assert fb["fenceKept"] is True, fb
    assert fb["tableAfter"] is True, "a block insert with the caret inside a fence lands AFTER it"
    assert fb["fences"] == 2, "the fence count is unchanged: inserts keep fences balanced"

    # -- the UTF-16 trap: the emoji is 2 code units, every offset must agree
    aw = results["astralWrap"]
    assert aw["surrogatePair"] is True, aw
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
    assert sg["draft"] == "body x!", sg
    assert sg["draftUnchanged"] is True, sg
    assert sg["execs"] == 0, "no mutation attempt at all mid-save"
    assert sg["posts"] == 1, "the gate does not mint a second save"

    isg = results["imageSavingGate"]
    assert isg["unchanged"] is True, isg
    assert isg["selUnchanged"] is True, isg
    assert isg["draft"] == "body!", isg
    assert isg["draftUnchanged"] is True, isg
    assert isg["execs"] == 0, isg
    assert isg["newPosts"] == 0, isg

    # -- shortcuts: exactly the §B bindings; nothing the browser reserves
    sc = results["shortcuts"]
    assert sc["boundOps"] == sorted(["bold", "italic", "link", "strike"]), sc["boundOps"]
    assert sc["ctrlB"] == ["bold"] and sc["metaB"] == ["bold"], sc
    assert sc["ctrlI"] == ["italic"], "Ctrl+I is bound (Jared's decision, §H-3)"
    assert sc["ctrlK"] == ["link"], sc
    for unbound in ("ctrlAltC", "ctrlAltB", "ctrlAltI", "ctrlAltK", "ctrlAltDigit",
                    "metaAltC", "ctrlAltShiftC"):
        assert sc[unbound] == [], f"{unbound} must not be bound: Ctrl/Cmd+Alt bindings collide"
    assert sc["altShift5"] == ["strike"], sc
    for reserved in ("ctrlShiftI", "ctrlShiftI2", "ctrlZ", "ctrlY", "ctrlT",
                     "ctrlDigit", "ctrlAltT", "ctrlAltShift5", "bareB", "tab"):
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

def _decoded(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _node_json(tmp_path, harness_source, timeout=NODE_TIMEOUT_S):
    script = harness_source.replace(
        "__STATIC__", json.dumps(STATIC.replace(os.sep, "/"))
    )
    harness = tmp_path / "formatbar-node-harness.mjs"
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
            "format bar node harness hung: "
            f"exit={exc.returncode}\nstdout:\n{_decoded(exc.stdout)}\n"
            f"stderr:\n{_decoded(exc.stderr)}"
        )
    assert proc.returncode == 0, (
        f"format bar node harness failed:\n{proc.stdout}\n{proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


MARKER_TIMEOUT_S = 20
FENCE_TIMEOUT_S = 20
SWEEP_TIMEOUT_S = 300

MARKER_HARNESS = r'''
globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};

class Area {
  constructor() {
    this.value = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
  }
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  focus() { globalThis.document.activeElement = this; }
}

let execCount = 0;
globalThis.document = {
  activeElement: null,
  execCommand(name, ui, text) {
    if (name !== 'insertText') return false;
    execCount += 1;
    const a = globalThis.document.activeElement;
    const start = Math.min(a.selectionStart, a.value.length);
    const end = Math.max(start, Math.min(a.selectionEnd, a.value.length));
    a.value = a.value.slice(0, start) + text + a.value.slice(end);
    a.selectionStart = a.selectionEnd = start + text.length;
    return true;
  },
};

const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;
const { OPS } = await import(url('formatbar.js'));
const area = new Area();

const cases = [
  { text: '*', op: 'italic', start: 0, end: 1, wantFirst: '', wantSecond: '*italic text*' },
  { text: '**', op: 'bold', start: 0, end: 2, wantFirst: '', wantSecond: '**bold text**' },
  { text: '~~', op: 'strike', start: 0, end: 2, wantFirst: '', wantSecond: '~~text~~' },
  { text: '`', op: 'code', start: 0, end: 1, wantFirst: '', wantSecond: '`code`' },
  { text: '***', op: 'italic', start: 0, end: 3, wantFirst: '*', wantSecond: '' },
  { text: '***', op: 'bold', start: 0, end: 3, wantFirst: '*', wantSecond: '*****' },
  { text: '**', op: 'italic', start: 0, end: 2, wantFirst: '****', wantSecond: '**' },
  { text: '*', op: 'bold', start: 0, end: 1, wantFirst: '*****', wantSecond: '*' },
  { text: '~~~', op: 'strike', start: 0, end: 3, wantFirst: '', wantSecond: '~~text~~' },
  { text: '``', op: 'code', start: 0, end: 2, wantFirst: '````', wantSecond: '``' },
  { text: '**', op: 'italic', start: 0, end: 1, wantFirst: '*', wantSecond: '*italic text**' },
  { text: '**', op: 'italic', start: 1, end: 2, wantFirst: '*', wantSecond: '**italic text*' },
  { text: '***', op: 'bold', start: 1, end: 3, wantFirst: '*', wantSecond: '***bold text**' },
  { text: '***', op: 'italic', start: 0, end: 2, wantFirst: '*****', wantSecond: '*******' },
  { text: '~~~', op: 'strike', start: 1, end: 3, wantFirst: '~', wantSecond: '~~~text~~' },
  { text: '``', op: 'code', start: 0, end: 1, wantFirst: '`', wantSecond: '`code``' },
];

const out = [];
for (const c of cases) {
  area.value = c.text;
  area.selectionStart = c.start;
  area.selectionEnd = c.end;
  execCount = 0;
  OPS[c.op](area, {});
  const first = area.value;
  const sel = [area.selectionStart, area.selectionEnd];
  const inBounds = Number.isInteger(sel[0]) && sel[0] >= 0 && sel[0] <= first.length
    && Number.isInteger(sel[1]) && sel[1] >= sel[0] && sel[1] <= first.length;
  const firstExecs = execCount;
  OPS[c.op](area, {});
  out.push({
    text: c.text, op: c.op, start: c.start, end: c.end,
    first, sel, second: area.value, execs: firstExecs, inBounds,
    wantFirst: c.wantFirst, wantSecond: c.wantSecond,
  });
}
console.log(JSON.stringify(out));
'''

FENCE_HARNESS = r'''
globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};

class Area {
  constructor() {
    this.value = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
  }
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  focus() { globalThis.document.activeElement = this; }
}

let execCount = 0;
globalThis.document = {
  activeElement: null,
  execCommand(name, ui, text) {
    if (name !== 'insertText') return false;
    execCount += 1;
    const a = globalThis.document.activeElement;
    const start = Math.min(a.selectionStart, a.value.length);
    const end = Math.max(start, Math.min(a.selectionEnd, a.value.length));
    a.value = a.value.slice(0, start) + text + a.value.slice(end);
    a.selectionStart = a.selectionEnd = start + text.length;
    return true;
  },
};

const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;
const { OPS } = await import(url('formatbar.js'));
const area = new Area();

function lineEndBeforeAfter(text) {
  return text.lastIndexOf('\n', text.indexOf('after') - 1);
}

const t1 = 'before\n```python\nx\n```\nafter';
const end1 = lineEndBeforeAfter(t1);
const t2 = 'before\n```\nx\n```\nafter';
const end2 = lineEndBeforeAfter(t2);
const t3 = 'before\n~~~\nx\n~~~\nafter';
const end3 = lineEndBeforeAfter(t3);
const t4 = 'before\n````\n```\ninner\n```\n````\nafter';
const end4 = lineEndBeforeAfter(t4);
const t5 = 'before\n> ```\n> x\n> ```\nafter';
const end5 = lineEndBeforeAfter(t5);
const close5 = t5.indexOf('> ```', t5.indexOf('x') + 1);
const t6 = 'before\n```\nx\nafter';

const cases = [
  { name: 'backtick info opener line', text: t1, caret: t1.indexOf('python'), fenceEnd: end1, want: 'afterFence' },
  { name: 'backtick plain opener line', text: t2, caret: t2.indexOf('```'), fenceEnd: end2, want: 'afterFence' },
  { name: 'backtick content line', text: t1, caret: t1.indexOf('x'), fenceEnd: end1, want: 'afterFence' },
  { name: 'backtick closing line', text: t1, caret: t1.lastIndexOf('```', end1) + 1, fenceEnd: end1, want: 'afterFence' },
  { name: 'tilde opener line', text: t3, caret: t3.indexOf('~~~'), fenceEnd: end3, want: 'afterFence' },
  { name: 'tilde content line', text: t3, caret: t3.indexOf('x'), fenceEnd: end3, want: 'afterFence' },
  { name: 'tilde closing line', text: t3, caret: t3.lastIndexOf('~~~', end3) + 1, fenceEnd: end3, want: 'afterFence' },
  { name: 'nested fence content line', text: t4, caret: t4.indexOf('inner'), fenceEnd: end4, want: 'afterFence' },
  { name: 'blockquoted opener line', text: t5, caret: t5.indexOf('> ```') + 2, fenceEnd: end5, want: 'afterFence' },
  { name: 'blockquoted content line', text: t5, caret: t5.indexOf('x'), fenceEnd: end5, want: 'afterFence' },
  { name: 'blockquoted closing line', text: t5, caret: close5 + 2, fenceEnd: end5, want: 'afterFence' },
  { name: 'unclosed fence content line', text: t6, caret: t6.indexOf('x'), want: 'end' },
  { name: 'caret before fence', text: t1, caret: 0, want: 'beforeFence' },
];

function fenceCount(text) {
  let count = 0;
  for (const raw of text.split('\n')) {
    const line = raw.replace(/^[ \t]*(?:>[ \t]?)+/, '');
    if (/^[ \t]{0,3}(?:`{3,}|~{3,})/.test(line)) count += 1;
  }
  return count;
}

const out = [];
for (const c of cases) {
  const originalFences = fenceCount(c.text);
  area.value = c.text;
  area.selectionStart = c.caret;
  area.selectionEnd = c.caret;
  execCount = 0;
  OPS.table(area, {});
  const result = area.value;
  const inserted = result.indexOf('| a | b |');
  out.push({
    name: c.name,
    inserted,
    fenceEnd: c.fenceEnd === undefined ? null : c.fenceEnd,
    textLength: c.text.length,
    fenceCount: fenceCount(result),
    originalFences,
    execs: execCount,
    want: c.want,
  });
}
console.log(JSON.stringify(out));
'''

SWEEP_HARNESS = r'''
globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};

class Area {
  constructor() {
    this.value = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
  }
  setSelectionRange(a, b) {
    this.selectionStart = a;
    this.selectionEnd = b;
  }
  focus() { globalThis.document.activeElement = this; }
}

let execCount = 0;
globalThis.document = {
  activeElement: null,
  execCommand(name, ui, text) {
    if (name !== 'insertText') return false;
    execCount += 1;
    const a = globalThis.document.activeElement;
    const start = Math.min(a.selectionStart, a.value.length);
    const end = Math.max(start, Math.min(a.selectionEnd, a.value.length));
    a.value = a.value.slice(0, start) + text + a.value.slice(end);
    a.selectionStart = a.selectionEnd = start + text.length;
    return true;
  },
};

const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;
const { OPS } = await import(url('formatbar.js'));

const chars = ['*', '~', '`', 'a', ' ', '\n', '\u{1F600}'];
const strings = [];
function build(prefix, codePoints) {
  strings.push(prefix);
  if (codePoints === 6) return;
  for (const c of chars) build(prefix + c, codePoints + 1);
}
build('', 0);

const inlineOps = ['bold', 'italic', 'strike', 'code'];
const blockOps = ['heading', 'list', 'numbered', 'quote', 'link', 'table', 'hr'];
const allOps = [...inlineOps, ...blockOps];
const markerFor = {
  bold: '*', italic: '*', strike: '~', code: '`',
};

function codePointBoundary(text, pos) {
  if (pos <= 0 || pos >= text.length) return pos;
  const prev = text.charCodeAt(pos - 1);
  const next = text.charCodeAt(pos);
  if (prev >= 0xD800 && prev <= 0xDBFF && next >= 0xDC00 && next <= 0xDFFF) return pos - 1;
  return pos;
}

function leadingRun(text, marker) {
  let length = 0;
  while (length + marker.length <= text.length
    && text.startsWith(marker, length)) length += marker.length;
  return length;
}

function trailingRun(text, marker) {
  let length = 0;
  while (text.length - length - marker.length >= 0
    && text.startsWith(marker, text.length - length - marker.length)) {
    length += marker.length;
  }
  return length;
}

function runEndingAt(text, pos, marker) {
  let length = 0;
  while (pos - length - marker.length >= 0
    && text.startsWith(marker, pos - length - marker.length)) {
    length += marker.length;
  }
  return length;
}

function runStartingAt(text, pos, marker) {
  let length = 0;
  while (pos + length + marker.length <= text.length
    && text.startsWith(marker, pos + length)) {
    length += marker.length;
  }
  return length;
}

function hasLayer(op, length, layer) {
  if (op === 'bold') return length >= 2;
  if (op === 'italic') return length > 0 && length % 2 === 1;
  return length === layer;
}

function allMarker(text, start, end, marker) {
  if (start >= end) return false;
  for (let i = start; i < end; i += 1) if (text[i] !== marker) return false;
  return true;
}

function isWellFormedInline(text, start, end, op) {
  if (start >= end) return false;
  if (codePointBoundary(text, start) !== start || codePointBoundary(text, end) !== end) {
    return false;
  }
  const marker = markerFor[op];
  const layer = marker.length;
  const chosen = text.slice(start, end);
  if (chosen.includes('\n') || allMarker(text, start, end, marker)) return false;
  const leading = leadingRun(chosen, marker);
  const trailing = trailingRun(chosen, marker);
  const left = runEndingAt(text, start, marker);
  const right = runStartingAt(text, end, marker);
  const leadingExact = leading === layer && trailing === layer
    && leading + trailing <= chosen.length
    && left === 0 && right === 0;
  const surroundingExact = leading === 0 && trailing === 0
    && left === layer && right === layer;
  const plain = leading === 0 && trailing === 0 && left === 0 && right === 0;
  return leadingExact || surroundingExact || plain;
}

function clampPos(value, length) {
  return Math.max(0, Math.min(length, value));
}

function snapSelection(text, start, end) {
  const length = text.length;
  const s = codePointBoundary(text, clampPos(start, length));
  const e = Math.max(s, codePointBoundary(text, clampPos(end, length)));
  return [s, e];
}

function lineRangeLocal(text, caret) {
  const start = caret === 0 ? 0 : text.lastIndexOf('\n', caret - 1) + 1;
  const end = text.indexOf('\n', start);
  return [start, end === -1 ? text.length : end];
}

function expandedLineRangeLocal(text, start, end) {
  const [lineStart] = lineRangeLocal(text, start);
  const probe = end > start ? end - 1 : start;
  const [, lineEnd] = lineRangeLocal(text, probe);
  return [lineStart, lineEnd];
}

function isSpaceAt(line, i) {
  return line[i] === ' ' || line[i] === '\t';
}

function listStripEnd(line) {
  let i = 0;
  while (i < line.length && isSpaceAt(line, i)) i += 1;
  if (i >= line.length) return -1;
  if (line[i] !== '-' && line[i] !== '*' && line[i] !== '+') return -1;
  i += 1;
  if (i >= line.length || !isSpaceAt(line, i)) return -1;
  while (i < line.length && isSpaceAt(line, i)) i += 1;
  return i;
}

function applyLineMarkerExpected(text, start, end, marker, numbered = false, list = false) {
  const [s, e] = snapSelection(text, start, end);
  const [lineStart, lineEnd] = expandedLineRangeLocal(text, s, e);
  const lines = text.slice(lineStart, lineEnd).split('\n');
  const ends = list ? lines.map(listStripEnd) : null;
  const allFormatted = list ? ends.every((endIndex) => endIndex >= 0) : false;
  const replacement = allFormatted
    ? lines.map((line, index) => line.slice(ends[index]))
    : lines.map((line, index) => (numbered ? `${index + 1}. ${line}` : marker + line));
  const joined = replacement.join('\n');
  return {
    value: text.slice(0, lineStart) + joined + text.slice(lineEnd),
    selection: [lineStart, lineStart + joined.length],
  };
}

function applyHeadingExpected(text, caret) {
  const [lineStart, lineEnd] = lineRangeLocal(text, snapSelection(text, caret, caret)[0]);
  const line = text.slice(lineStart, lineEnd);
  const hashes = /^(#{1,6})\s+/.exec(line);
  let replacement;
  let offset;
  if (!hashes) {
    replacement = '# ' + line;
    offset = 1;
  } else if (hashes[1].length < 6) {
    const more = '#'.repeat(hashes[1].length + 1);
    replacement = `${more} ${line.slice(hashes[1].length + 1)}`;
    offset = more.length + 1;
  } else {
    replacement = line.slice(hashes[1].length + 1);
    offset = 0;
  }
  return {
    value: text.slice(0, lineStart) + replacement + text.slice(lineEnd),
    selection: [lineStart + offset, lineStart + offset],
  };
}

function linkRangeExpected(text, caret) {
  const pair = text.lastIndexOf('](', Math.max(0, caret - 1));
  if (pair < 0) return null;
  let depth = 0;
  let open = -1;
  for (let i = pair - 1; i >= 0; i -= 1) {
    if (text[i] === ']') depth += 1;
    else if (text[i] === '[') {
      if (depth === 0) {
        open = i;
        break;
      }
      depth -= 1;
    }
  }
  const close = text.indexOf(')', pair + 2);
  if (open < 0 || close < 0 || depth !== 0) return null;
  if (!(pair < caret && caret <= close)) return null;
  const inner = text.slice(open + 1, pair);
  if (inner.startsWith('[')) return null;
  return {
    start: open,
    end: close + 1,
    replacement: inner,
    selection: [open, open + inner.length],
  };
}

function applyLinkExpected(text, start, end) {
  const [s, e] = snapSelection(text, start, end);
  if (s === e) {
    const off = linkRangeExpected(text, s);
    if (off) {
      return {
        value: text.slice(0, off.start) + off.replacement + text.slice(off.end),
        selection: off.selection,
      };
    }
    return {
      value: text.slice(0, s) + '[link text](url)' + text.slice(e),
      selection: [s + 12, s + 15],
    };
  }
  const chosen = text.slice(s, e);
  return {
    value: text.slice(0, s) + `[${chosen}](url)` + text.slice(e),
    selection: [s + chosen.length + 3, s + chosen.length + 6],
  };
}

function strippedFenceLineExpected(line) {
  const prefix = /^[ \t]*(?:>[ \t]?)+/.exec(line);
  return prefix ? line.slice(prefix[0].length) : line;
}

function fenceCloserExpected(marker) {
  const char = marker[0] === '~' ? '\\~' : '`';
  return new RegExp(`^[ \t]*${char}{${marker.length},}[ \t]*$`);
}

function fenceBlocksExpected(text) {
  const rawLines = text.split('\n');
  const lines = [];
  let pos = 0;
  for (const line of rawLines) {
    lines.push({ start: pos, end: pos + line.length });
    pos += line.length + 1;
  }
  const stripped = rawLines.map(strippedFenceLineExpected);
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const opener = /^[ \t]{0,3}(`{3,}|~{3,})([^\n]*)$/.exec(stripped[i]);
    if (opener && !(opener[1][0] === '`' && opener[2].includes('`'))) {
      const closer = fenceCloserExpected(opener[1]);
      let j = i + 1;
      while (j < lines.length && !closer.test(stripped[j])) j += 1;
      const end = j < lines.length ? lines[j].end : text.length;
      blocks.push({ start: lines[i].start, end, endLine: end });
      if (j < lines.length) {
        i = j + 1;
        continue;
      }
      return blocks;
    }
    i += 1;
  }
  return blocks;
}

function fenceInsertAfterExpected(text, caret) {
  for (const block of fenceBlocksExpected(text)) {
    if (caret >= block.start && caret < block.end) return block.endLine;
  }
  return null;
}

function blockInsertPlanExpected(text, caret, insert) {
  const [from] = snapSelection(text, caret, caret);
  let at = from;
  const afterFence = fenceInsertAfterExpected(text, at);
  if (afterFence !== null) at = afterFence;
  const before = text.slice(0, at);
  const after = text.slice(at);
  const open = before === '' || before.endsWith('\n\n') ? '' : '\n\n';
  const close = after === '' || after.startsWith('\n\n') ? '' : '\n\n';
  const chunk = open + insert + close;
  return {
    value: before + chunk + after,
    selection: [before.length + chunk.length, before.length + chunk.length],
  };
}

function blockExpected(op, text, start, end) {
  if (op === 'heading') return applyHeadingExpected(text, start);
  if (op === 'list') return applyLineMarkerExpected(text, start, end, '- ', false, true);
  if (op === 'numbered') return applyLineMarkerExpected(text, start, end, '1. ', true, false);
  if (op === 'quote') return applyLineMarkerExpected(text, start, end, '> ', false, false);
  if (op === 'link') return applyLinkExpected(text, start, end);
  if (op === 'table') {
    const [caret] = snapSelection(text, start, end);
    const plan = blockInsertPlanExpected(text, caret, '| a | b |\n|---|---|\n|   |   |');
    const textStart = plan.value.indexOf('| a');
    return { value: plan.value, selection: [textStart + 2, textStart + 3] };
  }
  if (op === 'hr') {
    const [caret] = snapSelection(text, start, end);
    return blockInsertPlanExpected(text, caret, '---');
  }
  return null;
}

function isSubsequence(needle, haystack) {
  if (needle === '') return true;
  let from = 0;
  for (const c of needle) {
    const at = haystack.indexOf(c, from);
    if (at < 0) return false;
    from = at + c.length;
  }
  return true;
}

const area = new Area();
const expectedCases = strings.reduce(
  (sum, text) => sum + ((text.length + 1) * (text.length + 2) / 2) * allOps.length,
  0,
);
let cases = 0;
const bad = [];

for (let si = 0; si < strings.length && bad.length === 0; si += 1) {
  const text = strings[si];
  const baseSeq = text.replace(/[*~`]/g, '');
  const len = text.length;
  for (let start = 0; start <= len && bad.length === 0; start += 1) {
    for (let end = start; end <= len && bad.length === 0; end += 1) {
      for (let oi = 0; oi < allOps.length; oi += 1) {
        const op = allOps[oi];
        const isInline = oi < 4;
        cases += 1;
        area.value = text;
        area.selectionStart = start;
        area.selectionEnd = end;
        execCount = 0;
        OPS[op](area, {});
        const first = area.value;
        const s0 = area.selectionStart;
        const e0 = area.selectionEnd;
        let problem = '';
        if (execCount !== 1) problem = `execCount=${execCount}`;
        else if (!Number.isInteger(s0) || s0 < 0 || s0 > first.length
          || !Number.isInteger(e0) || e0 < s0 || e0 > first.length) {
          problem = `selection=[${s0},${e0}] len=${first.length}`;
        } else if (first.includes('\r')) problem = 'contains CR';
        else if (isInline) {
          if (!isSubsequence(baseSeq, first.replace(/[*~`]/g, ''))) {
            problem = 'original non-marker sequence not preserved';
          }
          if (!problem && isWellFormedInline(text, start, end, op)) {
            OPS[op](area, {});
            if (area.value !== text) problem = 'same inline op twice changed the text';
          }
        } else {
          const expected = blockExpected(op, text, start, end);
          if (!expected) {
            problem = 'missing block expectation';
          } else if (first !== expected.value) {
            problem = 'block result not expected';
          } else if (s0 !== expected.selection[0] || e0 !== expected.selection[1]) {
            problem = `block selection=[${s0},${e0}] expected=[${expected.selection}]`;
          }
        }
        if (problem) {
          bad.push({
            text, start, end, op, first, selection: [s0, e0],
            twice: isInline ? area.value : undefined, problem,
          });
          break;
        }
      }
    }
  }
}

console.log(JSON.stringify({ cases, expectedCases, bad }));'''

@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served formatbar module")
def test_the_format_bar_inline_toggles_terminate_on_marker_only_selections(tmp_path):
    cases = _node_json(tmp_path, MARKER_HARNESS, timeout=MARKER_TIMEOUT_S)
    assert len(cases) == 16
    for case in cases:
        assert case["execs"] == 1, case
        assert case["inBounds"] is True, case
        assert case["first"] == case["wantFirst"], case
        assert case["second"] == case["wantSecond"], case


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served formatbar module")
def test_the_format_bar_block_inserts_land_outside_every_fence_shape(tmp_path):
    cases = _node_json(tmp_path, FENCE_HARNESS, timeout=FENCE_TIMEOUT_S)
    assert len(cases) == 13
    for case in cases:
        assert case["execs"] == 1, case
        assert case["inserted"] >= 0, case
        assert case["fenceCount"] == case["originalFences"], case
        if case["want"] == "afterFence":
            assert case["inserted"] == case["fenceEnd"] + 2, case
        elif case["want"] == "end":
            assert case["inserted"] == case["textLength"] + 2, case
        elif case["want"] == "beforeFence":
            assert case["inserted"] == 0, case
        else:
            raise AssertionError(case)


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served formatbar module")
def test_the_format_bar_survives_the_exhaustive_marker_selection_sweep(tmp_path):
    results = _node_json(tmp_path, SWEEP_HARNESS, timeout=SWEEP_TIMEOUT_S)
    assert results["bad"] == [], results["bad"]
    assert results["cases"] == results["expectedCases"]
