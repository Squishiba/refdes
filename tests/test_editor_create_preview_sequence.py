"""A superseded create-preview response must never write the form (EDITOR-API-011).

The New Item form fires an unawaited ``/api/create/preview`` on every id
keystroke, destination keystroke, and type/board/workspace change
(``create.js`` ``refreshPreview``). Network completions arrive in any order,
so a late answer for a superseded request can land last; the continuation
writes ``idPreview.textContent``, the class, and ``destInput.value``
unconditionally, so the form ends up showing the id and destination of an
input the user has already replaced — and a late *failure* stamps
"preview failed" over the newest request's good answer. Nothing is reserved
by a preview (the service re-plans under the save lock), so the visible
"would be" id is the form's only promise to the user before Create; showing
a stale one is the whole failure.

There is no Node build step and no browser here (see ``test_serve_static.py``),
so this drives the real ``create.js`` headless under node — the same posture
as ``test_editor_create_workspace.py`` — with the one addition this finding
needs: the fetch stub hands preview requests *deferred* resolvers, so the
test pins the completion order (newer first, older landing late).

Four scenarios, one node process:

- stale success: type an explicit id, resolve the newer preview first, then
  let the initial one land late — the id badge and the suggested destination
  must keep the newest request's answer.
- stale failure: same overlap, the superseded request fails late — a
  "preview failed" banner must not stamp over the newest good answer.
- type change mid-flight: switching type fires a second preview; a late
  answer for the *previous* type must not show its id.
- controls: the newest response still writes the badge and suggests the
  destination, and a user-typed destination is never overwritten.
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

// Preview responses are DEFERRED: the stub records a resolver per request,
// so the test decides which preview lands first and which lands late.
let schemaPayload;
const previewRequests = [];
const okRes = (payload) => ({ ok: true, status: 200, statusText: 'OK', json: async () => payload });
const badRes = (payload) => ({ ok: false, status: 500, statusText: 'Server Error', json: async () => payload });
globalThis.fetch = (path, init) => {
  if (path.includes('/api/create/preview')) {
    const entry = { url: path };
    entry.promise = new Promise((resolve) => {
      entry.resolve = (payload, ok = true) => resolve(ok ? okRes(payload) : badRes(payload));
    });
    previewRequests.push(entry);
    return entry.promise;
  }
  return Promise.resolve(okRes(schemaPayload));
};

const { createForm } = await import(url('create.js'));
const tick = (ms) => new Promise((r) => setTimeout(r, ms));
const drain = () => previewRequests.splice(0, previewRequests.length);

const fieldSpec = { type: 'text', required: true, creatable: true, default: '' };
const REQ_TYPE = { name: 'requirement', prefix: 'REQ', label: 'Requirement', append_only: false, amends: false, fields: { text: fieldSpec } };
const DEC_TYPE = { name: 'decision', prefix: 'DEC', label: 'Decision', append_only: false, amends: false, fields: { text: fieldSpec } };

const results = {};

// -- stale success: the late answer for the pre-keystroke input must not
//    overwrite the id badge or the destination the newer response suggested
{
  schemaPayload = { types: [REQ_TYPE], boards: [], workspaces: [], date_format: 'YYYY-MM-DD' };
  const form = createForm({});
  await tick(50);
  const initial = drain();
  results.staleSuccessOpenRequests = initial.length;
  const idInput = find(form, 'create-id');
  const idPreview = find(form, 'id-preview');
  const destInput = find(form, 'create-destination');
  idInput.value = 'REQ-042';
  idInput.dispatch('input');
  await tick(20);
  const newer = drain();
  results.staleSuccessSecondRequest = newer.length;
  results.staleSuccessSecondUrl = newer.length ? newer[0].url : null;
  newer[0].resolve({ id: 'REQ-042', destination: 'items/explicit.yaml' });
  await tick(20);
  results.afterNewest = { id: idPreview.textContent, dest: destInput.value };
  initial[0].resolve({ id: 'REQ-001', destination: 'items/old.yaml' }); // lands late
  await tick(20);
  results.afterStale = { id: idPreview.textContent, dest: destInput.value, cls: idPreview.className };
}

// -- stale failure: a late refusal for a superseded input must not stamp
//    "preview failed" over the newest request's good answer
{
  schemaPayload = { types: [REQ_TYPE], boards: [], workspaces: [], date_format: 'YYYY-MM-DD' };
  const form = createForm({});
  await tick(50);
  const initial = drain();
  const idInput = find(form, 'create-id');
  const idPreview = find(form, 'id-preview');
  idInput.value = 'REQ-043';
  idInput.dispatch('input');
  await tick(20);
  const newer = drain();
  newer[0].resolve({ id: 'REQ-043', destination: 'items/reqs.yaml' });
  await tick(20);
  initial[0].resolve({ error: 'boom' }, false); // the superseded request fails late
  await tick(20);
  results.afterStaleFailure = { id: idPreview.textContent, cls: idPreview.className };
}

// -- type change mid-flight: a late answer for the PREVIOUS type's preview
//    must not show its id after the form switched types
{
  schemaPayload = { types: [REQ_TYPE, DEC_TYPE], boards: [], workspaces: [], date_format: 'YYYY-MM-DD' };
  const form = createForm({});
  await tick(50);
  const initial = drain();
  const typeSelect = find(form, 'create-type');
  const idPreview = find(form, 'id-preview');
  typeSelect.value = 'decision';
  typeSelect.dispatch('change');
  await tick(20);
  const newer = drain();
  results.typeChangeSecondUrl = newer.length ? newer[0].url : null;
  newer[0].resolve({ id: 'DEC-001', destination: 'items/decs.yaml' });
  await tick(20);
  initial[0].resolve({ id: 'REQ-001', destination: 'items/reqs.yaml' }); // lands late
  await tick(20);
  results.afterTypeChange = { id: idPreview.textContent };
}

// -- controls: the newest response writes the badge and suggests the
//    destination; a destination the user typed is never overwritten
{
  schemaPayload = { types: [REQ_TYPE], boards: [], workspaces: [], date_format: 'YYYY-MM-DD' };
  const form = createForm({});
  await tick(50);
  drain();
  const idPreview = find(form, 'id-preview');
  const destInput = find(form, 'create-destination');
  destInput.value = 'my/dest.yaml';
  destInput.dispatch('input');
  await tick(20);
  const newer = drain();
  newer[0].resolve({ id: 'REQ-007', destination: 'items/other.yaml' });
  await tick(20);
  results.controlFreshWrite = { id: idPreview.textContent, dest: destInput.value };
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served create form module")
def test_superseded_create_preview_responses_never_write_the_form():
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

    # the overlap exists: one preview on open, a second after the keystroke,
    # carrying the newer id
    assert results["staleSuccessOpenRequests"] == 1
    assert results["staleSuccessSecondRequest"] == 1
    assert "id=REQ-042" in results["staleSuccessSecondUrl"]

    # the newest response lands and writes the form
    assert results["afterNewest"] == {"id": "would be REQ-042", "dest": "items/explicit.yaml"}

    # the superseded response lands late: badge, class, and destination keep
    # the newest answer
    assert results["afterStale"]["id"] == "would be REQ-042"
    assert results["afterStale"]["dest"] == "items/explicit.yaml"
    assert results["afterStale"]["cls"] == "badge id-preview"

    # a late failure for superseded input never stamps the badge as failed
    assert results["afterStaleFailure"]["id"] == "would be REQ-043"
    assert results["afterStaleFailure"]["cls"] == "badge id-preview"

    # a late answer for the previous type never shows its id after a switch
    assert "type=decision" in results["typeChangeSecondUrl"]
    assert results["afterTypeChange"]["id"] == "would be DEC-001"

    # controls: the newest response writes, and a typed destination sticks
    assert results["controlFreshWrite"] == {"id": "would be REQ-007", "dest": "my/dest.yaml"}
