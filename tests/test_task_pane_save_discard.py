"""Run-17 findings 1 + 3: the Save seam's Discard redraw and the conflict rows.

docs/design/thread-workbench-w5b-plan.md owns the seam; the run-17 user-sim
report (in-prog-logs/user-sim-release-gate-run17.md, findings 1 and 3) owns
these two defects:

1. (Medium) After Discard the Save button stays visible with zero pending
   ticks -- a no-op click. The Save visibility is recomputed by the seam's
   ``draw()`` on the panel host's ``change`` event, and the pane's Discard
   (taskpane-ticks.js) resets the checkboxes PROGRAMMATICALLY and calls its
   own ``refreshPanel``: no ``change`` fires, so ``draw()`` never runs. The
   fix is structural: ``initSave`` returns its ``refreshPanel`` wrapped so
   every pane refresh also redraws the Save buttons, and the glue rebinds
   ``refreshPanel`` to that wrapper (the glue's Discard/restore paths then
   trigger the redraw through the refresh they already perform).

2. (Cosmetic) The conflict panel lists ticks whose value already equals the
   file's ("T-x: yours open, the file has open") -- noise when the change
   came from elsewhere. ``showConflict`` lists only rows that need the
   author's eyes: a tick row whose value DIFFERS from the file's (a tick
   equal to the file is no conflict) and the current rows the author did
   not tick (the panel's current-list context, pinned by #468's
   test_a_conflict_refetches_the_page_and_offers_exactly_three, which names
   the unticked T-gamma). When NO pending tick differs, the rows are
   replaced by the one plain line 'the file changed since you opened this
   page, but none of your pending ticks conflict with it' and the three
   ratified outcomes stay offered.

The same node-harness posture as tests/test_task_pane_save_ui.py and
tests/test_task_pane_save_polish.py (neither is edited): plain FakeNode DOM
from ``document.createElement``, a fetch recording (url, init) with scripted
answers, a location counting reloads, a clipboard that records text, a
DOMParser stub reading ``data-refdes-*`` out of the page text. No layout, no
CSS, no real event dispatch. The real-browser behaviour is verified by the
lead, not here.

Red today, green after the fix:

  test_the_glue_rebinds_refresh_panel_to_the_save_hook                    RED
  test_the_discard_click_hides_the_save_button                            RED
  test_a_new_tick_after_a_discard_shows_the_save_again                    RED
  test_the_conflict_panel_does_not_list_ticks_that_equal_the_file         RED
  test_the_all_equal_conflict_prints_the_plain_line_and_the_three         RED
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest
from test_serve_static import strip_js_comments

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(REPO_ROOT, "src", "refdes", "serve", "static")
GLUE = "taskpane-ticks.js"

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120

PLAIN_LINE = (
    "the file changed since you opened this page, "
    "but none of your pending ticks conflict with it"
)

HARNESS = """
const STATIC = __STATIC__;
const PAGE = __PAGE__;
const url = (name) => `file://${STATIC}/${name}`;

// The fake DOM, copied from tests/test_task_pane_save_ui.py's harness (the
// repo's posture): plain nodes from createElement, no layout, no CSS, the
// honest slice of event dispatch (a listener on this very node).
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
  if (method === "POST") {
    posts.push({ url: String(path), method, body: init && init.body ? JSON.parse(init.body) : null });
    const next = queue.shift();
    if (!next) throw new Error("harness: no scripted POST answer left");
    if (next.throws) throw new Error("transport down");
    return {
      ok: next.status === 200,
      status: next.status,
      json: async () => next.json,
      text: async () => (next.text === undefined ? "" : next.text),
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
  const discard = panelEl.appendChild(new FakeNode("button"));
  discard.className = "refdes-taskpane-discard";
  return { drafts, panelEl, entry: { tipKey, revision, canDraft: true, panelEl, status, discard } };
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
const settle = () => new Promise((r) => setTimeout(r, 80));

const results = { ok: true };

async function scenario(name, run) {
  // each scenario is its OWN TAB: a fresh mirror, like a fresh page
  store.clear();
  posts.length = 0; gets.length = 0; copies.length = 0;
  reloads = 0; queue = []; pageText = PAGE;
  try {
    results[name] = JSON.parse(JSON.stringify(await run()));
  } catch (err) { results[name] = { harnessError: String((err && err.stack) || err) }; }
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

// -- finding 1: the pane's Discard releases the draft and refreshes the
// panel PROGRAMMATICALLY (no `change` event). The seam's Save visibility
// must follow: the glue rebinds refreshPanel to initSave's wrapper, so a
// refresh redraws it.
await scenario("discardHidesSave", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  const refreshed = [];
  const glueRefresh = (panel) => { refreshed.push(panel.tipKey); };
  // exactly the glue's line: refreshPanel = initSave({...}) || refreshPanel
  const repaint = initSave({ drafts, panels: [entry], refreshPanel: glueRefresh }) || glueRefresh;
  const save = findButton(panelEl, "refdes-taskpane-save");
  const cleanHidden = save.hidden;
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change"); // the checkbox's change bubbling to the panel host
  const visibleAfterTick = !save.hidden;
  // Discard, as the glue's handler runs it (taskpane-ticks.js): release the
  // draft, reset the rows, refresh the panel. NO change event fires here --
  // that is the whole defect.
  drafts.discard(TIP);
  repaint(entry);
  return {
    cleanHidden,
    visibleAfterTick,
    visibleAfterDiscard: !save.hidden,
    refreshed,
    pending: drafts.pendingCount(TIP),
  };
});

// -- finding 1, half b: after the Discard hid it, a NEW tick shows it again.
await scenario("retickShowsSave", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  const glueRefresh = () => {};
  const repaint = initSave({ drafts, panels: [entry], refreshPanel: glueRefresh }) || glueRefresh;
  const save = findButton(panelEl, "refdes-taskpane-save");
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change");
  drafts.discard(TIP);
  repaint(entry);
  const visibleAfterDiscard = !save.hidden;
  drafts.setTick(TIP, "T-alpha", "done", "open");
  drafts.setRevision(TIP, REV);
  repaint(entry); // the refresh alone must repaint the seam's Save
  return { visibleAfterDiscard, visibleAfterRetick: !save.hidden };
});

// -- finding 3, half a: the tick T-alpha EQUALS the file (the pane ticked it
// against an older open, the file moved to open); T-beta vanished (appended,
// differs). Only T-beta is a conflict row.
await scenario("equalTicksNotListed", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "open", "done");
  drafts.setTick(TIP, "T-beta", "done", "open");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change");
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [CONFLICT_409];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  return {
    hasPanel: Boolean(panel),
    text: panel ? panel.textContent : "",
    buttons: panel ? buttonsIn(panel) : [],
    reloads,
    pending: drafts.pendingCount(TIP),
  };
});

// -- finding 3, half b: every pending tick EQUALS the file: no rows, the one
// plain line, and the three ratified outcomes still offered.
await scenario("allEqualPlainLine", async () => {
  const { drafts, panelEl, entry } = freshPanel(TIP, REV);
  initSave({ drafts, panels: [entry], refreshPanel: () => {} });
  drafts.setTick(TIP, "T-alpha", "open", "done");
  drafts.setTick(TIP, "T-gamma", "open", "dropped");
  drafts.setRevision(TIP, REV);
  panelEl.fire("change");
  const save = findButton(panelEl, "refdes-taskpane-save");
  queue = [CONFLICT_409];
  save.click();
  await settle();
  const panel = findClass(panelEl, "refdes-taskpane-conflict");
  return {
    hasPanel: Boolean(panel),
    text: panel ? panel.textContent : "",
    buttons: panel ? buttonsIn(panel) : [],
    reloads,
    pending: drafts.pendingCount(TIP),
  };
});

console.log(JSON.stringify(results));
"""

# The current page the DOMParser stub reads: the tip moved (REV-9); T-alpha
# and T-beta are GONE from the list (a tick on a vanished row is appended by
# describeConflict, T-alpha's tick value equals the file: the run-17 noise
# row "T-x: yours open, the file has open" needs the file to say open).
PAGE = (
    "<html><body>"
    '<div class="refdes-taskpane-panel" data-refdes-tip-key="KEY-A" data-refdes-revision="REV-9">'
    '<input data-refdes-task="T-alpha" data-refdes-task-state="open" data-refdes-tick-states="done,dropped" checked="checked">'
    '<input data-refdes-task="T-gamma" data-refdes-task-state="open" data-refdes-tick-states="done,dropped">'
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


def _glue_code() -> str:
    with open(os.path.join(STATIC_DIR, GLUE), encoding="utf-8") as fh:
        return strip_js_comments(fh.read())


def test_the_glue_rebinds_refresh_panel_to_the_save_hook():
    """RED today: the mechanism pin. initSave RETURNS its refreshPanel
    wrapped with the Save redraws, and the glue rebinds its own binding to
    that wrapper (``refreshPanel = initSave({...}) || refreshPanel``), so
    every path that refreshes the pane -- Discard included, which fires no
    ``change`` -- also recomputes the Save button's visibility. A fallthrough
    keeps the glue honest if the seam hands back nothing to rebind."""
    code = _glue_code()
    assert re.search(r"refreshPanel\s*=\s*initSave\(", code), (
        f"{GLUE} must rebind refreshPanel to initSave's wrapped refreshPanel: "
        "Discard refreshes the pane programmatically, and an unwrapped refresh "
        "never recomputes the Save button"
    )


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_the_discard_click_hides_the_save_button(node_results):
    """RED today (finding 1, Medium): tick -> Save visible; Discard (the
    glue's shape: release the draft, reset the rows, refresh the panel, NO
    change event) -> the Save button hides. Zero pending ticks never leave a
    clickable no-op Save on the pane."""
    got = _scenario(node_results, "discardHidesSave")
    assert got["cleanHidden"] is True, got
    assert got["visibleAfterTick"] is True, got
    assert got["visibleAfterDiscard"] is False, got
    assert got["refreshed"] == [ "KEY-A" ], got
    assert got["pending"] == 0, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_a_new_tick_after_a_discard_shows_the_save_again(node_results):
    """RED today (finding 1, the other half): the rebind must not freeze the
    button off -- after the Discard hid it, a new tick plus a pane refresh
    shows it again (the redraw recomputes from the live store)."""
    got = _scenario(node_results, "retickShowsSave")
    assert got["visibleAfterDiscard"] is False, got
    assert got["visibleAfterRetick"] is True, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_the_conflict_panel_does_not_list_ticks_that_equal_the_file(node_results):
    """RED today (finding 3, Cosmetic): the tick T-alpha's value EQUALS the
    current file's ('yours open, the file has open' was the run-17 noise):
    it is not listed. The vanished T-beta's tick (describeConflict appends
    it, differs) IS listed, and the unticked current row T-gamma keeps its
    context line (the #468 pin). The three outcomes and the kept draft are
    unchanged."""
    got = _scenario(node_results, "equalTicksNotListed")
    assert got["hasPanel"], got
    text = got["text"]
    assert "T-beta" in text, (text, "the differing tick must be listed")
    assert "yours done, the file has gone" in text, text
    assert "T-alpha" not in text, (text, "a tick equal to the file is not a conflict row")
    assert got["buttons"] == ["Keep mine", "Keep theirs", "Copy it out"], got
    assert got["reloads"] == 0, got
    assert got["pending"] == 2, got


@pytest.mark.skipif(NODE is None, reason="no node on PATH to run the served save module")
def test_the_all_equal_conflict_prints_the_plain_line_and_the_three(node_results):
    """RED today (finding 3, the all-equal case): every pending tick already
    equals the file: no tick rows are listed; the panel prints the one plain
    line 'the file changed since you opened this page, but none of your
    pending ticks conflict with it' and still offers exactly the three
    ratified outcomes. The draft is kept, nothing reloads."""
    got = _scenario(node_results, "allEqualPlainLine")
    assert got["hasPanel"], got
    text = got["text"]
    assert PLAIN_LINE in text, text
    assert "yours" not in text, (text, "no tick row belongs in the all-equal panel")
    assert got["buttons"] == ["Keep mine", "Keep theirs", "Copy it out"], got
    assert got["reloads"] == 0, got
    assert got["pending"] == 2, got
