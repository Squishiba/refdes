"""The editor font preference is a browser-only setting, not a body mutation.

The design (in-prog-logs/editor-format-toolbar-design-20261029.md §D) fixes
the storage key, the three family stacks, the 11–20 px stepper, the three line
heights, and the CSP-safe application path: CSSOM custom properties on the body
textarea. This harness uses the same real-served-module posture as
test_editor_link_undo.py: node imports fontsetting.js, editor.js, and item.js,
with a tiny DOM/storage stub, then asserts the store and the editor mount.
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

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.listeners = {};
    this.parentNode = null;
    this._parent = null;
    this._text = '';
    this.value = '';
    this.type = '';
    this.name = '';
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.rows = 0;
    this.readOnly = false;
    this.placeholder = '';
    this.src = '';
    this.alt = '';
    this.loading = '';
    this.href = '';
    this.target = '';
    this.rel = '';
    this.selectionStart = null;
    this.selectionEnd = null;
    this.style = {
      _props: {},
      setProperty(name, value) { this._props[name] = String(value); },
      getPropertyValue(name) { return this._props[name] || ''; },
    };
  }

  set className(value) { this._cls = String(value); }
  get className() { return this._cls || ''; }

  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() {
    return this.children.length
      ? this.children.map((child) => child.textContent).join('')
      : this._text;
  }

  get firstChild() { return this.children[0] || null; }

  appendChild(child) {
    child.parentNode = this;
    child._parent = this;
    this.children.push(child);
    return child;
  }

  replaceChild(newChild, oldChild) {
    const at = this.children.indexOf(oldChild);
    if (at >= 0) this.children[at] = newChild;
    newChild.parentNode = this;
    oldChild.parentNode = null;
    return oldChild;
  }

  remove() {
    const parent = this.parentNode || this._parent;
    if (parent) {
      parent.children = parent.children.filter((child) => child !== this);
      parent._parent = null;
    }
  }

  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((fn) => fn !== fnTarget);
    function fnTarget(candidate) { return candidate === fn; }
  }
  dispatchEvent(type, event = {}) {
    const detail = Object.assign({ type, target: this }, event);
    for (const fn of this.listeners[type] || []) fn(detail);
    if (this.parentNode) this.parentNode.dispatchEvent(type, detail);
  }
  click() { this.dispatchEvent('click'); }
  focus() { globalThis.document.activeElement = this; }
  select() {}
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  contains(node) {
    let cursor = node;
    while (cursor) {
      if (cursor === this) return true;
      cursor = cursor.parentNode;
    }
    return false;
  }
  querySelectorAll(selector) {
    const out = [];
    const matches = (node) => {
      if (selector.startsWith('.')) {
        return (node.className || '').split(/\s+/).includes(selector.slice(1));
      }
      if (selector.startsWith('[') && selector.endsWith(']')) {
        return node.getAttribute(selector.slice(1, -1)) !== null;
      }
      if (selector.includes('.')) {
        const [tag, cls] = selector.split('.');
        return (!tag || node.tagName === tag.toUpperCase())
          && (node.className || '').split(/\s+/).includes(cls);
      }
      return node.tagName === selector.toUpperCase();
    };
    const walk = (node) => {
      for (const child of node.children) {
        if (matches(child)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
}

function findAll(root, cls) {
  const out = [];
  const walk = (node) => {
    if (node && (node.className || '').split(/\s+/).includes(cls)) out.push(node);
    for (const child of (node && node.children) || []) walk(child);
  };
  walk(root);
  return out;
}

function find(root, cls) {
  return findAll(root, cls)[0] || null;
}

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, textContent: String(text) }),
  querySelector: (selector) => (selector.includes('refdes-token') ? { content: 'tok' } : null),
  activeElement: null,
  body: new FakeNode('body'),
};
globalThis.window = { addEventListener: () => {}, dispatchEvent: () => false };
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

function storageStub(initial = {}, throws = {}) {
  const store = new Map(Object.entries(initial));
  return {
    store,
    getItem(key) {
      if (throws.getItem) throw new Error('storage read denied');
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      if (throws.setItem) throw new Error('storage write denied');
      store.set(key, String(value));
    },
    removeItem(key) { store.delete(key); },
  };
}

globalThis.localStorage = storageStub();
globalThis.sessionStorage = storageStub();

function editItem() {
  return {
    id: 'DEC-001',
    handle: 'DEC-001',
    title: 'Editor font preference',
    type: 'DEC',
    board: 'main',
    source_file: 'decisions.md',
    source_line: 1,
    fields: {},
    inherited_fields: [],
    body: 'test body',
    links: { outgoing: {}, incoming: {} },
    coverage: null,
    checks: [],
    diagnostics: [],
    page: 'dec/001',
    revision: 'rev-0',
    edit: {
      editable: true,
      file_revision: 'rev-0',
      fields: {},
      body: { editable: true },
      links: {},
    },
  };
}

globalThis.fetch = async (path) => {
  const p = String(path);
  let payload = {};
  if (p.startsWith('/api/images')) payload = { images: [], asset_dirs: [] };
  else if (p.startsWith('/api/items')) payload = { items: [] };
  else if (p.startsWith('/api/item/DEC-001/sources')) payload = { files: [] };
  else if (p.startsWith('/api/item/DEC-001')) payload = editItem();
  return { ok: true, status: 200, statusText: 'OK', json: async () => payload };
};

const {
  STORAGE_KEY,
  FONT_STACKS,
  DEFAULT_FONT,
  createFontSetting,
} = await import(url('fontsetting.js'));
const { createEditor } = await import(url('editor.js'));
const { renderItem } = await import(url('item.js'));

const tick = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function controllerFor(initial = {}, throws = {}) {
  globalThis.localStorage = storageStub(initial, throws);
  return createFontSetting();
}

function areaWithFont(controller) {
  const area = new FakeNode('textarea');
  controller.applyTo(area);
  return area;
}

const results = {};

{
  const controller = controllerFor();
  const area = areaWithFont(controller);
  results.defaults = {
    key: STORAGE_KEY,
    current: controller.current(),
    vars: area.style._props,
    stacks: FONT_STACKS,
  };
}

{
  const payload = JSON.stringify({ family: 'serif', size: 16, lineHeight: 1.7 });
  const controller = controllerFor({ [STORAGE_KEY]: payload });
  const area = areaWithFont(controller);
  results.stored = { current: controller.current(), vars: area.style._props };
}

{
  const controller = controllerFor({ [STORAGE_KEY]: '{not json' });
  const area = areaWithFont(controller);
  results.corrupt = { current: controller.current(), vars: area.style._props };
}

{
  const payload = JSON.stringify({ family: 'comic', size: 99, lineHeight: 9, extra: true });
  const controller = controllerFor({ [STORAGE_KEY]: payload });
  const area = areaWithFont(controller);
  results.partial = { current: controller.current(), vars: area.style._props };
}

{
  const payload = JSON.stringify({ family: 'sans', size: '17', lineHeight: '1.7' });
  const controller = controllerFor({ [STORAGE_KEY]: payload });
  const area = areaWithFont(controller);
  results.stringish = { current: controller.current(), vars: area.style._props };
}

{
  const controller = controllerFor({}, { getItem: true });
  const area = areaWithFont(controller);
  results.readThrows = { current: controller.current(), vars: area.style._props };
}

{
  const controller = controllerFor({}, { setItem: true });
  controller.setFamily('sans');
  controller.setSize(17);
  controller.setLineHeight(1.35);
  const area = areaWithFont(controller);
  results.writeThrows = {
    current: controller.current(),
    vars: area.style._props,
    stored: globalThis.localStorage.store.get(STORAGE_KEY) || null,
  };
}

{
  const controller = controllerFor();
  const toggle = find(controller.node, 'font-setting-toggle');
  const popover = find(controller.node, 'font-setting-popover');
  const before = { hidden: popover.hidden, aria: toggle.getAttribute('aria-expanded'), popup: toggle.getAttribute('aria-haspopup') };
  toggle.click();
  const open = { hidden: popover.hidden, aria: toggle.getAttribute('aria-expanded') };
  find(controller.node, 'font-size-increase').click();
  find(controller.node, 'font-size-increase').click();
  const sizeValue = find(controller.node, 'font-size-value').textContent;
  findAll(controller.node, 'font-family').find((input) => input.dataset.family === 'sans').click();
  findAll(controller.node, 'font-line-height').find((input) => input.dataset.lineHeight === 'compact').click();
  popover.dispatchEvent('keydown', { key: 'Escape' });
  results.ui = {
    before,
    open,
    sizeValue,
    current: controller.current(),
    persisted: JSON.parse(globalThis.localStorage.getItem(STORAGE_KEY)),
    afterEscape: { hidden: popover.hidden, aria: toggle.getAttribute('aria-expanded') },
  };
}

{
  const readOnly = createEditor(
    { id: 'RO-001', edit: { editable: false, reason: 'sealed', fields: {}, body: { editable: false } } },
    'RO-001',
    () => {},
    () => {},
  );
  results.readOnly = {
    fontBar: readOnly.fontBar,
    body: readOnly.bodyControl ? readOnly.bodyControl('nope') : null,
  };
}

{
  globalThis.localStorage = storageStub({
    [STORAGE_KEY]: JSON.stringify({ family: 'sans', size: 17, lineHeight: 1.7 }),
  });
  globalThis.sessionStorage = storageStub();
  const container = new FakeNode('div');
  await renderItem(container, 'DEC-001');
  await tick(30);
  const area = find(container, 'body-edit');
  const bar = find(container, 'font-setting');
  const parent = area.parentNode;
  const initialVars = Object.assign({}, area.style._props);
  const focusBefore = (() => {
    area.focus();
    area.setSelectionRange(3, 3);
    return { value: area.value, start: area.selectionStart, end: area.selectionEnd };
  })();
  find(bar, 'font-size-increase').click();
  results.mounted = {
    hasBar: Boolean(bar),
    barBeforeArea: parent.children.indexOf(bar) >= 0 && parent.children.indexOf(bar) < parent.children.indexOf(area),
    initialVars: initialVars,
    vars: area.style._props,
    persisted: JSON.parse(globalThis.localStorage.getItem(STORAGE_KEY)),
    bodyUnchanged: area.value === focusBefore.value,
    selectionUnchanged: area.selectionStart === focusBefore.start && area.selectionEnd === focusBefore.end,
    focusStays: globalThis.document.activeElement === area,
  };
}

{
  const area = new FakeNode('textarea');
  const controller = controllerFor();
  controller.applyTo(area);
  results.customPropertiesOnly = {
    styleProps: area.style._props,
    directFontProperties: Object.keys(area.style._props).filter((name) => !name.startsWith('--refdes-editor-')),
    defaults: DEFAULT_FONT,
  };
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_font_setting_store_popover_and_editor_mount():
    script = HARNESS.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    results = json.loads(proc.stdout.strip().splitlines()[-1])

    assert results["defaults"]["key"] == "refdes.editor.font"
    assert results["defaults"]["current"] == {"family": "mono", "size": 12, "lineHeight": 1.5}
    assert results["defaults"]["stacks"] == {
        "mono": "monospace",
        "sans": "system-ui, sans-serif",
        "serif": "Georgia, serif",
    }
    assert results["defaults"]["vars"] == {
        "--refdes-editor-font": "monospace",
        "--refdes-editor-size": "12px",
        "--refdes-editor-line-height": "1.5",
    }

    assert results["stored"]["current"] == {"family": "serif", "size": 16, "lineHeight": 1.7}
    assert results["stored"]["vars"]["--refdes-editor-font"] == "Georgia, serif"
    assert results["stored"]["vars"]["--refdes-editor-size"] == "16px"
    assert results["stored"]["vars"]["--refdes-editor-line-height"] == "1.7"

    assert results["corrupt"]["current"] == {"family": "mono", "size": 12, "lineHeight": 1.5}
    assert results["corrupt"]["vars"]["--refdes-editor-font"] == "monospace"

    assert results["partial"]["current"] == {"family": "mono", "size": 20, "lineHeight": 1.5}
    assert results["stringish"]["current"] == {"family": "sans", "size": 17, "lineHeight": 1.7}

    assert results["readThrows"]["current"] == {"family": "mono", "size": 12, "lineHeight": 1.5}
    assert results["readThrows"]["vars"]["--refdes-editor-size"] == "12px"

    assert results["writeThrows"]["current"] == {"family": "sans", "size": 17, "lineHeight": 1.35}
    assert results["writeThrows"]["vars"]["--refdes-editor-font"] == "system-ui, sans-serif"
    assert results["writeThrows"]["stored"] is None

    assert results["ui"]["before"] == {"hidden": True, "aria": "false", "popup": "dialog"}
    assert results["ui"]["open"] == {"hidden": False, "aria": "true"}
    assert results["ui"]["sizeValue"] == "14px"
    assert results["ui"]["current"] == {"family": "sans", "size": 14, "lineHeight": 1.35}
    assert results["ui"]["persisted"] == {"family": "sans", "size": 14, "lineHeight": 1.35}
    assert results["ui"]["afterEscape"] == {"hidden": True, "aria": "false"}

    assert results["readOnly"]["fontBar"] is None
    assert results["readOnly"]["body"] is None

    assert results["mounted"]["hasBar"] is True
    assert results["mounted"]["barBeforeArea"] is True
    assert results["mounted"]["initialVars"] == {
        "--refdes-editor-font": "system-ui, sans-serif",
        "--refdes-editor-size": "17px",
        "--refdes-editor-line-height": "1.7",
    }
    assert results["mounted"]["vars"] == {
        "--refdes-editor-font": "system-ui, sans-serif",
        "--refdes-editor-size": "18px",
        "--refdes-editor-line-height": "1.7",
    }
    assert results["mounted"]["persisted"] == {
        "family": "sans",
        "size": 18,
        "lineHeight": 1.7,
    }
    assert results["mounted"]["bodyUnchanged"] is True
    assert results["mounted"]["selectionUnchanged"] is True
    assert results["mounted"]["focusStays"] is True

    assert results["customPropertiesOnly"]["directFontProperties"] == []
    assert results["customPropertiesOnly"]["defaults"] == {"family": "mono", "size": 12, "lineHeight": 1.5}
