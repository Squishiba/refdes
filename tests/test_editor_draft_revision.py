"""A dirty form saves against the revision it OPENED on, never the newest one.

docs/design/browser-editor.md, "Revision and conflict detection": "A content
mismatch returns a conflict, never a last-write-wins save" -- and "Drafts":
the draft is "the intent to change one item, held against the revision the
form was opened on". The bug this pins (reproduced live in Chromium 2026-11-05):
open the editor, type an unsaved body change, let an external writer move the
item's file, let the poller fire `refdes:rebuilt`, click Save. The re-rendered
form re-adopts the NEW file revision (editor.js opens with
`draft.revision || edit.file_revision`, and `draft.revision` is only written
by `dropAppliedOp` after a partial save), so Save posts the new revision, the
server sees a match, and the external change is silently lost.

The contract, per scenario (node harness, the posture of
tests/test_editor_draft_mirror.py: the real editor.js/drafts.js under a
sessionStorage/document/fetch stub; a rebuild re-render is a second
`createEditor` over the same handle with the item payload the refetch carries,
exactly what app.js's renderRoute -> renderItem does):

- stamp: the first change to a field/body makes the draft record the revision
  the form opened on;
- rebuild-changed: after a rebuild that moved the file revision, Save posts
  the OPENING revision, the 409 opens the conflict screen, nothing saves;
- rebuild-clean: a form with no draft adopts the new revision (no false
  conflict, no stale revision) and saves at it;
- save-then-stamp: a successful save clears the draft; the next edit records
  the NEW revision, and a later rebuild conflicts against it;
- rebuild-same-revision: a rebuild that did not move THIS item's file (an
  unrelated item changed) must not turn a dirty form into a conflict.

The server side of the same contract (the real save API returns 409 for a
stale body save; an external change to another item's file does not conflict
this one) is pinned in tests/test_serve_edit_http.py.
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
    this.dataset = {};
    this.style = {
      _props: {},
      setProperty(name, value) { this._props[name] = String(value); },
      getPropertyValue(name) { return this._props[name] || ''; },
    };
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
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  fire(type) { for (const fn of this.listeners[type] || []) fn({}); }
  click() { this.fire('click'); }
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

let posts = [];
let respond; // (body) => {status, payload} for each edit POST
globalThis.fetch = async (path, init) => {
  const sent = init && init.body ? JSON.parse(init.body) : null;
  if (path.includes('/edit')) {
    posts.push(sent);
    const { status, payload } = respond(sent);
    return { ok: status === 200, status, statusText: '', json: async () => payload };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({ spans: [] }) };
};

const { createEditor } = await import(url('editor.js'));
const drafts = await import(url('drafts.js'));

// The payload a refetch carries: the item's file is at `rev` on disk now.
function itemAt(handle, rev) {
  return {
    id: handle,
    revision: rev,
    edit: {
      editable: true,
      file_revision: rev,
      fields: { status: { editable: true, value_type: 'enum', control: 'select', choices: ['draft', 'approved'] } },
      body: { editable: true },
      links: {},
    },
  };
}

// The author types into the form the way a keystroke does: the value lands in
// the control, the input listener commits it to the draft.
function typeBody(editor, text) {
  const area = editor.bodyControl('body from disk');
  area.value = text;
  area.fire('input');
  return area;
}

const ok200 = (rev) => ({ status: 200, payload: { revision: rev } });
const conflict = (current) => ({
  status: 409,
  payload: {
    kind: 'conflict', ok: false, message: 'the file changed',
    current_revision: current, current_text: 'disk text', diff: '--- a\\n+++ b',
  },
});
const conflictUnlessAt = (opening, advanced) => (sent) =>
  sent.expected_revision === opening
    ? conflict(advanced)
    : ok200(sent.expected_revision.replace(/\\d+/, (n) => String(Number(n) + 1)));

const results = {};

// -- stamp: the first change records the revision the form opened on
{
  const handle = 'REQ-001';
  typeBody(createEditor(itemAt(handle, 'rev-0'), handle, () => {}, () => {}), 'my typed body');
  const draft = drafts.getDraft(handle);
  results.stamp = { body: draft.body, revision: draft.revision };
  drafts.clearDraft(handle);
}

// -- stamp on a field change
{
  const handle = 'REQ-002';
  const editor = createEditor(itemAt(handle, 'rev-0'), handle, () => {}, () => {});
  const select = editor.fieldControl('status', 'approved');
  select.value = 'draft';
  select.fire('change');
  results.stampField = { fields: drafts.getDraft(handle).fields, revision: drafts.getDraft(handle).revision };
  drafts.clearDraft(handle);
}

// -- rebuild-changed: Save must carry the OPENING revision and show the conflict
{
  const handle = 'REQ-003';
  typeBody(createEditor(itemAt(handle, 'rev-0'), handle, () => {}, () => {}), 'my typed body');
  // refdes:rebuilt -> renderRoute -> renderItem refetches: the file is at rev-1
  let saved = false;
  const editor = createEditor(itemAt(handle, 'rev-1'), handle, () => { saved = true; }, () => {});
  const area = editor.bodyControl('body from disk + EXTERNAL EDIT');
  const reopenedAt = editor.getRevision();
  const shownValue = area.value;
  posts = [];
  respond = conflictUnlessAt('rev-0', 'rev-1');
  find(editor.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  results.rebuildChanged = {
    reopenedAt,
    shownValue,
    posts: posts.map((p) => `${p.op}@${p.expected_revision}`),
    saved,
    conflictVisible: find(editor.node, 'conflict').hidden === false,
    draftKept: drafts.isDirty(drafts.getDraft(handle)),
  };
  drafts.clearDraft(handle);
}

// -- rebuild-clean: no draft, the reopened form adopts the new revision
{
  const handle = 'REQ-004';
  createEditor(itemAt(handle, 'rev-0'), handle, () => {}, () => {});
  let saved = false;
  const editor = createEditor(itemAt(handle, 'rev-1'), handle, () => { saved = true; }, () => {});
  const reopenedAt = editor.getRevision();
  typeBody(editor, 'typed after adopting rev-1');
  posts = [];
  respond = (sent) =>
    sent.expected_revision === 'rev-1' ? ok200('rev-2') : conflictUnlessAt('rev-1', 'rev-1')(sent);
  find(editor.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  results.rebuildClean = {
    reopenedAt,
    posts: posts.map((p) => `${p.op}@${p.expected_revision}`),
    saved,
    conflictVisible: find(editor.node, 'conflict').hidden === false,
  };
  drafts.clearDraft(handle);
}

// -- save-then-stamp: after a save, the NEXT edit records the NEW revision,
//    and a later rebuild conflicts against it (never last-write-wins)
{
  const handle = 'REQ-005';
  let saved = false;
  const editor = createEditor(itemAt(handle, 'rev-0'), handle, () => { saved = true; }, () => {});
  typeBody(editor, 'first edit');
  posts = [];
  respond = (sent) => (sent.expected_revision === 'rev-0' ? ok200('rev-1') : conflict(sent.expected_revision));
  find(editor.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  const cleared = !drafts.isDirty(drafts.getDraft(handle));
  typeBody(editor, 'second edit');
  const stamp = drafts.getDraft(handle).revision;
  const rebuilt = createEditor(itemAt(handle, 'rev-2'), handle, () => { saved = true; }, () => {});
  rebuilt.bodyControl('body from disk + EXTERNAL EDIT');
  posts = [];
  respond = conflictUnlessAt('rev-1', 'rev-2');
  find(rebuilt.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  results.saveThenStamp = {
    firstSaved: saved,
    cleared,
    stamp,
    posts: posts.map((p) => `${p.op}@${p.expected_revision}`),
    conflictVisible: find(rebuilt.node, 'conflict').hidden === false,
  };
  drafts.clearDraft(handle);
}

// -- rebuild-same-revision: an unrelated item changed; this item's file did
//    not move, so the dirty form must save cleanly at its own revision
{
  const handle = 'REQ-006';
  let saved = false;
  const editor = createEditor(itemAt(handle, 'rev-0'), handle, () => {}, () => {});
  typeBody(editor, 'my typed body');
  const rebuilt = createEditor(itemAt(handle, 'rev-0'), handle, () => { saved = true; }, () => {});
  rebuilt.bodyControl('body from disk');
  posts = [];
  respond = (sent) => (sent.expected_revision === 'rev-0' ? ok200('rev-1') : conflict(sent.expected_revision));
  find(rebuilt.node, 'save').click();
  await new Promise((r) => setTimeout(r, 50));
  results.rebuildSameRevision = {
    posts: posts.map((p) => `${p.op}@${p.expected_revision}`),
    saved,
    conflictVisible: find(rebuilt.node, 'conflict').hidden === false,
  };
  drafts.clearDraft(handle);
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_a_dirty_form_keeps_the_revision_it_opened_on_through_a_rebuild():
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

    # (1) the first change to the body records the revision the form opened on
    assert results["stamp"]["body"] == "my typed body"
    assert results["stamp"]["revision"] == "rev-0", (
        "the first keystroke did not record the opening revision in the draft: "
        "draft.revision stayed null, so a rebuild re-adopts the newest file "
        "revision and Save becomes last-write-wins"
    )

    # (1b) same for a field change
    assert results["stampField"]["fields"] == {"status": "draft"}
    assert results["stampField"]["revision"] == "rev-0", (
        "the first field change did not record the opening revision in the draft"
    )

    # (2) the re-rendered dirty form keeps the OPENING revision; Save posts it,
    # the server's 409 opens the conflict screen, and nothing saves
    rebuilt = results["rebuildChanged"]
    assert rebuilt["shownValue"] == "my typed body"  # the draft survives the re-render
    assert rebuilt["reopenedAt"] == "rev-0", (
        f"the form re-opened on {rebuilt['reopenedAt']!r}, the NEW file revision: "
        "a dirty draft must keep the revision it opened on (rev-0), not adopt the "
        "revision the external writer produced"
    )
    assert rebuilt["posts"] == ["set_body@rev-0"], (
        f"Save carried {rebuilt['posts']!r}: it posted the revision the external "
        "writer produced, so the server accepts it and the external change is lost"
    )
    assert rebuilt["saved"] is False
    assert rebuilt["conflictVisible"] is True, (
        "a save that trails the file must open the conflict screen (keep-mine / "
        "keep-theirs / diff), not report success"
    )
    assert rebuilt["draftKept"] is True

    # (3) a form with no draft adopts the new revision and saves at it
    clean = results["rebuildClean"]
    assert clean["reopenedAt"] == "rev-1"
    assert clean["posts"] == ["set_body@rev-1"]
    assert clean["saved"] is True
    assert clean["conflictVisible"] is False

    # (4) after a save the draft is gone; the next edit records the NEW revision,
    # and the next rebuild conflicts against it
    after = results["saveThenStamp"]
    assert after["firstSaved"] is True
    assert after["cleared"] is True
    assert after["stamp"] == "rev-1", (
        f"the edit after a successful save recorded {after['stamp']!r}: it must "
        "record the revision the save produced (rev-1), not null"
    )
    assert after["posts"] == ["set_body@rev-1"], (
        f"Save carried {after['posts']!r} after the save+rebuild: it must trail "
        "the external writer (rev-1) and conflict, not post rev-2"
    )
    assert after["conflictVisible"] is True

    # (5) a rebuild that did not move THIS item's file does not conflict a
    # dirty form: the save rides the same revision and lands
    same = results["rebuildSameRevision"]
    assert same["posts"] == ["set_body@rev-0"]
    assert same["saved"] is True
    assert same["conflictVisible"] is False
