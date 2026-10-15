"""Undo of a pending link op cancels it -- it does not mint the opposite op.

The link picker's undo button sits on a *pending* line (links.js), and its
only sane meaning is "take that op back": the link goes back to what the
server holds. Implemented with the add/remove *toggle* (drafts.js
`linkToggle`), undo of a pending add pushed the target onto the remove side
-- a `remove_link` for a link the item does not have -- and undo of a
pending remove pushed it onto the add side -- an `add_link` for a link it
already has. The server refuses exactly those ops (422 refused, verified
against a live server on current main: `remove_link satisfies REQ-002` on
DEC-001 -> "does not link REQ-002"; `add_link` of the composite the undo
stamps -> "no item ... to link to"), and a refused save leaves the whole
draft behind, so the author's undo is sticky: Save is red, the draft reloads
dirty, and the bogus op survives (EDITOR-API-004).

Same posture as `test_editor_draft_mirror.py`: no browser, the REAL served
modules under node -- `editor.js` (which builds the real `links.js` picker)
driving the real `drafts.js` over a `sessionStorage` stub, with "reload" a
fresh import of `drafts.js` (a new memory Map) over the same storage.

Scenarios, one node process:

- undo-add: add a candidate, undo it. The draft is clean -- no op on
  either side, no mirror, and a reload comes back clean. (Base: a pending
  `remove_link` survives here, the Save posts it, the refusal keeps it.)
- undo-remove: remove a real server link, undo the removal. Clean again,
  and the link stays where the server has it. (Base: a pending `add_link`
  for the link that was never gone.)
- cancel-via-add: remove a server link, then click Add on that same
  candidate. That click cancels the removal -- it must not stack an
  `add_link` for a link the item already has.
- removal-still-works: the control the bug report must not lose. Remove a
  server link and save: the Save posts exactly one valid `remove_link`,
  the server applies it, the draft clears.
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

# One node spawn; generous for a cold process start on a shared runner (see
# the timeout note in test_vscode_extension.py for why 10 s is not one).
NODE_TIMEOUT_S = 120

HARNESS = r"""
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
    this.value = '';
    this.dataset = {};
    this.disabled = false;
    this.hidden = false;
  }
  set className(v) { this._cls = v; }
  get className() { return this._cls || ''; }
  // the real DOM: assigning textContent replaces every child, '' included
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
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  click() { for (const fn of this.listeners.click || []) fn({}); }
  setSelectionRange() {}
  focus() {}
  select() {}
  querySelectorAll(selector) {
    const [tag, rawcls] = selector.replace(/^([a-z]+)/, (m) => `${m}|`).split('|');
    const cls = (rawcls || '').replace(/^\.+/, '');
    const out = [];
    const walk = (node) => {
      for (const child of node.children) {
        const tagOk = !tag || child.tagName === tag.toUpperCase();
        const clsOk = !cls || (child.className || '').split(/\s+/).includes(cls);
        if (tagOk && clsOk) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
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

function find(node, cls) {
  return findAll(node, cls)[0] || null;
}

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector: (sel) => (sel.includes('refdes-token') ? { content: 'tok' } : null),
};
globalThis.window = { addEventListener: () => {} };

// The candidate list the picker fetches: REQ-001 is the item's server link
// (composite form), REQ-002 is a clean add candidate.
globalThis.fetch = async (path, init) => {
  if (path.startsWith('/api/items')) {
    const items = [
      { id: 'REQ-001', handle: 'REQ-001', key: 'k1', title: 'Rail' },
      { id: 'REQ-002', handle: 'REQ-002', key: 'k2', title: 'Boot' },
    ];
    return { ok: true, status: 200, statusText: 'OK', json: async () => ({ items }) };
  }
  if (path.includes('/edit')) {
    const sent = init && init.body ? JSON.parse(init.body) : null;
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

const posts = [];
let respond = () => ({ ok: true, payload: { revision: 'rev-1' } });

const { createEditor } = await import(url('editor.js'));
const drafts = await import(url('drafts.js'));
let freshCount = 0;
const reloadDrafts = async () =>
  await import(`${url('drafts.js')}?reload=${++freshCount}`); // fresh memory Map, same storage

// DEC-001 links REQ-001 on the server, as the composite write leaves it.
function editItem(handle) {
  return {
    id: handle,
    revision: 'rev-0',
    edit: {
      editable: true,
      file_revision: 'rev-0',
      fields: {},
      body: { editable: true },
      links: {
        satisfies: {
          editable: true,
          targets: ['REQ-001@k1'],
          target_types: ['REQ'],
        },
      },
    },
  };
}

const mirrorOf = (handle) =>
  JSON.parse(
    globalThis.sessionStorage.getItem(`refdes.draft.v1.${encodeURIComponent(handle)}`) ?? 'null'
  );

const snapshot = (draft) => JSON.parse(JSON.stringify(draft.links));
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

function editorFor(handle) {
  let saved = false;
  const editor = createEditor(editItem(handle), handle, () => { saved = true; }, () => {});
  return { editor, saved: () => saved };
}

// the candidate add button whose row labels this target
function candidateAdd(editor, label) {
  return findAll(editor.node, 'link-add').find((b) =>
    (b._parent.textContent || '').startsWith(label)
  );
}

const results = {};

// -- undo-add: a pending add's undo leaves no op on either side
{
  const handle = 'DEC-001';
  posts.length = 0;
  const { editor } = editorFor(handle);
  await tick(20); // the candidates promise
  candidateAdd(editor, 'REQ-002').click();
  const added = drafts.getDraft(handle);
  results.undoAddAfterAdd = { links: snapshot(added), dirty: drafts.isDirty(added) };
  find(findAll(editor.node, 'pending add')[0], 'link-undo').click();
  const after = drafts.getDraft(handle);
  const reloaded = (await reloadDrafts()).getDraft(handle);
  results.undoAdd = {
    links: snapshot(after),
    dirty: drafts.isDirty(after),
    mirror: mirrorOf(handle),
    saveDisabled: find(editor.node, 'save').disabled,
    reloadLinks: snapshot(reloaded),
    reloadDirty: drafts.isDirty(reloaded),
  };
}

// -- the refused Save that the base's bogus op produces (what the author sees)
{
  const handle = 'DEC-001';
  // a draft with a bogus remove, exactly what base's undo left behind
  drafts.draftLinkRemove(handle, 'satisfies', 'REQ-002');
  posts.length = 0;
  respond = () => ({
    ok: false,
    payload: { kind: 'refused', reason: "item DEC-001 does not link REQ-002" },
  });
  const { editor } = editorFor(handle);
  await tick(20);
  find(editor.node, 'save').click();
  await tick(50);
  const reloaded = (await reloadDrafts()).getDraft(handle);
  results.bogusRemoveSave = {
    posts: posts.map((p) => `${p.op} ${p.verb} ${p.target}`),
    reloadLinks: snapshot(reloaded),
    reloadDirty: drafts.isDirty(reloaded),
  };
  drafts.clearDraft(handle);
}

// -- undo-remove: undoing a valid removal returns to the server state
{
  const handle = 'DEC-002';
  posts.length = 0;
  const { editor } = editorFor(handle);
  await tick(20);
  find(editor.node, 'link-remove').click();
  const removed = drafts.getDraft(handle);
  results.undoRemoveAfterRemove = { links: snapshot(removed), dirty: drafts.isDirty(removed) };
  find(findAll(editor.node, 'pending remove')[0], 'link-undo').click();
  const after = drafts.getDraft(handle);
  const reloaded = (await reloadDrafts()).getDraft(handle);
  results.undoRemove = {
    links: snapshot(after),
    dirty: drafts.isDirty(after),
    mirror: mirrorOf(handle),
    reloadDirty: drafts.isDirty(reloaded),
  };
}

// -- cancel-via-add: Add on a server link's candidate cancels the removal
{
  const handle = 'DEC-003';
  const { editor } = editorFor(handle);
  await tick(20);
  find(editor.node, 'link-remove').click();
  const removed = drafts.getDraft(handle);
  results.cancelViaAddAfterRemove = { links: snapshot(removed), dirty: drafts.isDirty(removed) };
  candidateAdd(editor, 'REQ-001').click();
  const after = drafts.getDraft(handle);
  results.cancelViaAdd = { links: snapshot(after), dirty: drafts.isDirty(after) };
}

// -- removal-still-works: the valid removal saves and clears the draft
{
  const handle = 'DEC-004';
  posts.length = 0;
  respond = () => ({ ok: true, payload: { revision: 'rev-1' } });
  const { editor, saved } = editorFor(handle);
  await tick(20);
  find(editor.node, 'link-remove').click();
  find(editor.node, 'save').click();
  await tick(50);
  const reloaded = (await reloadDrafts()).getDraft(handle);
  results.removalSave = {
    posts: posts.map((p) => `${p.op} ${p.verb} ${p.target}`),
    saved: saved(),
    mirror: mirrorOf(handle),
    reloadDirty: drafts.isDirty(reloaded),
  };
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_undo_of_a_pending_link_op_cancels_it_and_keeps_the_draft_clean():
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

    # the pending add really was a pending add
    add = results["undoAddAfterAdd"]
    assert add["links"]["add"] == {"satisfies": ["REQ-002"]} and add["dirty"] is True

    # the core assertion: undo takes the op back -- not the other side
    undo = results["undoAdd"]
    assert undo["links"] == {"add": {}, "remove": {}}, (
        "undo of a pending add left a pending op: the undo button toggles the "
        "target onto the remove side instead of cancelling the add (EDITOR-API-004)"
    )
    assert undo["dirty"] is False
    assert undo["mirror"] is None, "the mirror kept a draft the undo had made clean"
    assert undo["saveDisabled"] is True, "Save is offered on a draft the undo made clean"
    assert undo["reloadLinks"] == {"add": {}, "remove": {}}
    assert undo["reloadDirty"] is False

    # what the bogus op costs the author, on the server the picker targets:
    # a Save of the flipped op is refused and the draft survives it
    save = results["bogusRemoveSave"]
    assert save["posts"] == ["remove_link satisfies REQ-002"]
    assert save["reloadDirty"] is True, (
        "the refused save cleared the draft: the refusal must keep the author's "
        "pending work, which is why a bogus op is sticky"
    )

    # the same defect, mirrored: undo of a valid removal must not mint an add
    rm = results["undoRemoveAfterRemove"]
    assert rm["links"] == {"add": {}, "remove": {"satisfies": ["REQ-001@k1"]}} and rm["dirty"] is True
    undo2 = results["undoRemove"]
    assert undo2["links"] == {"add": {}, "remove": {}}, (
        "undo of a pending remove left a pending add_link for a link the item "
        "already has: the undo button toggles instead of cancelling (EDITOR-API-004)"
    )
    assert undo2["dirty"] is False
    assert undo2["mirror"] is None
    assert undo2["reloadDirty"] is False

    # Add on a server link's candidate is a cancel of the removal, not a new op
    cva = results["cancelViaAdd"]
    assert cva["links"] == {"add": {}, "remove": {}} and cva["dirty"] is False, (
        "clicking Add on the candidate of a pending-removed server link stacked "
        "an add_link for a link the item already has"
    )

    # the control the fix must keep: a valid removal saves, one op, and clears
    good = results["removalSave"]
    assert good["posts"] == ["remove_link satisfies REQ-001@k1"]
    assert good["saved"] is True
    assert good["mirror"] is None
    assert good["reloadDirty"] is False
