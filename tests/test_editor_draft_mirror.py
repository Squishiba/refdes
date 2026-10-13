"""The draft mirror must never hold an op that memory has already applied.

The editor posts a multi-op save one op at a time (editor.js ``postAll``);
each 200 response means that op is applied on disk and must leave the draft
-- both the live memory copy and the sessionStorage mirror, which is what a
tab reload restores (docs/design/browser-editor.md, "Drafts: what the editor
holds before it saves"). A mirror write landing *between* "server applied
this op" and "memory dropped it" leaves the applied edit in sessionStorage
as still-pending: a reload restores it as dirty, the status line lies about
what is saved, and a retry re-posts an already-applied op. There is no Node
build step and no browser here (see ``test_serve_static.py``), so this runs
the real modules headless under node -- the same posture as the browser,
minus the rendering: the actual ``editor.js`` save loop drives the actual
``drafts.js`` persistence over a ``sessionStorage`` stub, and "reload" is a
fresh import of ``drafts.js`` (a new memory ``Map``) over the same storage.

Two scenarios, one node process:

- partial: a field op and a body op pending; the server applies the field
  (200) and refuses the body (422). The mirror and the reloaded draft must
  hold the *refused* body only -- never the applied field.
- complete: a field op and a link op pending; both apply. The save clears
  the draft, so the mirror key must be gone and a reload must come back
  clean and not dirty.
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

# One node spawn for both scenarios; generous for a cold process start on a
# shared runner (see the timeout note in test_vscode_extension.py for why
# 10 s is not one).
NODE_TIMEOUT_S = 120

HARNESS = """
const STATIC = __STATIC__;
const url = (name) => `file://${STATIC}/${name}`;

const store = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
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
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  click() { for (const fn of this.listeners.click || []) fn({}); }
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

const posts = [];
let respond; // (body, n) => {ok, payload} for the n-th edit POST
globalThis.fetch = async (path, init) => {
  const sent = init && init.body ? JSON.parse(init.body) : null;
  if (path.includes('/edit')) {
    posts.push(sent);
    const { ok, payload } = respond(sent, posts.length);
    return {
      ok,
      status: ok ? 200 : 422,
      statusText: ok ? 'OK' : 'Unprocessable',
      json: async () => payload,
    };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) };
};

const { createEditor } = await import(url('editor.js'));
const drafts = await import(url('drafts.js'));
let freshCount = 0;
const reloadDrafts = async () =>
  await import(`${url('drafts.js')}?reload=${++freshCount}`); // fresh memory Map, same storage

function editItem(handle) {
  return {
    id: handle,
    revision: 'rev-0',
    edit: {
      editable: true,
      file_revision: 'rev-0',
      fields: { status: { editable: true, value_type: 'enum', choices: ['draft', 'approved'] } },
      body: { editable: true },
      links: {},
    },
  };
}

const mirrorOf = (handle) =>
  JSON.parse(globalThis.sessionStorage.getItem(`refdes.draft.v1.${encodeURIComponent(handle)}`) ?? 'null');

const results = {};

// -- partial: field applies, body refused -> mirror keeps only the refused op
{
  const handle = 'REQ-001';
  let saved = false;
  const editor = createEditor(editItem(handle), handle, () => { saved = true; }, () => {});
  drafts.setDraftField(handle, 'status', 'approved');
  drafts.setDraftBody(handle, 'new body text');
  respond = (body, n) => (n === 1
    ? { ok: true, payload: { revision: 'rev-1' } }
    : { ok: false, payload: { kind: 'refused', reason: 'nope' } });
  find(editor.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  const reloaded = (await reloadDrafts()).getDraft(handle);
  results.partial = {
    posts: posts.map((p) => `${p.op}@${p.expected_revision}`),
    memory: drafts.isDirty(drafts.getDraft(handle)),
    mirror: mirrorOf(handle),
    reloadFields: reloaded.fields,
    reloadDirty: drafts.isDirty(reloaded),
    saved,
  };
}

// -- complete: every op applies -> the save clears the draft entirely
{
  const handle = 'REQ-002';
  let saved = false;
  posts.length = 0;
  const editor = createEditor(editItem(handle), handle, () => { saved = true; }, () => {});
  drafts.setDraftField(handle, 'status', 'approved');
  drafts.draftLinkAdd(handle, 'satisfies', 'REQ-003');
  let rev = 0;
  respond = () => ({ ok: true, payload: { revision: `rev-${++rev}` } });
  find(editor.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  const reloaded = (await reloadDrafts()).getDraft(handle);
  results.complete = {
    posts: posts.map((p) => `${p.op}@${p.expected_revision}`),
    mirror: mirrorOf(handle),
    reloadDirty: drafts.isDirty(reloaded),
    saved,
  };
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_applied_ops_leave_the_session_mirror_with_the_memory_that_dropped_them():
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

    partial = results["partial"]
    # the field op applied at rev-1 and the body op then carried that revision
    assert partial["posts"] == ["set_field@rev-0", "set_body@rev-1"]
    assert partial["saved"] is False
    # the editor's status line follows the live draft: still dirty (the body)
    assert partial["memory"] is True
    # the core assertion: the mirror holds only what memory still holds --
    # the refused body, and never the applied field
    assert partial["mirror"]["fields"] == {}, (
        "the applied set_field op is still in the sessionStorage mirror: it was "
        "persisted before the drop and never re-persisted after (EDITOR-API-002)"
    )
    assert partial["mirror"]["body"] == "new body text"
    # a reload restores the draft as it actually stands: pending body, no field
    assert partial["reloadFields"] == {}, (
        "a fresh drafts.js over the same storage restored the applied set_field "
        "op as still-pending (EDITOR-API-002)"
    )
    assert partial["reloadDirty"] is True
    assert partial["mirror"]["revision"] == "rev-1"

    complete = results["complete"]
    assert complete["posts"] == ["set_field@rev-0", "add_link@rev-1"]
    assert complete["saved"] is True
    # a fully-saved draft is no draft at all: the mirror key is gone...
    assert complete["mirror"] is None
    # ...and a reload comes back clean, not dirty
    assert complete["reloadDirty"] is False
