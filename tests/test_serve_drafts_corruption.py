"""EDITOR-DRAFT-003: a corrupt draft mirror must never read as a clean draft.

The one real check on drafts.js semantics: node imports the actual ES module
(no build step, no re-implementation) with stubbed ``window``,
``sessionStorage`` and a small fake ``document``, and drives it the way the
editor page does. Before the fix, ``load()`` wrapped the storage read and
``JSON.parse`` in one try, so a truncated mirror silently returned
``emptyDraft()``: ``isDirty`` false, no prompt on close, no console line --
unsaved work indistinguishable from no work.

Like the VS Code extension's ``node --check`` test, this skips when node is
not on PATH (CI installs no node); it bites on dev machines.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFTS_JS = os.path.join(
    REPO_ROOT, "src", "refdes", "serve", "static", "drafts.js"
)
HANDLE = "widget-w-001"
DRAFT_KEY = "refdes.draft.v1.widget-w-001"
CORRUPT_KEY = "refdes.draft.corrupt.v1.widget-w-001"
TRUNCATED = '{"revision":"r7","fields":{"title":"X"},"body":"half a d'

HARNESS = """
import { pathToFileURL } from 'node:url';
const [draftsPath, scenario, seedJson] = process.argv.slice(2);
const { handle, storage } = JSON.parse(seedJson);

const store = new Map(Object.entries(storage));
const listeners = {};
const warnings = [];

globalThis.sessionStorage = {
  getItem: (k) => {
    if (scenario === 'unavailable') throw new Error('SecurityError: storage blocked');
    return store.has(k) ? store.get(k) : null;
  },
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
};
globalThis.window = {
  addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
};

class FakeNode {
  constructor(tag) {
    this.tag = tag; this.className = ''; this.children = [];
    this.ownText = ''; this.attrs = {}; this.handlers = {}; this.parent = null;
  }
  get textContent() { return this.ownText; }
  set textContent(t) { this.children = []; this.ownText = String(t); }
  setAttribute(k, v) { this.attrs[k] = v; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  prepend(child) { child.parent = this; this.children.unshift(child); return child; }
  removeChild(child) {
    this.children = this.children.filter((c) => c !== child); child.parent = null;
  }
  remove() { if (this.parent) this.parent.removeChild(this); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  click() { for (const fn of this.handlers.click || []) fn({}); }
  allText() {
    return [this.ownText, ...this.children.map((c) => c.allText())].filter(Boolean).join(' ');
  }
  findButton() {
    if (this.tag === 'button') return this;
    for (const child of this.children) { const hit = child.findButton(); if (hit) return hit; }
    return null;
  }
}
const body = new FakeNode('body');
globalThis.document = { body, createElement: (tag) => new FakeNode(tag) };
const realWarn = console.warn;
console.warn = (...args) => { warnings.push(args.join(' ')); };

const drafts = await import(pathToFileURL(draftsPath).href);

function snapshot() {
  const draft = drafts.getDraft(handle);
  const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  for (const fn of listeners.beforeunload || []) fn(event);
  return {
    draft,
    isDirty: drafts.isDirty(draft),
    hasAnyDraft: drafts.hasAnyDraft(),
    corrupt: drafts.corruptDraft(handle),
    prompted: event.defaultPrevented,
    banners: body.children.map((b) => ({ cls: b.className, text: b.allText() })),
    warnings: [...warnings],
    storage: Object.fromEntries(store),
  };
}

let result = snapshot();
if (scenario === 'discard') {
  const button = body.children[0] && body.children[0].findButton();
  if (button) button.click();
  result = { corrupted: result, afterDiscard: snapshot() };
}
console.warn = realWarn;
process.stdout.write(JSON.stringify(result));
"""


def _run(tmp_path, scenario: str, storage: dict, handle: str = HANDLE) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    seed = json.dumps({"handle": handle, "storage": storage})
    proc = subprocess.run(
        [node, str(harness), DRAFTS_JS, scenario, seed],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_truncated_mirror_is_preserved_and_never_reads_clean(tmp_path):
    result = _run(tmp_path, "corrupt", {DRAFT_KEY: TRUNCATED})
    # editing still works: the page opens on a fresh, clean draft...
    assert result["draft"] == {
        "revision": None, "fields": {}, "body": None, "pins": [],
        "links": {"add": {}, "remove": {}},
    }
    # ...but the damage is named, not swallowed: raw bytes + a reason
    assert result["corrupt"] is not None, "the corrupt mirror was not reported"
    assert result["corrupt"]["raw"] == TRUNCATED
    assert result["corrupt"]["reason"]
    # the bytes are recoverable for the whole tab session, not just this page
    assert result["storage"][CORRUPT_KEY] == TRUNCATED
    # a tab close asks, because preserved evidence of unsaved work IS unsaved work
    assert result["hasAnyDraft"] is True
    assert result["prompted"] is True
    # and the user sees it: a visible banner naming the recovery key
    assert len(result["banners"]) == 1
    assert "bad" in result["banners"][0]["cls"]
    assert CORRUPT_KEY in result["banners"][0]["text"]
    assert any(HANDLE in line for line in result["warnings"])


def test_corrupt_mirror_is_still_corrupt_after_a_reload(tmp_path):
    """Reload = a fresh process (fresh module state, fresh page) over the same
    sessionStorage bytes: the mirror must still be reported, not read as clean."""
    first = _run(tmp_path, "corrupt", {DRAFT_KEY: TRUNCATED})
    second = _run(tmp_path, "corrupt", first["storage"])
    assert second["corrupt"] is not None
    assert second["corrupt"]["raw"] == TRUNCATED
    assert second["hasAnyDraft"] is True and second["prompted"] is True
    assert len(second["banners"]) == 1
    assert second["storage"][CORRUPT_KEY] == TRUNCATED


def test_discarding_the_mirror_is_an_explicit_user_release(tmp_path):
    result = _run(tmp_path, "discard", {DRAFT_KEY: TRUNCATED})
    assert result["corrupted"]["corrupt"] is not None
    after = result["afterDiscard"]
    assert after["corrupt"] is None
    assert CORRUPT_KEY not in after["storage"]
    assert after["hasAnyDraft"] is False
    assert after["prompted"] is False
    assert after["banners"] == []


def test_valid_draft_control(tmp_path):
    valid = json.dumps({
        "revision": "r7", "fields": {"title": "X"}, "body": "b", "pins": [],
        "links": {"add": {"rel": ["a"]}, "remove": {}},
    })
    result = _run(tmp_path, "corrupt", {DRAFT_KEY: valid})
    assert result["draft"]["revision"] == "r7"
    assert result["draft"]["fields"] == {"title": "X"}
    assert result["draft"]["body"] == "b"
    assert result["draft"]["links"] == {"add": {"rel": ["a"]}, "remove": {}}
    assert result["corrupt"] is None
    assert result["banners"] == []
    assert result["warnings"] == []
    assert CORRUPT_KEY not in result["storage"]
    # a restored draft IS unsaved work: the close prompt arms, the mirror stays put
    assert result["isDirty"] is True
    assert result["prompted"] is True
    assert result["storage"][DRAFT_KEY] == valid


def test_no_draft_control(tmp_path):
    result = _run(tmp_path, "corrupt", {})
    assert result["draft"] == {
        "revision": None, "fields": {}, "body": None, "pins": [],
        "links": {"add": {}, "remove": {}},
    }
    assert result["isDirty"] is False
    assert result["hasAnyDraft"] is False
    assert result["prompted"] is False
    assert result["corrupt"] is None
    assert result["banners"] == []
    assert result["warnings"] == []
    assert result["storage"] == {}


@pytest.mark.parametrize("raw", ["null", "[1, 2]", '"just a string"', "42"])
def test_mirrors_that_parse_but_are_not_drafts_are_corrupt(tmp_path, raw):
    result = _run(tmp_path, "corrupt", {DRAFT_KEY: raw})
    assert result["corrupt"] is not None, f"{raw!r} read as a clean draft"
    assert result["corrupt"]["raw"] == raw
    assert result["storage"][CORRUPT_KEY] == raw
    assert result["hasAnyDraft"] is True and result["prompted"] is True
    assert len(result["banners"]) == 1


def test_unreachable_storage_still_costs_persistence_not_editing(tmp_path):
    """Private mode / blocked storage is the silent path the module documents:
    no mirror can be read OR preserved, so there is nothing to report."""
    result = _run(tmp_path, "unavailable", {DRAFT_KEY: TRUNCATED})
    assert result["draft"]["fields"] == {}
    assert result["corrupt"] is None
    assert result["banners"] == []
    assert result["warnings"] == []
    assert result["isDirty"] is False and result["prompted"] is False
