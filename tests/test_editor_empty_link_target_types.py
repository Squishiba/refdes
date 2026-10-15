"""A verb declared with an empty target-type list is UNRESTRICTED -- in the
server and, to the point, in the picker.

The server's reading of `links: {verb: []}` is "any declared type", in three
places that all say it the same way: `Project.accepts_type` (model.py, "an
empty list is unrestricted"), `build.resolve_links` (skips the type check
under `if allowed and ...`), and the editor's own gate in
`serve.edit._resolve_link_op` (refuses with "accepts any declared type",
and -- verified live against a server on this tree -- applies
`add_link blocked_by REQ-001` for a verb declared `blocked_by: []`, writing
the composite). The standard itself declares exactly such a verb:
`log.links.blocked_by: []` in hardware@3's base.yaml.

The picker read the same empty list as "no candidates". `links.js`
`candidatesFor` loops the declared types to build its per-type `/api/items`
queries; with `target_types: []` it issued no request at all and the verb
rendered "no candidates match" -- a picker offering nothing for a link the
server accepts to every item in the project (EDITOR-API-006).

Two halves, one per side of the seam:

- HTTP (green before the fix, pinning the contract the UI must mirror):
  `GET /api/item/<ref>` reports the empty-verb as editable with
  `target_types: []`, and `POST .../edit` applies an add of any type.
- Node, the REAL served modules (red before the fix): with `target_types: []`
  the picker must fetch the unfiltered list and offer every item as a
  candidate, and clicking Add must draft the add; a verb with declared types
  must keep fetching exactly those types and offering exactly their items.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import keys as keys_mod
from refdes.serve.server import EditorApp

# --------------------------------------------------------------------------
# half one: the server accepts what it says it accepts
# --------------------------------------------------------------------------

SCHEMA = """\
site:
  title: "Empty target types"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  blocked_by: { inverse: blocking, label: Blocked by }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
    links:
      blocked_by: []
"""

K_REQ1 = keys_mod.mint()

REQS = f"""\
defaults: {{ type: requirement, board: board-a }}
items:
  - id: REQ-001
    key: {K_REQ1}
    text: The rail shall supply 3.3 V.
"""

LOG = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    summary: Started the rail work.
"""


def log_file(root) -> str:
    return str(root / "items" / "log.yaml")


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@pytest.fixture
def served(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "reqs.yaml").write_text(REQS, encoding="utf-8", newline="\n")
    (items / "log.yaml").write_text(LOG, encoding="utf-8", newline="\n")
    app = EditorApp(str(tmp_path / "refdes-project.yaml"), poll_interval=60)
    app.start()
    try:
        yield Client(app), tmp_path
    finally:
        app.stop()


def test_an_empty_target_list_is_editable_and_reported_empty(served):
    client, _root = served
    status, payload = client.api_get("/api/item/LOG-001")
    assert status == 200
    verbs = payload["edit"]["links"]
    assert set(verbs) == {"blocked_by"}
    assert verbs["blocked_by"] == {"editable": True, "target_types": [], "targets": []}


def test_the_server_applies_an_add_of_any_type_under_an_empty_list(served):
    client, root = served
    status, payload = client.api_post(
        "/api/item/LOG-001/edit",
        {
            "op": "add_link",
            "verb": "blocked_by",
            "target": "REQ-001",
            "expected_revision": sha256(log_file(root)),
        },
        origin="default",
    )
    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["ok"] is True
    with open(log_file(root), encoding="utf-8") as fh:
        assert f"blocked_by: REQ-001@{K_REQ1}" in fh.read()


# --------------------------------------------------------------------------
# half two: the picker must offer what the server accepts
# --------------------------------------------------------------------------

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "refdes", "serve", "static"
)

NODE = shutil.which("node")

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

function findAll(node, cls) {
  const out = [];
  const tokens = (node.className || '').split(/\s+/);
  if (tokens.includes(cls)) out.push(node);
  for (const child of node.children) out.push(...findAll(child, cls));
  return out;
}

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector: (sel) => (sel.includes('refdes-token') ? { content: 'tok' } : null),
};
globalThis.window = { addEventListener: () => {} };

// Three items, one per type: an unrestricted picker must offer ALL of
// them; a verb declaring `requirement` must offer exactly REQ-001.
const ALL = [
  { id: 'REQ-001', handle: 'REQ-001', key: 'k1', title: 'Rail', type: 'requirement' },
  { id: 'DEC-001', handle: 'DEC-001', key: 'k2', title: 'Buck', type: 'decision' },
  { id: 'LOG-001', handle: 'LOG-001', key: 'k3', title: 'Start', type: 'log' },
];

const fetchCalls = [];

globalThis.fetch = async (path) => {
  if (path === '/api/items' || path.startsWith('/api/items?')) {
    fetchCalls.push(path);
    const m = /(^|\?)type=([^&]+)/.exec(path);
    const items = m ? ALL.filter((r) => r.type === decodeURIComponent(m[2])) : ALL;
    return { ok: true, status: 200, statusText: 'OK', json: async () => ({ items }) };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) };
};

const { createEditor } = await import(url('editor.js'));
const drafts = await import(url('drafts.js'));

const tick = (ms) => new Promise((r) => setTimeout(r, ms));
const snapshot = (draft) => JSON.parse(JSON.stringify(draft.links));

function editItem(links) {
  return {
    id: 'X',
    revision: 'rev-0',
    edit: {
      editable: true,
      file_revision: 'rev-0',
      fields: {},
      body: { editable: true },
      links,
    },
  };
}

function candidateLabels(editor) {
  // the candidate row is [span.link-target, button.link-add]: label from the
  // span, since the row's full textContent also carries the button text
  return findAll(editor.node, 'link-add').map(
    (b) => (b._parent.children[0] || {}).textContent || ''
  );
}

const results = {};

// -- unrestricted: a verb declared with `target_types: []` must offer every
//    item (the server accepts a link to any of them), and Add must draft.
{
  const handle = 'LOG-001';
  fetchCalls.length = 0;
  const editor = createEditor(
    editItem({ blocked_by: { editable: true, target_types: [], targets: [] } }),
    handle, () => {}, () => {},
  );
  await tick(20); // the candidates promise
  results.unrestrictedCalls = fetchCalls.filter((p) => p.startsWith('/api/items'));
  results.unrestrictedCandidates = candidateLabels(editor);
  const add = findAll(editor.node, 'link-add').find(
    (b) => (b._parent.textContent || '').startsWith('REQ-001')
  );
  if (add) {
    add.click();
    results.unrestrictedAdd = snapshot(drafts.getDraft(handle)).add;
  } else {
    results.unrestrictedAdd = null;
  }
}

// -- restricted control: a verb declaring its types keeps the filtered
//    per-type fetch and offers exactly those items, and nothing else.
{
  const handle = 'DEC-001';
  fetchCalls.length = 0;
  const editor = createEditor(
    editItem({ satisfies: { editable: true, target_types: ['requirement'], targets: [] } }),
    handle, () => {}, () => {},
  );
  await tick(20);
  results.restrictedCalls = fetchCalls.filter((p) => p.startsWith('/api/items'));
  results.restrictedCandidates = candidateLabels(editor);
}

console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served editor modules")
def test_the_picker_offers_every_item_for_an_unrestricted_verb():
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

    assert results["unrestrictedCalls"] == ["/api/items"], (
        "an unrestricted verb (target_types: []) must fetch the unfiltered "
        f"/api/items; the picker fetched {results['unrestrictedCalls']!r} "
        "(it loops the declared types and issues nothing for an empty list)"
    )
    assert results["unrestrictedCandidates"] == [
        "DEC-001 — Buck",
        "LOG-001 — Start",
        "REQ-001 — Rail",
    ], (
        "the picker offered no candidates for a verb the server accepts to "
        "every type -- an empty target list is unrestricted, not empty "
        "(EDITOR-API-006)"
    )
    assert results["unrestrictedAdd"] == {"blocked_by": ["REQ-001"]}, (
        "clicking Add on an unrestricted verb's candidate must draft the add"
    )

    assert results["restrictedCalls"] == ["/api/items?type=requirement"]
    assert results["restrictedCandidates"] == ["REQ-001 — Rail"], (
        "a verb declaring target types must keep offering exactly the items "
        "of the declared types -- the fix must not widen the filtered path"
    )
