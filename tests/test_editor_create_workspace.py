"""The New Item form must carry a chosen workspace to preview and create.

docs/design/browser-editor.md, "Creating items": "Creation starts with type,
then board/workspace where configured", with the destination suggested from
the project's registered board/workspace paths. The form had a Board select
only -- the service accepts `workspace` and `/api/create/schema` publishes
the workspaces list, so the UI dropped the scope between the select and the
request. There is no Node build step and no browser here (see
``test_serve_static.py``), so this drives the real ``create.js`` headless
under node -- the same posture as ``test_editor_draft_mirror.py``: a
``FakeNode`` whose ``value`` getter is DOM-faithful (an option's value is its
text when none is set; a select's value is its first option's), the real
``api.js`` over a fetch stub, and assertions on the requests the form
actually sends.

Three scenarios, one node process:

- workspaces configured: the form renders a Workspace select whose default
  option has an *empty* value (the browser reads an option's value as its
  text, so "(file default)" is only inert if its value attribute is '' --
  a truthy label leaks straight into ``fields`` and onto disk), picking
  ``product-a`` puts ``workspace=product-a`` on the next preview GET, and
  the create POST carries ``fields.workspace`` and no board.
- boards configured, form untouched: the create POST carries no ``board``
  key -- the "(file default)" row means "ask the file", not a value.
- no workspaces configured: no Workspace control, no workspace param.
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

HARNESS = """
const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this._text = '';
  }
  set className(v) { this._cls = v; }
  get className() { return this._cls || ''; }
  set textContent(v) { this._text = String(v); if (v !== '') this.children = []; }
  get textContent() {
    return this.children.length
      ? this.children.map((c) => c.textContent).join('')
      : this._text;
  }
  // DOM-faithful value: an <option> with no value attribute reports its
  // text; a <select> reports its first option's value until assigned.
  get value() {
    if (this._value !== undefined) return this._value;
    if (this.tagName === 'SELECT') {
      const first = this.children.find((c) => c.tagName === 'OPTION');
      return first ? first.value : '';
    }
    return this._text;
  }
  set value(v) { this._value = String(v); }
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this['attr_' + name] = value; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  dispatch(type) { for (const fn of this.listeners[type] || []) fn({ target: this }); }
  click() { this.dispatch('click'); }
  querySelectorAll(sel) {
    const out = [];
    const walk = (node) => {
      for (const child of node.children) {
        if (sel === '[data-field]' && child.dataset && child.dataset.field !== undefined) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
  setSelectionRange() {}
  focus() {}
  select() {}
}

function find(node, cls) {
  if ((node.className || '').split(/\\s+/).includes(cls)) return node;
  for (const child of node.children) {
    const hit = find(child, cls);
    if (hit) return hit;
  }
  return null;
}

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector: (sel) => (sel.includes('refdes-token') ? { content: 'tok' } : null),
};
globalThis.window = { addEventListener: () => {} };
globalThis.location = { hash: '' };

let schemaPayload;
const previewUrls = [];
const createBodies = [];
globalThis.fetch = async (path, init) => {
  if (path.includes('/api/create/preview')) {
    previewUrls.push(path);
    return {
      ok: true, status: 200, statusText: 'OK',
      json: async () => ({ id: 'REQ-001', destination: 'items/reqs.yaml', destination_exists: true }),
    };
  }
  if (path.includes('/api/items/create')) {
    createBodies.push(JSON.parse(init.body));
    return {
      ok: true, status: 200, statusText: 'OK',
      json: async () => ({ id: 'REQ-001', path: 'items/reqs.yaml' }),
    };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => schemaPayload };
};

const { createForm } = await import(url('create.js'));
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

const fieldSpec = { type: 'text', required: true, creatable: true, default: '' };
const REQ_TYPE = { name: 'requirement', prefix: 'REQ', label: 'Requirement', append_only: false, amends: false, fields: { text: fieldSpec } };

const results = {};

// -- workspaces configured: control, preview param, create body
{
  schemaPayload = {
    types: [REQ_TYPE],
    boards: ['board-a', 'board-b'],
    workspaces: ['platform', 'product-a'],
    date_format: 'YYYY-MM-DD',
  };
  const form = createForm({});
  await tick(50);
  const ws = find(form, 'create-workspace');
  const board = find(form, 'create-board');
  results.workspaceOptions = ws ? ws.options.map((o) => o.value) : null;
  results.boardDefaultOptionValue = board ? board.options[0].value : null;
  results.initialPreviewUrl = previewUrls[previewUrls.length - 1] || null;
  if (ws) {
    ws.value = 'product-a';
    ws.dispatch('change');
    await tick(50);
    results.chosenPreviewUrl = previewUrls[previewUrls.length - 1] || null;
  }
  find(form, 'create-save').click();
  await tick(50);
  results.createFields = createBodies.length ? createBodies[createBodies.length - 1].fields : null;
}

// -- boards configured, nothing touched: the file-default row sends no board
{
  previewUrls.length = 0;
  createBodies.length = 0;
  schemaPayload = {
    types: [REQ_TYPE],
    boards: ['board-a'],
    workspaces: [],
    date_format: 'YYYY-MM-DD',
  };
  const form = createForm({});
  await tick(50);
  results.noWorkspaceControl = find(form, 'create-workspace') === null;
  results.boardOnlyPreviewUrl = previewUrls[previewUrls.length - 1] || null;
  find(form, 'create-save').click();
  await tick(50);
  results.untouchedCreateFields = createBodies.length ? createBodies[0].fields : null;
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served create form module")
def test_the_create_form_carries_the_workspace_choice_through_preview_to_create():
    script = HARNESS.replace("__STATIC__", json.dumps(STATIC.replace(os.sep, "/")))
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    results = json.loads(proc.stdout.strip().splitlines()[-1])

    # the control exists and its options are (empty default) + registry keys
    assert results["workspaceOptions"] == ["", "platform", "product-a"]
    # "(file default)" is a label, never a value -- on a board-only project
    # the untouched select must not stamp a board on the item at all (a blank
    # required text control is skipped: "the gate's to report")
    assert results["boardDefaultOptionValue"] == ""
    assert results["untouchedCreateFields"] == {}

    # the untouched form sends no scope at all
    assert "workspace=" not in (results["initialPreviewUrl"] or "")
    assert "board=" not in (results["initialPreviewUrl"] or "")

    # picking a workspace steers the preview, and the create carries it
    assert "workspace=product-a" in (results["chosenPreviewUrl"] or "")
    assert results["createFields"] == {"workspace": "product-a"}

    # a project with no workspaces gets no control and sends no param
    assert results["noWorkspaceControl"] is True
    assert "workspace=" not in (results["boardOnlyPreviewUrl"] or "")
