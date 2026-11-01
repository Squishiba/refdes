"""The bar's refdes row, driven under node (slice 2, design §C/§H-4/§H-5).

Same posture as ``test_editor_format_bar.py``: no browser, the REAL served
modules -- the real ``editor.js`` wiring (which builds the real
``formatbar.js`` bar and the shared ``pickers.js`` candidate machinery) over
``api.js``, ``drafts.js``, ``live-calc.js``, ``images.js`` and
``sourcepicker.js``, with stubs for DOM / sessionStorage / fetch.

Scenarios, one node process:

- the skeleton buttons insert the §H-4 strings through the shared mutator
  (one execCommand, the draft commits through the ordinary input path) with
  the ``name`` placeholder SELECTED (typing replaces it);
- the calc-fence skeleton is a block insert: blank-line padded, landed AFTER
  the enclosing fence when the caret sits inside one, fences balanced;
- the figure/value skeletons leave the caret INSIDE the brackets with an
  empty selection and wrap a selection (``[[fig:sel]]`` / ``{{sel}}``, sel
  kept selected);
- the astral (emoji) trap: a surrogate pair before the selection must not
  shift an insertion;
- the isSaving() gate: every refdes button no-ops mid-save (value,
  selection, draft, fetches all unchanged; the picker stays closed);
- read-only: an editor whose body is not editable has no bar at all;
- the ``[[ID]]`` picker: opens on click (aria-expanded, focus to the filter,
  fetch ``/api/items?limit=5000``), renders ALL items sorted by display id,
  type-ahead filters by id and title, shows display ids and never an
  ``@key`` composite, caps with the honest notice, shows the failure banner,
  picks at the caret (``[[ID]]``) and over a selection (``[[ID|sel]]``),
  closes on pick, Escape returns focus to the textarea, ArrowDown/Up + Enter
  activate rows;
- Image/Source buttons focus the existing panels below the textarea (the
  bar's own buttons), never mutate the body;
- ``pickers.js`` exports the shared ``PICKER_LIMIT`` (the links.js page
  size), and links.js keeps its behavior through the shared module.
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
  removeItem: (k) => { localStore.delete(k); },
};

// ---------- fake DOM
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
  querySelector(sel) {
    for (const part of sel.split(',')) {
      const found = this.querySelectorAll(part.trim());
      if (found.length) return found[0];
    }
    return null;
  }
  setSelectionRange(s, e) { this.selectionStart = s; this.selectionEnd = e; }
  focus() { globalThis.document.activeElement = this; }
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
let ITEMS = { items: [], total: 0 };
let ITEMS_FAIL = null;
const itemsPaths = [];
const editPosts = [];
let editSettle = null;
globalThis.fetch = async (path, init) => {
  if (path.startsWith('/api/items')) {
    itemsPaths.push(path);
    if (ITEMS_FAIL) {
      return { ok: false, status: 500, statusText: 'boom', json: async () => ({ error: ITEMS_FAIL }) };
    }
    return { ok: true, status: 200, statusText: 'OK', json: async () => ITEMS };
  }
  if (path.includes('/calc')) {
    return { ok: true, status: 200, statusText: 'OK', json: async () => ({ revision: 'rev-0', spans: [] }) };
  }
  if (path.includes('/edit')) {
    editPosts.push(init && init.body ? JSON.parse(init.body) : null);
    return new Promise((resolve) => {
      editSettle = (payload, ok) => resolve(
        { ok, status: ok ? 200 : 422, statusText: 'OK', json: async () => payload });
    });
  }
  if (path.startsWith('/api/images')) {
    return {
      ok: true, status: 200, statusText: 'OK',
      json: async () => ({ images: [{
        name: 'rail.png', rel: 'assets/rail.png', bytes: 1234,
        markdown: '![rail](assets/rail.png)', insertable: true,
      }] }),
    };
  }
  if (path.startsWith('/api/item/')) {
    const h = decodeURIComponent(path.split('/api/item/')[1].split('?')[0]);
    return { ok: true, status: 200, statusText: 'OK', json: async () => itemRender(h) };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) };
};

const { createEditor } = await import(url('editor.js'));
const { SPAN_SKELETON, FENCE_SKELETON, FIGURE_SKELETON, VALUE_SKELETON } =
  await import(url('formatbar.js'));
const pickers = await import(url('pickers.js'));
const drafts = await import(url('drafts.js'));

function editItem(handle, bodyEditable = true) {
  return {
    id: handle,
    revision: 'rev-0',
    edit: {
      editable: true, file_revision: 'rev-0', fields: {},
      body: { editable: bodyEditable }, links: {},
    },
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

function openEditor(handle, body, bodyEditable = true) {
  const editor = createEditor(editItem(handle, bodyEditable), handle, () => {}, () => {});
  const area = editor.bodyControl(body, null);
  globalThis.document.activeElement = area;
  const bar = area && area._refdesFormatBar;
  const op = (name) => findAll(bar, `fmt-${name}`)[0];
  return {
    editor, area, bar,
    click: (name) => op(name).click(),
    button: (name) => op(name),
    select: (s, e) => area.setSelectionRange(s, e === undefined ? s : e),
  };
}

function fenceOpens(value) {
  return (value.match(/```calc/g) || []).length;
}
function fenceMarkers(value) {
  return (value.match(/```/g) || []).length;
}

const results = { fenceBalance: [], astral: hasSurrogateSafe };
function hasSurrogateSafe(value) { return value.length !== [...value].length; }

// ---------- the refdes group and its buttons
{
  const ed = openEditor('RD-A11Y', 'body');
  const group = findAll(ed.bar, 'fmt-refdes');
  const buttons = group.length ? group[0].children : [];
  results.group = {
    count: group.length,
    labels: buttons.map((b) => b.getAttribute('aria-label') || ''),
    classes: buttons.map((b) => b.className),
    typed: buttons.every((b) => b.tagName === 'BUTTON' && b.type === 'button'),
    refAria: (() => {
      const b = findAll(ed.bar, 'fmt-reference')[0];
      return { popup: b.getAttribute('aria-haspopup'), expanded: b.getAttribute('aria-expanded') };
    })(),
    navi: (() => {
      const b = findAll(ed.bar, 'fmt-navi')[0];
      return b ? { text: b.textContent, aria: b.getAttribute('aria-label') } : null;
    })(),
  };
  const mdown = buttons[0].dispatch('mousedown', {});
  results.group.mousedownPrevented = mdown.defaultPrevented === true;
  drafts.clearDraft('RD-A11Y');
}

// ---------- span skeleton: the §H-4 string, name selected
{
  const h = 'RD-SPAN';
  const ed = openEditor(h, 'hello world');
  const n0 = execCalls.length;
  ed.select(0, 5);
  ed.click('span');
  const idx = ed.area.value.indexOf(SPAN_SKELETON);
  results.span = {
    value: ed.area.value,
    skeleton: SPAN_SKELETON,
    sel: [ed.area.selectionStart, ed.area.selectionEnd],
    nameSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'name',
    execs: execCalls.length - n0,
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}

// ---------- navi: keyless marker at the caret, wrap on a selection, refuse
// `--` and newlines (the marker is a one-line HTML comment)
{
  const h = 'RD-NAVI';
  const ed = openEditor(h, 'hello world');
  const n0 = execCalls.length;
  ed.select(0, 0);
  ed.click('navi');
  results.naviCaret = {
    value: ed.area.value,
    selText: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
    execs: execCalls.length - n0,
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}
{
  const h = 'RD-NAVISEL';
  const ed = openEditor(h, 'hello world');
  ed.select(0, 5);
  ed.click('navi');
  results.naviWrap = {
    value: ed.area.value,
    selText: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}
for (const [name, body, from, to] of [
  ['dash', 'use a--b pair', 4, 8],
  ['arrow', 'x --> y', 2, 5],
  ['newline', 'one\ntwo', 0, 7],
]) {
  const h = `RD-NAVI-REF-${name}`;
  const ed = openEditor(h, body);
  ed.select(from, to);
  const v0 = ed.area.value;
  const sel0 = [ed.area.selectionStart, ed.area.selectionEnd];
  const n0 = execCalls.length;
  const d0 = drafts.getDraft(h).body;
  ed.click('navi');
  results[`naviRefuse-${name}`] = {
    value: ed.area.value,
    unchanged: ed.area.value === v0,
    selUnchanged: ed.area.selectionStart === sel0[0] && ed.area.selectionEnd === sel0[1],
    execs: execCalls.length - n0,
    draft: drafts.getDraft(h).body,
    draftUnchanged: drafts.getDraft(h).body === d0,
  };
  drafts.clearDraft(h);
}

// ---------- calc-fence skeleton: block insert, name selected
{
  const h = 'RD-FENCE';
  const ed = openEditor(h, '');
  ed.select(0, 0);
  ed.click('calc');
  const idx = ed.area.value.indexOf(FENCE_SKELETON);
  results.fence = {
    value: ed.area.value,
    at: idx,
    nameSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'name',
    opens: fenceOpens(ed.area.value),
    markers: fenceMarkers(ed.area.value),
    draft: drafts.getDraft(h).body,
  };
  drafts.clearDraft(h);
}
{
  // caret INSIDE a calc fence: the skeleton lands AFTER the fence, balanced
  const h = 'RD-FENCE-IN';
  const ed = openEditor(h, '```calc\nI_total = 5 A\n```\n');
  ed.select(8, 8);
  ed.click('calc');
  results.fenceInside = {
    value: ed.area.value,
    opens: fenceOpens(ed.area.value),
    markers: fenceMarkers(ed.area.value),
    after: ed.area.value.indexOf(FENCE_SKELETON) > ed.area.value.indexOf('I_total'),
    nameSelected: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd) === 'name',
  };
  drafts.clearDraft(h);
}

// ---------- figure / value: caret inside, selection wrapped
{
  const h = 'RD-FIG';
  const ed = openEditor(h, 'hello world');
  ed.select(0, 0);
  ed.click('figure');
  const caretSel = [ed.area.selectionStart, ed.area.selectionEnd];
  const withCaret = ed.area.value;
  ed.area.value = 'hello world';
  ed.select(0, 5);
  ed.click('figure');
  results.figure = {
    withCaret,
    caretSel,
    caretInside: withCaret === FIGURE_SKELETON + 'hello world'
      && caretSel[0] === '[[fig:'.length && caretSel[1] === caretSel[0],
    value: ed.area.value,
    sel: [ed.area.selectionStart, ed.area.selectionEnd],
    selText: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}
{
  const h = 'RD-VAL';
  const ed = openEditor(h, 'hello world');
  ed.select(0, 0);
  ed.click('value');
  const caretSel = [ed.area.selectionStart, ed.area.selectionEnd];
  const withCaret = ed.area.value;
  ed.area.value = 'hello world';
  ed.select(0, 5);
  ed.click('value');
  results.value = {
    withCaret,
    caretInside: withCaret === VALUE_SKELETON + 'hello world'
      && caretSel[0] === 2 && caretSel[1] === 2,
    wrapped: ed.area.value,
    selText: ed.area.value.slice(ed.area.selectionStart, ed.area.selectionEnd),
  };
  drafts.clearDraft(h);
}

// ---------- the astral trap: a surrogate pair before the selection
{
  const h = 'RD-ASTRAL';
  const ed = openEditor(h, '\u{1F44D} hello');
  ed.select(3, 8);
  ed.click('figure');
  results.astral = {
    value: ed.area.value,
    want: '\u{1F44D} [[fig:hello]]',
    ok: ed.area.value === '\u{1F44D} [[fig:hello]]',
  };
  drafts.clearDraft(h);
}

// ---------- the isSaving() gate: every refdes button inert mid-save
{
  const h = 'RD-SAVE';
  const ed = openEditor(h, 'body x');
  ed.area.value = 'body x!';
  ed.area.dispatch('input');
  const save = find(ed.editor.node, 'save');
  save.disabled = false;
  save.click();
  await tick(5);
  const before = ed.area.value;
  for (const name of ['span', 'calc', 'figure', 'value', 'navi', 'reference']) ed.click(name);
  const popover = find(ed.bar, 'fmt-picker');
  results.savingGate = {
    unchanged: ed.area.value === before,
    draftUnchanged: drafts.getDraft(h).body === 'body x!',
    pickerClosed: popover.hidden === true,
  };
  const settle = editSettle;
  editSettle = null;
  if (settle) settle({ revision: 'rev-1' }, true);
  await tick(5);
  drafts.clearDraft(h);
}

// ---------- read-only: no bar at all
{
  const ed = openEditor('RD-RO', 'body', false);
  results.readOnly = { area: ed.area === null, bar: !ed.bar };
}

// ---------- the [[ID]] picker
function setItems(items, total) {
  ITEMS = { items, total: total === undefined ? items.length : total };
}

async function openPicker(ed) {
  ed.click('reference');
  await tick(5);
  return find(ed.bar, 'fmt-picker');
}

{
  const h = 'RD-PICKER';
  setItems([
    { id: 'DEC-002', handle: 'd2', key: 'ffff0002', title: 'Unsettled boot approach.' },
    { id: 'DEC-001', handle: 'd1', key: 'ffff0001', title: 'Use the buck regulator.' },
    { handle: 'IFC-001', key: 'ffff0003', title: 'Imported decision.' },
  ]);
  const ed = openEditor(h, 'cite here');
  const popover = await openPicker(ed);
  const rows = findAll(popover, 'fmt-picker-row');
  const labels = rows.map((r) => r.textContent);
  results.picker = {
    opened: popover.hidden === false,
    expanded: findAll(ed.bar, 'fmt-reference')[0].getAttribute('aria-expanded'),
    fetchPath: itemsPaths[itemsPaths.length - 1],
    limit: pickers.PICKER_LIMIT,
    sorted: labels[0].startsWith('DEC-001') && labels[1].startsWith('DEC-002'),
    labels,
    noKeyComposite: labels.every((l) => !l.includes('@')),
    handleRow: labels.some((l) => l.startsWith('IFC-001')),
  };

  // type-ahead filter (id and title)
  const filter = find(popover, 'fmt-picker-filter');
  filter.value = 'buck';
  filter.dispatch('input');
  const filtered = findAll(popover, 'fmt-picker-row').map((r) => r.textContent);
  results.picker.filtered = filtered;

  // pick with a selection: [[ID|sel]]
  const rows2 = findAll(popover, 'fmt-picker-row');
  ed.select(0, 4);
  rows2[0].click();
  await tick(5);
  const n0 = execCalls.length;
  results.picker.pick = {
    value: ed.area.value,
    closed: find(ed.bar, 'fmt-picker').hidden === true,
    focusRestored: globalThis.document.activeElement === ed.area,
    expanded: findAll(ed.bar, 'fmt-reference')[0].getAttribute('aria-expanded'),
    draft: drafts.getDraft(h).body,
  };

  // pick at a caret: [[ID]]
  ed.select(0, 0);
  const popover2 = await openPicker(ed);
  findAll(popover2, 'fmt-picker-row')[1].click();
  results.picker.caretPick = { value: ed.area.value.slice(0, 20), draft: drafts.getDraft(h).body };

  // Escape closes and returns focus, mutating nothing
  const v0 = ed.area.value;
  const popover3 = await openPicker(ed);
  const ev = popover3.dispatch('keydown', { key: 'Escape' });
  results.picker.escape = {
    closed: popover3.hidden === true,
    focusRestored: globalThis.document.activeElement === ed.area,
    valueUnchanged: ed.area.value === v0,
    prevented: ev.defaultPrevented === true,
  };

  // keyboard activation: ArrowDown moves the active row, Enter picks it
  const popover4 = await openPicker(ed);
  popover4.dispatch('keydown', { key: 'ArrowDown' });
  const active = findAll(popover4, 'fmt-picker-row').filter((r) => hasCls(r, 'active'));
  const v1 = ed.area.value;
  popover4.dispatch('keydown', { key: 'Enter' });
  await tick(5);
  results.picker.keyboard = {
    activeLabel: active.map((r) => r.textContent),
    inserted: ed.area.value.length - v1.length === '[[DEC-001]]'.length
      && ed.area.value.includes('[[DEC-001]]'),
    closed: popover4.hidden === true,
  };
  drafts.clearDraft(h);
}
{
  // cap notice: the fetched page is a prefix, and the filter says so
  const h = 'RD-CAP';
  setItems([
    { id: 'AAA-001', handle: 'a1', title: 'First.' },
    { id: 'AAA-002', handle: 'a2', title: 'Second.' },
  ], 6000);
  const ed = openEditor(h, '');
  const popover = await openPicker(ed);
  results.cap = {
    notice: find(popover, 'fmt-picker-list').textContent.includes(
      'showing the first 2 of 6000 items -- the filter searches only these'),
  };
  drafts.clearDraft(h);
}
{
  // fetch failure: an honest banner, no crash
  const h = 'RD-FAIL';
  ITEMS_FAIL = 'the api is down';
  const ed = openEditor(h, '');
  const popover = await openPicker(ed);
  await tick(5);
  results.fetchFail = {
    banner: find(popover, 'fmt-picker-list').textContent.includes('items failed: the api is down'),
  };
  ITEMS_FAIL = null;
  drafts.clearDraft(h);
}

// ---------- Image/Source buttons focus the existing panels
{
  const h = 'RD-FOCUS';
  const ed = openEditor(h, 'body');
  ed.click('image');
  const focusImages = ed.editor.imagePicker.contains(globalThis.document.activeElement);
  const v0 = ed.area.value;
  ed.click('source');
  results.focus = {
    images: focusImages,
    source: ed.editor.sourcePicker.contains(globalThis.document.activeElement),
    bodyUnchanged: ed.area.value === v0,
  };
  drafts.clearDraft(h);
}

// ---------- shared picker module
{
  results.pickers = {
    limit: pickers.PICKER_LIMIT,
    displayHalfAt: pickers.displayHalf('DEC-001@abcd1234') === 'DEC-001',
    displayHalfPlain: pickers.displayHalf('DEC-001') === 'DEC-001',
  };
}

console.log(JSON.stringify(results));
"""


def _node_json(tmp_path, harness_source, timeout=NODE_TIMEOUT_S):
    script = harness_source.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
    harness = tmp_path / "refdes-buttons-node-harness.mjs"
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
            "refdes buttons node harness hung: "
            f"exit={exc.returncode}\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        )
    assert proc.returncode == 0, f"refdes buttons node harness failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_the_refdes_row_inserts_and_picks_through_the_shared_mutator(tmp_path):
    results = _node_json(tmp_path, HARNESS)

    g = results["group"]
    assert g["count"] == 1 and g["typed"] and len(g["labels"]) == 8
    assert all(len(label) > 0 for label in g["labels"]), g
    assert g["classes"] == [
        "fmt-btn fmt-reference", "fmt-btn fmt-figure", "fmt-btn fmt-calc",
        "fmt-btn fmt-span", "fmt-btn fmt-value", "fmt-btn fmt-navi",
        "fmt-btn fmt-image", "fmt-btn fmt-source",
    ], "Navi sits after value; the panel openers stay last"
    assert g["navi"] == {"text": "Navi", "aria": "Navi: insert a <!--navi: text--> marker"}, g["navi"]
    assert g["refAria"]["popup"] == "dialog" and g["refAria"]["expanded"] == "false", g
    assert g["mousedownPrevented"] is True, "mousedown must not steal focus from the textarea"

    sp = results["span"]
    assert sp["value"] == "`name := 0 | V` world", sp
    assert sp["nameSelected"] is True, "the §H-4 skeleton selects `name` (typing replaces it)"
    assert sp["execs"] == 1, "one insertion = one execCommand"
    assert sp["draft"] == "`name := 0 | V` world", "the draft commits through the input path"

    nc = results["naviCaret"]
    assert nc["value"] == "<!--navi: text-->hello world", nc
    assert nc["selText"] == "text", "the placeholder is selected (typing replaces it)"
    assert nc["execs"] == 1, "one insertion = one execCommand (Ctrl/Cmd+Z restores in one step)"
    assert nc["draft"] == "<!--navi: text-->hello world", "the draft commits through the input path"

    nw = results["naviWrap"]
    assert nw["value"] == "<!--navi: hello--> world", nw
    assert nw["selText"] == "hello", "the wrapped text stays selected"

    for name in ("dash", "arrow", "newline"):
        nr = results[f"naviRefuse-{name}"]
        assert nr["unchanged"] is True, (name, nr)
        assert nr["selUnchanged"] is True, (name, nr)
        assert nr["execs"] == 0, (name, nr)
        assert nr["draftUnchanged"] is True and nr["draft"] is None, (name, nr)

    fe = results["fence"]
    assert fe["value"] == "```calc\nname = expr | V\n```", fe
    assert fe["at"] == 0 and fe["nameSelected"] is True, fe
    assert fe["opens"] == 1, "fences stay balanced"
    fi = results["fenceInside"]
    assert fi["after"] is True, fi
    assert fi["opens"] == 2 and fi["nameSelected"] is True, fi

    fig = results["figure"]
    assert fig["caretInside"] is True, fig
    assert fig["value"] == "[[fig:hello]] world", fig
    assert fig["selText"] == "hello", "the wrapped id stays selected"

    va = results["value"]
    assert va["caretInside"] is True, va
    assert va["wrapped"] == "{{hello}} world", va
    assert va["selText"] == "hello", va

    assert results["astral"]["ok"] is True and results["astral"]["value"] == results["astral"]["want"], \
        results["astral"]

    sg = results["savingGate"]
    assert sg["unchanged"] and sg["draftUnchanged"], sg
    assert sg["pickerClosed"] is True, "the picker stays closed mid-save"

    assert results["readOnly"]["area"] is True and results["readOnly"]["bar"] is True

    pk = results["picker"]
    assert pk["opened"] is True and pk["expanded"] == "true", pk
    assert pk["fetchPath"] == "/api/items?limit=5000", pk
    assert pk["limit"] == 5000, pk
    assert pk["sorted"] is True and pk["handleRow"] is True, pk["labels"]
    assert pk["noKeyComposite"] is True, pk["labels"]
    assert pk["filtered"] == ["DEC-001 — Use the buck regulator."], pk["filtered"]
    assert pk["pick"]["value"] == "[[DEC-001|cite]] here", pk["pick"]
    assert pk["pick"]["closed"] and pk["pick"]["focusRestored"] and pk["pick"]["expanded"] == "false"
    assert pk["caretPick"]["value"].startswith("[[DEC-002]]"), pk["caretPick"]
    assert pk["escape"]["closed"] and pk["escape"]["focusRestored"] and pk["escape"]["prevented"]
    assert pk["escape"]["valueUnchanged"] is True, pk["escape"]
    assert pk["keyboard"]["activeLabel"] == ["DEC-001 — Use the buck regulator."], pk["keyboard"]
    assert pk["keyboard"]["inserted"] is True and pk["keyboard"]["closed"] is True, pk["keyboard"]

    assert results["cap"]["notice"] is True, results["cap"]
    assert results["fetchFail"]["banner"] is True, results["fetchFail"]

    fo = results["focus"]
    assert fo["images"] is True, "the Image button focuses the existing images panel"
    assert fo["source"] is True, "the Source button focuses the existing sources panel"
    assert fo["bodyUnchanged"] is True, "focus buttons never mutate the body"

    assert results["pickers"]["limit"] == 5000
    assert results["pickers"]["displayHalfAt"] is True
    assert results["pickers"]["displayHalfPlain"] is True
