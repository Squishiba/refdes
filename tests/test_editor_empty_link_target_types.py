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
  candidate -- except the item being edited, which the picker never offers
  (a self-link is not a choice to make from a list) -- and clicking Add
  must draft the add; a verb with declared types must keep fetching exactly
  those types and offering exactly their items.
  The list API caps at a page of rows (`filters.py`: default 500, max 5000),
  so the picker must ask for the full page -- a 600-item project must offer
  all 600, not a silently truncated 500 -- and must say so honestly when
  even the full page truncates: a project past the cap shows the fetched
  rows plus a "showing the first N of M" line that names the filter's
  limit (it searches only the fetched rows), never a list that hides the
  gap or promises a remedy it cannot deliver.
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

# 600 requirements: past the list API's default page of 500, so the pins
# below prove the cap is real server behavior (the picker must page for it).
REQS = (
    "defaults: { type: requirement, board: board-a }\n"
    "items:\n"
    + "".join(
        f"  - id: REQ-{n:03d}\n"
        + (f"    key: {K_REQ1}\n" if n == 1 else "")
        + f"    text: Requirement number {n}.\n"
        for n in range(1, 601)
    )
)

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


def test_the_items_list_pages_at_500_and_honors_the_max_page(served):
    # The cap the picker must plan around (600 requirements in this fixture):
    # an unpaginated GET /api/items hands back 500 with total 600; the page
    # of MAX_LIMIT=5000 the picker asks for covers the whole project.
    client, _root = served
    status, payload = client.api_get("/api/items")
    assert status == 200
    assert payload["total"] == 601 and payload["limit"] == 500  # 600 REQ + 1 LOG
    assert len(payload["items"]) == 500
    status, payload = client.api_get("/api/items?limit=5000")
    assert status == 200
    assert payload["limit"] == 5000 and len(payload["items"]) == 601


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
// them except the item under edit; a verb declaring `requirement` must
// offer exactly REQ-001.
const ALL = [
  { id: 'REQ-001', handle: 'REQ-001', key: 'k1', title: 'Rail', type: 'requirement' },
  { id: 'DEC-001', handle: 'DEC-001', key: 'k2', title: 'Buck', type: 'decision' },
  { id: 'LOG-001', handle: 'LOG-001', key: 'k3', title: 'Start', type: 'log' },
];

// The list API caps its payload at one page (serve/filters.py: DEFAULT_LIMIT
// 500, MAX_LIMIT 5000; api.py applies parse_limit). The stub mirrors that:
// no limit param means the default 500, limit slices the match, and `total`
// is always the FULL match count -- the picker must ask for the full page
// and must not hide a truncation.
let UNIVERSE = ALL;

const fetchCalls = [];

globalThis.fetch = async (path) => {
  if (path === '/api/items' || path.startsWith('/api/items?')) {
    fetchCalls.push(path);
    const params = new URLSearchParams(path.includes('?') ? path.split('?')[1] : '');
    const type = params.get('type');
    const cap = params.has('limit') ? Number(params.get('limit')) : 500;
    const matched = type ? UNIVERSE.filter((r) => r.type === type) : UNIVERSE;
    const items = matched.slice(0, cap);
    return {
      ok: true, status: 200, statusText: 'OK',
      json: async () => ({ items, total: matched.length, limit: cap }),
    };
  }
  return { ok: true, status: 200, statusText: 'OK', json: async () => ({}) };
};

const { createEditor } = await import(url('editor.js'));
const drafts = await import(url('drafts.js'));

const tick = (ms) => new Promise((r) => setTimeout(r, ms));
const snapshot = (draft) => JSON.parse(JSON.stringify(draft.links));

function editItem(links, self) {
  // self: id/key of the item under edit, so the picker can recognize it
  // among the candidate rows (the item view the API serves carries both).
  return {
    id: 'X',
    revision: 'rev-0',
    ...(self || {}),
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

function findMuted(editor) {
  return findAll(editor.node, 'muted').map((n) => n.textContent).filter((t) => t.startsWith('showing'));
}

const results = {};

// -- unrestricted: a verb declared with `target_types: []` must offer every
//    item (the server accepts a link to any of them) EXCEPT the item under
//    edit, and Add must draft.
{
  const handle = 'LOG-001';
  UNIVERSE = ALL;
  fetchCalls.length = 0;
  const editor = createEditor(
    editItem(
      { blocked_by: { editable: true, target_types: [], targets: [] } },
      { id: 'LOG-001', key: 'k3' }
    ),
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
  UNIVERSE = ALL;
  fetchCalls.length = 0;
  const editor = createEditor(
    editItem({ satisfies: { editable: true, target_types: ['requirement'], targets: [] } }),
    handle, () => {}, () => {},
  );
  await tick(20);
  results.restrictedCalls = fetchCalls.filter((p) => p.startsWith('/api/items'));
  results.restrictedCandidates = candidateLabels(editor);
  results.restrictedNotice = findMuted(editor);
}

// -- big project (600 items > the default page of 500): the picker must ask
//    for the full page and offer ALL 600, not a silently truncated 500.
{
  const handle = 'DEC-002';
  UNIVERSE = Array.from({ length: 600 }, (_, i) => ({
    id: `REQ-${String(i + 1).padStart(4, '0')}`,
    handle: `REQ-${String(i + 1).padStart(4, '0')}`,
    key: `q${i}`, title: `R${i}`, type: 'requirement',
  }));
  fetchCalls.length = 0;
  const editor = createEditor(
    editItem({ refines: { editable: true, target_types: ['requirement'], targets: [] } }),
    handle, () => {}, () => {},
  );
  await tick(50);
  results.bigCalls = fetchCalls.filter((p) => p.startsWith('/api/items'));
  results.bigCandidateCount = findAll(editor.node, 'link-add').length;
  results.bigNotice = findMuted(editor);
}

// -- past the cap (6000 items > MAX_LIMIT page of 5000): the fetched page is
//    the whole offer, and the picker says so -- "showing N of M" -- instead
//    of presenting a list that silently hides 1000 valid targets.
{
  const handle = 'DEC-003';
  UNIVERSE = Array.from({ length: 6000 }, (_, i) => ({
    id: `REQ-${String(i + 1).padStart(5, '0')}`,
    handle: `REQ-${String(i + 1).padStart(5, '0')}`,
    key: `q${i}`, title: `R${i}`, type: 'requirement',
  }));
  fetchCalls.length = 0;
  const editor = createEditor(
    editItem({ refines: { editable: true, target_types: ['requirement'], targets: [] } }),
    handle, () => {}, () => {},
  );
  await tick(100);
  results.cappedCandidateCount = findAll(editor.node, 'link-add').length;
  results.cappedNotice = findMuted(editor);
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
        encoding="utf-8",  # the harness labels carry an em dash; node writes
        # UTF-8 and the Windows default (cp1252) mangles it in CI
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    results = json.loads(proc.stdout.strip().splitlines()[-1])

    assert results["unrestrictedCalls"] == ["/api/items?limit=5000"], (
        "an unrestricted verb (target_types: []) must fetch the unfiltered "
        f"/api/items at the full page; the picker fetched {results['unrestrictedCalls']!r} "
        "(it loops the declared types and issues nothing for an empty list)"
    )
    assert results["unrestrictedCandidates"] == [
        "DEC-001 — Buck",
        "REQ-001 — Rail",
    ], (
        "the picker offered no candidates (or offered the item under edit) "
        "for a verb the server accepts to every type -- an empty target "
        "list is unrestricted, not empty (EDITOR-API-006), and the picker "
        "must not offer a self-link"
    )
    assert results["unrestrictedAdd"] == {"blocked_by": ["REQ-001"]}, (
        "clicking Add on an unrestricted verb's candidate must draft the add"
    )

    assert results["restrictedCalls"] == ["/api/items?limit=5000&type=requirement"]
    assert results["restrictedCandidates"] == ["REQ-001 — Rail"], (
        "a verb declaring target types must keep offering exactly the items "
        "of the declared types -- the fix must not widen the filtered path"
    )
    assert results["restrictedNotice"] == []

    # 600 matching items > the default page of 500: the picker must ask for
    # the full page and offer all of them -- silently offering 500 of 600
    # valid targets is the same hiding-the-gap defect, in pages (review of
    # PR #267, finding 1).
    assert results["bigCalls"] == ["/api/items?limit=5000&type=requirement"]
    assert results["bigCandidateCount"] == 600, (
        "the picker silently truncated its candidate list at the default "
        f"page of 500: it offered {results['bigCandidateCount']} of 600 items"
    )
    assert results["bigNotice"] == []

    # past even the full page (6000 > MAX_LIMIT 5000): the fetched page is
    # the whole offer and the picker says so, instead of presenting a list
    # that hides 1000 valid targets. The wording must be honest about what
    # the author can still do: the filter searches only the fetched rows
    # (renderCandidates matches over `all`), so it must not promise that
    # filtering reaches the rows past the cap (review of PR #267, round 2,
    # finding 1).
    assert results["cappedCandidateCount"] == 5000
    assert results["cappedNotice"] == [
        "showing the first 5000 of 6000 targets -- the filter searches only these"
    ], (
        "a truncated candidate list must say so, and say it honestly: the "
        "filter only searches the fetched rows, so a notice that suggests "
        "filtering reaches the rest is a false remedy"
    )
