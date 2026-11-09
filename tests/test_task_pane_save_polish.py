"""W5b.4c-2b polish (from the #474 review): two defects in the save seam.

1. ``taskpane-save.js`` Copy-it-out calls ``navigator.clipboard.writeText``,
   which RETURNS A PROMISE. The surrounding ``try/catch`` catches only a
   synchronous throw, so a permission-DENIED rejection -- the common real
   case in a browser (the prompt refused, a non-secure origin) -- surfaces
   as an ``unhandledRejection``, a page-level error the pane must never
   cause. The contract is "a refused clipboard costs the copy, never the
   pane": the rejection is swallowed, the read-only textarea stands, and
   the synchronous path (no clipboard API at all) keeps working exactly as
   the W5b.4c-2b pins leave it.

2. The stale-choice race in ``showConflict``: the Keep-mine handler closes
   over ``choices`` computed when the conflict panel was SHOWN. Ticks the
   author changes in the draft AFTER the panel appeared (the panel stands
   while the author keeps editing) are lost: keep-mine discards the draft
   and re-stamps the OLD pairs. Keep mine must keep the CURRENT draft --
   the pairs are read at CLICK time -- and the three ratified outcomes and
   "nothing merges" are unchanged.

The same node-harness posture as tests/test_task_pane_save_ui.py (which is
NOT edited): plain FakeNode DOM from ``document.createElement``, a fetch
recording (url, init) with scripted answers, a location counting reloads, a
``navigator.clipboard`` the scenario can make reject, a DOMParser stub that
reads ``data-refdes-*`` out of the page text, and a top-level
``process.on('unhandledRejection')`` recorder (a listener suppresses node's
default crash, so the harness exits 0 and RECORDS what the module leaked).

This is the honest headless slice: no layout, no CSS, no real event
dispatch, no real clipboard permission prompt. The real-browser behaviour
(Chromium/Firefox prompts, rendering) is verified by the lead, not here.

Red today, green after the fix:

  test_a_refused_clipboard_rejection_is_swallowed_and_the_textarea_stands  RED
  test_keep_mine_keeps_the_ticks_added_while_the_panel_stood_open          RED
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(REPO_ROOT, "src", "refdes", "serve", "static")

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120

HARNESS = """
const STATIC = __STATIC__;
const PAGE = __PAGE__;
const url = (name) => `file://${STATIC}/${name}`;

// The seam's contract under test (1): a rejection the module does not
// handle is RECORDED here. A process listener suppresses node's default
// crash, so the harness exits 0 and the scenario shows what leaked.
const unhandled = [];
process.on('unhandledRejection', (reason) => {
  unhandled.push(String(reason && reason.message ? reason.message : reason));
});

// -- the fake page, the same posture as tests/test_task_pane_save_ui.py
class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.parentNode = null;
    this.listeners = {};
    this._text = "";
    this.type = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.readOnly = false;
    this.value = "";
    this.checked = false;
  }
  get parentElement() { return this.parentNode; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this.children.length
      ? this.children.map((c) => c.textContent).join("")
      : this._text;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] === undefined ? null : this.attrs[name]; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  insertBefore(child, ref) {
    child.parentNode = this;
    const at = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(at < 0 ? this.children.length : at, 0, child);
    return child;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
  }
  fire(type) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {} }); }
  querySelectorAll(sel) {
    const out = [];
    const want = (node) => {
      if (sel.startsWith(".") && node.className.split(/\\s+/).includes(sel.slice(1))) out.push(node);
      if (sel.startsWith("[") && node.getAttribute(sel.slice(1, -1)) !== null) out.push(node);
      if (sel === "button" && node.tagName === "BUTTON") out.push(node);
    };
    const walk = (node) => { want(node); for (const c of node.children) walk(c); };
    walk(this);
    return out;
  }
  click() { for (const fn of this.listeners.click || []) fn({ preventDefault() {} }); }
}

const store = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const TOKEN = "tok-1";
globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  querySelector(sel) {
    if (sel.includes("refdes-token")) return { content: TOKEN };
    return null;
  },
  querySelectorAll: () => [],
};
globalThis.window = { addEventListener: () => {} };

let reloads = 0;
globalThis.location = {
  href: "http://127.0.0.1:8123/preview/log-002.html",
  reload() { reloads += 1; },
};

const copies = [];
// node >= 21 ships a real `navigator` global with a getter-only slot, so a
// plain assignment throws; defineProperty replaces the slot honestly.
Object.defineProperty(globalThis, "navigator", {
  value: { clipboard: { writeText: async (t) => { copies.push(String(t)); } } },
  configurable: true,
  writable: true,
});

const posts = [];
const gets = [];
let queue = []; // scripted answers for the POSTs, in order: {status, json, text, throws}
let pageText = PAGE;
globalThis.fetch = async (path, init) => {
  const method = (init && init.method) || "GET";
  const headers = (init && init.headers) || {};
  if (method === "POST") {
    posts.push({ url: String(path), method, body: init && init.body ? JSON.parse(init.body) : null });
    const next = queue.shift();
    if (!next) throw new Error("harness: no scripted POST answer left");
    if (next.throws) throw new Error("transport down");
    return {
      ok: next.status === 200,
      status: next.status,
      json: async () => next.json,
      text: async () => next.text === undefined ? "" : next.text,
    };
  }
  gets.push({ url: String(path), method });
  return { ok: true, status: 200, text: async () => pageText };
};

class FakeParsedDoc {
  constructor(text) { this.text = text; }
  querySelectorAll(sel) {
    if (sel !== ".refdes-taskpane-panel") return [];
    const tags = [...this.text.matchAll(/<div class="refdes-taskpane-panel"[^>]*>[\\s\\S]*?(?=<div class="refdes-taskpane-panel"|<\\/aside>)/g)];
    return tags.map((m) => {
      const panel = new FakeNode("div");
      panel.className = "refdes-taskpane-panel";
      for (const a of m[0].matchAll(/([\\w-]+)="([^"]*)"/g)) panel.setAttribute(a[1], a[2]);
      panel.querySelectorAll = (inner) => {
        if (inner !== "input[data-refdes-task]") return [];
        return [...m[0].matchAll(/<input[^>]*data-refdes-task="[^"]*"[^>]*>/g)].map((im) => {
          const box = new FakeNode("input");
          for (const a of im[0].matchAll(/([\\w-]+)="([^"]*)"/g)) box.setAttribute(a[1], a[2]);
          box.checked = /checked=/.test(im[0]);
          return box;
        });
      };
      return panel;
    });
  }
}
globalThis.DOMParser = class {
  parseFromString(text, type) { return new FakeParsedDoc(text); }
};

const { createTickDrafts } = await import(url("tick-drafts.js"));
const { initSave } = await import(url("taskpane-save.js"));

function freshPanel(tipKey, revision) {
  const drafts = createTickDrafts(globalThis.sessionStorage);
  const panelEl = new FakeNode("div");
  panelEl.className = "refdes-taskpane-panel";
  panelEl.setAttribute("data-refdes-tip-key", tipKey);
  panelEl.setAttribute("data-refdes-revision", revision);
  const status = panelEl.appendChild(new FakeNode("p"));
  status.className = "refdes-taskpane-tick-status";
  return { drafts, panelEl, entry: { tipKey, revision, canDraft: true, panelEl, status } };
}

function findButton(root, cls) {
  return root.querySelectorAll("." + cls).filter((n) => n.tagName === "BUTTON")[0] || null;
}
function findClass(root, cls) {
  return root.querySelectorAll("." + cls)[0] || null;
}
function buttonsIn(root) {
  const labels = [];
  const walk = (node) => {
    if (node.tagName === "BUTTON") labels.push(node.textContent);
    for (const c of node.children) walk(c);
  };
  walk(root);
  return labels;
}
const TIP = "KEY-A";
const REV = "REV-0";
const CONFLICT_409 = {
  status: 409,
  json: {
    kind: "conflict", ok: false, message: "conflict: the file moved",
    path: "items/log.yaml", expected_revision: REV, current_revision: "REV-9",
    current_text: "raw", diff: "",
  },
};
const settle = () => new Promise((r) => setTimeout(r, 80));

const results = { ok: true };

async function scenario(name, run) {
  // each scenario is its OWN TAB: a fresh mirror, like a fresh page
  store.clear();
  posts.length = 0; gets.length = 0; copies.length = 0;
  reloads = 0; queue = []; pageText = PAGE;
  try {
    results[name] = JSON.parse(JSON.stringify(await run()));
  } catch (err) { results[name] = { harnessError: String(err && err.stack || err) }; }
}

// -- (1) a clipboard that REJECTS asynchronously: the pane must leak no
// unhandledRejection, and the read-only textarea must still stand.
await scenario("refusedClipboard", async () => {
  const honest = navigator.clipboard.writeText;
  navigator.clipboard.writeText = (t) => {
    copies.push(String(t)); // the copy was TRIED
    return Promise.reject(new Error("PermissionDeniedError: the page was denied clipboard access"));
  };
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setTick(TIP, "T-beta", "open", "done");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change");
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [CONFLICT_409];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  const button = panel.children.filter((c) => c.tagName === "BUTTON" && c.textContent === "Copy it out")[0];
  button.click();
  await settle();
  await settle(); // let any rejection that escaped the module reach the recorder
  navigator.clipboard.writeText = honest;
  let box = null;
  const walk = (node) => { if (node.tagName === "TEXTAREA") box = box || node; for (const c of node.children) walk(c); };
  walk(panelEl);
  return {
    textarea: box ? box.value : null,
    readOnly: box ? box.readOnly === true : null,
    copies,
    unhandled: unhandled.slice(),
    reloads,
    pending: drafts.pendingCount(TIP),
  };
});

// -- (2) the stale-choice race: a tick added to the draft WHILE the conflict
// panel stands is kept by Keep mine (the pairs are the CURRENT draft, read
// at click time), on the CURRENT tip key and revision, and nothing merges.
await scenario("lateTick", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setTick(TIP, "T-beta", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change");
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [CONFLICT_409];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  const buttons = buttonsIn(panel);
  // the author keeps editing WHILE THE PANEL STANDS: T-gamma is a row of
  // the CURRENT page (it is in PAGE below), so Keep mine must keep it too
  drafts.setTick(TIP, "T-gamma", "done", "open");
  const mine = panel.children.filter((c) => c.tagName === "BUTTON" && c.textContent === "Keep mine")[0];
  mine.click();
  await settle();
  return {
    buttons,
    reloaded: reloads,
    revision: drafts.revision(TIP),
    ticks: drafts.pendingTicks(TIP),
  };
});

results.unhandledAtExit = unhandled.slice();
console.log(JSON.stringify(results));
"""

# The current page the DOMParser stub reads: the tip moved (REV-9), T-beta
# is gone, T-gamma joined -- the same fixture the 4c-2b scenarios use.
PAGE = (
    "<html><body>"
    '<div class="refdes-taskpane-panel" data-refdes-tip-key="KEY-A" data-refdes-revision="REV-9">'
    '<input data-refdes-task="T-alpha" data-refdes-task-state="open" data-refdes-tick-states="done,dropped">'
    '<input data-refdes-task="T-gamma" data-refdes-task-state="open" data-refdes-tick-states="done,dropped" checked="checked">'
    "</div></aside></body></html>"
)


@pytest.fixture(scope="module")
def node_results():
    if NODE is None:
        return {"__skipped__": "no node on PATH to run the served save module"}
    script = HARNESS.replace("__STATIC__", json.dumps(STATIC_DIR.replace(os.sep, "/"))).replace(
        "__PAGE__", json.dumps(PAGE)
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        return {"__red__": f"node exited {proc.returncode}:\n{proc.stderr[-4000:]}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"__red__": f"node printed no results:\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}"}


def _scenario(node_results, name):
    if "__skipped__" in node_results:
        pytest.skip(node_results["__skipped__"])
    if "__red__" in node_results:
        pytest.fail("RED today: the seam does not run under node.\n" + node_results["__red__"])
    assert name in node_results, f"the harness reported no {name!r} scenario"
    got = node_results[name]
    assert "harnessError" not in got, got["harnessError"]
    return got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_refused_clipboard_rejection_is_swallowed_and_the_textarea_stands(node_results):
    """RED today: writeText's REJECTION (not a synchronous throw) is the real
    browser case -- the permission prompt refused. The promise rejection
    escapes the module's try/catch and surfaces as an unhandledRejection, a
    page-level error the pane must never cause. Green means: the recorder
    caught NOTHING, the transcript textarea stands (read-only, my lines in
    my order), the copy was tried, and nothing reloaded: a refused clipboard
    costs the copy, never the pane."""
    got = _scenario(node_results, "refusedClipboard")
    assert got["unhandled"] == [], f"the seam leaked an unhandledRejection: {got['unhandled']}"
    assert got["textarea"], got
    assert "T-alpha: done" in got["textarea"], got
    assert "T-beta: open" in got["textarea"], got
    assert got["readOnly"] is True, got
    assert got["copies"] == [got["textarea"]], got
    assert got["reloads"] == 0, got
    assert got["pending"] == 2, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_keep_mine_keeps_the_ticks_added_while_the_panel_stood_open(node_results):
    """RED today: Keep mine closes over the choices computed when the panel
    was SHOWN, so a tick the author adds AFTER the panel appeared is lost
    (discard, then re-stamp the OLD pairs). Green means Keep mine keeps the
    CURRENT draft: T-alpha AND the late T-gamma on the current tip key
    (KEY-A) with the current revision (REV-9), T-beta dropped (its row is
    gone -- nothing merges, nothing invented back), the three outcomes
    unchanged, and exactly one reload."""
    got = _scenario(node_results, "lateTick")
    assert got["buttons"] == ["Keep mine", "Keep theirs", "Copy it out"], got
    assert got["reloaded"] == 1, got
    assert got["revision"] == "REV-9", got
    assert got["ticks"] == [["T-alpha", "done"], ["T-gamma", "done"]], got
