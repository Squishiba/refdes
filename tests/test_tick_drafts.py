"""W5b.4b contract tests: the tick draft module (docs/design/thread-workbench-w5b-plan.md,
§4 W5b.4 + §6 Q1/Q5/Q6/Q8, all RATIFIED 2026-11-06).

The module under test is `src/refdes/serve/static/tick-drafts.js`: ONE new pure
ES module holding the tick DRAFT -- no DOM, no network, no globals beyond what
drafts.js uses. The storage object is INJECTED, so these node harnesses drive
it headless with a fake (the posture of tests/test_serve_drafts_corruption.py:
one node process per scenario, argv-seeded storage, skip when node is absent).
The harnesses deliberately define NO `document`, `window`, `fetch` or
`sessionStorage` globals: a module that touches any of them fails the import
itself (the purity proof runs, it is not only a text scan).

The pinned export surface (the pane module of W5b.4c builds against this):

    createTickDrafts(storage) -> {
      get(tipKey),                                   // {revision, ticks}
      setTick(tipKey, taskId, wantedState, originalState),
      clearTick(tipKey, taskId),
      pendingCount(tipKey),
      pendingTicks(tipKey),                          // [[taskId, state], ...]
      setRevision(tipKey, revision),
      revision(tipKey),
      discard(tipKey),
      corrupt(tipKey),
      counts(),                                      // {tipKey: pendingCount}
      persistent(),                                  // false once storage threw
    }

Draft shape per tip key: `{revision, ticks: {taskId: wantedState}}`. The
mirror key is its OWN prefix, `refdes.tickdraft.v1.` + encodeURIComponent, so
it can never collide with the editor's `refdes.draft.v1.` item drafts (Q1(b):
reuse drafts.js's persistence rules -- page memory + per-tab sessionStorage
mirror, corrupt mirror preserved under its own corrupt key and re-armed on
load until an explicit discard -- not its draft shape). setTick with
wantedState === originalState REMOVES the entry (Q6(b): un-ticking back to
the original leaves no pending change), pendingTicks is insertion-ordered and
is exactly the `POST /api/item/<ref>/continue` body's `ticks` list shape,
and a draft whose pending list is empty leaves NO mirror key behind.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO_ROOT, "src", "refdes", "serve", "static")
TICK_DRAFTS_JS = os.path.join(STATIC, "tick-drafts.js")
DRAFTS_JS = os.path.join(STATIC, "drafts.js")

NODE = shutil.which("node")

# One node spawn per scenario; generous for a cold process start on a shared
# runner (see the timeout note in tests/test_editor_draft_mirror.py).
NODE_TIMEOUT_S = 120

TICK_PREFIX = "refdes.tickdraft.v1."
CORRUPT_PREFIX = "refdes.tickdraft.corrupt.v1."

TIP = "LOG-001@k-9"
TRUNCATED = '{"revision":"r7","ticks":{"T-1":"d'


def enc(text: str) -> str:
    # encodeURIComponent's unreserved set in urllib terms
    return urllib.parse.quote(text, safe="!*()'")


def tick_key(tip: str) -> str:
    return TICK_PREFIX + enc(tip)


def corrupt_key(tip: str) -> str:
    return CORRUPT_PREFIX + enc(tip)


HARNESS = """
import { pathToFileURL } from 'node:url';

const [tickPath, draftsPath, scenario, seedJson] = process.argv.slice(2);
const input = JSON.parse(seedJson);
const TIP = input.tip ?? 'LOG-001@k-9';

// The injected storage: the sessionStorage triple, with per-scenario faults.
function fakeStorage(entries, fail) {
  const store = new Map(Object.entries(entries || {}));
  const api = {
    getItem(k) {
      if (fail === 'getItem') throw new Error('SecurityError: storage blocked');
      return store.has(k) ? store.get(k) : null;
    },
    setItem(k, v) {
      if (fail === 'setItem') throw new Error('QuotaExceededError: full');
      store.set(k, String(v));
    },
    removeItem(k) {
      if (fail === 'removeItem') throw new Error('SecurityError: storage blocked');
      store.delete(k);
    },
  };
  return { api, store };
}

const { createTickDrafts } = await import(pathToFileURL(tickPath).href);

const snap = (d, tip) => ({
  get: d.get(tip),
  count: d.pendingCount(tip),
  ticks: d.pendingTicks(tip),
  revision: d.revision(tip),
  counts: d.counts(),
  corrupt: d.corrupt(tip),
  persistent: d.persistent(),
});

const S = (fail) => fakeStorage(input.storage, fail);
const out = { scenario };

if (scenario === 'basic') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  out.initial = snap(d, TIP);
  d.setTick(TIP, 'T-1', 'done', 'open');
  out.after = snap(d, TIP);
  out.storage = Object.fromEntries(store);
}

if (scenario === 'untickRoundtrip') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  d.setTick(TIP, 'T-1', 'done', 'open');
  out.dirty = snap(d, TIP);
  out.setReturn = d.setTick(TIP, 'T-1', 'open', 'open');
  out.unticked = snap(d, TIP);
  out.storage = Object.fromEntries(store);
  out.clearMissing = d.clearTick(TIP, 'T-404');
  out.afterClear = snap(d, TIP);
}

if (scenario === 'untickToNewState') {
  const { api } = S();
  const d = createTickDrafts(api);
  d.setTick(TIP, 'T-1', 'done', 'open');
  d.setTick(TIP, 'T-1', 'dropped', 'open');
  out.ticks = d.pendingTicks(TIP);
  out.count = d.pendingCount(TIP);
}

if (scenario === 'insertionOrder') {
  const { api } = S();
  const d = createTickDrafts(api);
  d.setTick(TIP, 'T-3', 'done', 'open');
  d.setTick(TIP, 'T-1', 'dropped', 'open');
  d.setTick(TIP, 'T-2', 'done', 'open');
  d.clearTick(TIP, 'T-3');
  d.setTick(TIP, 'T-3', 'dropped', 'open');
  out.ticks = d.pendingTicks(TIP);
}

if (scenario === 'revisionRules') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  d.setRevision(TIP, 'rev-7');
  out.cleanStamp = { revision: d.revision(TIP), storage: Object.fromEntries(store) };
  d.setTick(TIP, 'T-1', 'done', 'open');
  d.setRevision(TIP, 'rev-7');
  out.dirty = { revision: d.revision(TIP), storage: Object.fromEntries(store) };
  d.clearTick(TIP, 'T-1');
  out.emptied = { revision: d.revision(TIP), storage: Object.fromEntries(store) };
  d.setTick(TIP, 'T-2', 'done', 'open');
  d.setRevision(TIP, 'rev-9');
  out.restamped = { revision: d.revision(TIP), storage: Object.fromEntries(store) };
}

if (scenario === 'reloadWrite') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  d.setTick(TIP, 'T-1', 'done', 'open');
  d.setTick(TIP, 'T-2', 'dropped', 'open');
  d.setRevision(TIP, 'rev-3');
  out.write = snap(d, TIP);
  out.storage = Object.fromEntries(store);
}

if (scenario === 'reloadRead') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  out.read = snap(d, TIP);
  out.storage = Object.fromEntries(store);
}

if (scenario === 'twoTips') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  const B = input.tip2;
  const C = input.tip3;
  d.setTick(TIP, 'T-1', 'done', 'open');
  d.setTick(TIP, 'T-2', 'dropped', 'open');
  d.setTick(B, 'T-9', 'done', 'open');
  d.setTick(C, 'T-1', 'done', 'open');
  d.setTick(C, 'T-1', 'open', 'open');
  out.a = snap(d, TIP);
  out.b = snap(d, B);
  out.c = snap(d, C);
  out.keys = Object.keys(Object.fromEntries(store)).sort();
  out.storage = Object.fromEntries(store);
}

if (scenario === 'twoTabs') {
  const a = fakeStorage({});
  const b = fakeStorage({});
  const d1 = createTickDrafts(a.api);
  const d2 = createTickDrafts(b.api);
  d1.setTick(TIP, 'T-1', 'done', 'open');
  d2.setTick(TIP, 'T-1', 'dropped', 'open');
  out.tab1 = snap(d1, TIP);
  out.tab2 = snap(d2, TIP);
  out.tab1Keys = Object.keys(Object.fromEntries(a.store)).sort();
  out.tab2Keys = Object.keys(Object.fromEntries(b.store)).sort();
  out.tab1Reload = snap(createTickDrafts(a.api), TIP);
}

if (scenario === 'collide') {
  const { api, store } = S();
  // drafts.js needs the page globals; the tick module must need NONE of them,
  // so it is imported (above) with no globals defined at all.
  globalThis.sessionStorage = api;
  globalThis.window = { addEventListener: () => {} };
  const drafts = await import(pathToFileURL(draftsPath).href);
  drafts.setDraftField(TIP, 'status', 'approved');
  const d = createTickDrafts(api);
  out.fromItemDraft = snap(d, TIP);
  d.setTick(TIP, 'T-1', 'done', 'open');
  out.tick = snap(d, TIP);
  out.itemDraftFields = drafts.getDraft(TIP).fields;
  out.keys = Object.keys(Object.fromEntries(store)).sort();
  out.storage = Object.fromEntries(store);
}

if (scenario === 'oddKeys') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  for (const tip of input.tips) d.setTick(tip, 'T-1', 'done', 'open');
  out.keys = Object.keys(Object.fromEntries(store)).sort();
  const d2 = createTickDrafts(api); // reload over the same storage
  out.ticksByTip = Object.fromEntries(input.tips.map((t) => [t, d2.pendingTicks(t)]));
  out.counts = d2.counts();
}

if (scenario === 'protoTick') {
  const protoBefore = Object.getOwnPropertyNames(Object.prototype).join('|');
  const { api, store } = S();
  const d = createTickDrafts(api);
  out.added = d.setTick(TIP, '__proto__', 'done', 'open');
  out.after = snap(d, TIP);
  out.reload = snap(createTickDrafts(api), TIP); // mirror round-trip of the hostile id
  out.cleared = d.clearTick(TIP, '__proto__');
  out.afterClear = snap(d, TIP);
  out.protoPolluted = Object.getOwnPropertyNames(Object.prototype).join('|') !== protoBefore;
  out.protoHasDone = 'done' in Object.prototype;
  out.protoHasOpen = 'open' in Object.prototype;
  out.storage = Object.fromEntries(store);
}

if (scenario === 'hostileIds') {
  const { api } = S();
  const d = createTickDrafts(api);
  out.hostileStrings = [];
  for (const id of ['constructor', '__defineGetter__', '']) {
    const added = d.setTick(TIP, id, 'done', 'open');
    out.hostileStrings.push([id, added, d.pendingTicks(TIP).length]);
    d.clearTick(TIP, id);
  }
  out.nonStrings = [];
  for (const id of [123, null, undefined, {}, ['T-9'], true]) {
    const added = d.setTick(TIP, id, 'done', 'open');
    out.nonStrings.push([String(id), added, d.pendingCount(TIP)]);
  }
  out.final = snap(d, TIP);
  out.clearNonString = d.clearTick(TIP, 123);
  out.protoCtorIsString = typeof Object.prototype.constructor === 'string';
}

if (scenario === 'corruptRead') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  out.read = snap(d, TIP);
  out.storage = Object.fromEntries(store);
}

if (scenario === 'discardAll') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  out.before = snap(d, TIP);
  d.setTick(TIP, 'T-2', 'done', 'open'); // a newer valid draft takes over the slot
  out.edited = snap(d, TIP);
  d.discard(TIP);
  out.after = snap(d, TIP);
  out.storage = Object.fromEntries(store);
}

if (scenario === 'editedDiscard') {
  const { api, store } = S();
  const d = createTickDrafts(api);
  out.before = snap(d, TIP);
  d.setTick(TIP, 'T-1', 'done', 'open');
  out.edited = snap(d, TIP);
  d.discard(TIP); // discards the corrupt copy, never the newer valid draft
  out.after = snap(d, TIP);
  out.storage = Object.fromEntries(store);
}

if (scenario === 'storageGetThrows') {
  const { api, store } = S('getItem');
  const d = createTickDrafts(api);
  out.persistent = d.persistent();
  out.setReturn = d.setTick(TIP, 'T-1', 'done', 'open');
  out.snap = snap(d, TIP);
  out.storage = Object.fromEntries(store);
  out.discardReturn = (() => { d.discard(TIP); return 'no-throw'; })();
}

if (scenario === 'storageSetThrows') {
  const { api, store } = S('setItem');
  const d = createTickDrafts(api);
  d.setTick(TIP, 'T-1', 'done', 'open');
  out.snap = snap(d, TIP);
  out.storage = Object.fromEntries(store);
  out.untickReturn = d.setTick(TIP, 'T-1', 'open', 'open');
  out.empty = snap(d, TIP);
  out.persistent = d.persistent();
}

if (scenario === 'storageRemoveThrows') {
  const { api, store } = S('removeItem');
  const d = createTickDrafts(api);
  d.setTick(TIP, 'T-1', 'done', 'open');
  out.snap = snap(d, TIP);
  out.discardReturn = (() => { d.discard(TIP); return 'no-throw'; })();
  out.after = snap(d, TIP);
}

process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path, scenario: str, storage: dict | None = None, **extra) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to run the tick draft module")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8", newline="")
    seed = json.dumps({"storage": storage or {}, **extra})
    proc = subprocess.run(
        [NODE, str(harness), TICK_DRAFTS_JS, DRAFTS_JS, scenario, seed],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the unicode tip keys on the way back in.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness {scenario!r} failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _clean_draft():
    return {"revision": None, "ticks": {}}


# -- the draft lifecycle -----------------------------------------------------


def test_set_tick_lands_in_memory_and_the_session_mirror(tmp_path):
    r = _run(tmp_path, "basic")
    assert r["initial"] == {
        "get": _clean_draft(),
        "count": 0,
        "ticks": [],
        "revision": None,
        "counts": {},
        "corrupt": None,
        "persistent": True,
    }, "an untouched tip must read as a clean, empty, non-corrupt draft"
    assert r["after"]["count"] == 1
    assert r["after"]["ticks"] == [["T-1", "done"]]
    assert r["after"]["get"] == {"revision": None, "ticks": {"T-1": "done"}}
    assert r["after"]["counts"] == {TIP: 1}
    # the mirror is written on every change, not lazily: the key is the module's
    # own prefix, encodeURIComponent'd, and carries the draft shape
    assert list(r["storage"]) == [tick_key(TIP)], "mirror key is not the pinned prefix"
    assert json.loads(r["storage"][tick_key(TIP)]) == {"revision": None, "ticks": {"T-1": "done"}}


def test_untick_back_to_original_leaves_no_pending_change(tmp_path):
    """Q6(b): un-ticking in the draft is free; a row may return to its original
    state, and the draft must then be exactly as if the tick never happened."""
    r = _run(tmp_path, "untickRoundtrip")
    assert r["dirty"]["count"] == 1
    assert r["setReturn"] is True
    assert r["unticked"]["ticks"] == []
    assert r["unticked"]["count"] == 0
    assert r["unticked"]["counts"] == {}, "the tab-switch UI still counts a cancelled tick"
    # an empty draft leaves NO mirror key behind -- storage must be untouched-clean
    assert r["storage"] == {}, "an emptied draft left its mirror key in storage"
    # clearing an id that is not pending is a no-op, not a throw
    assert r["clearMissing"] is False
    assert r["afterClear"]["count"] == 0


def test_untick_to_a_new_state_stays_pending(tmp_path):
    """wantedState !== originalState keeps the entry, and a second wanted
    state replaces the first -- one entry per task id, never two."""
    r = _run(tmp_path, "untickToNewState")
    assert r["ticks"] == [["T-1", "dropped"]]
    assert r["count"] == 1


def test_pending_ticks_are_w5b2_pairs_in_insertion_order(tmp_path):
    """pendingTicks() is exactly the `POST /api/item/<ref>/continue` body's
    `ticks` list: [taskId, wantedState] pairs in the order the author ticked
    (a cleared id re-ticked moves to the end -- the order is insertion, not
    id sort)."""
    r = _run(tmp_path, "insertionOrder")
    assert r["ticks"] == [["T-1", "dropped"], ["T-2", "done"], ["T-3", "dropped"]]


def test_the_revision_rides_the_draft_and_leaves_with_it(tmp_path):
    """The draft carries the revision the pane rendered at (the save posts it);
    a draft with no pending ticks carries no revision and leaves no mirror --
    drafts.js's stampRevision rule (a clean form has no opening to carry)."""
    r = _run(tmp_path, "revisionRules")
    assert r["cleanStamp"] == {"revision": None, "storage": {}}, (
        "a stamp on an empty draft wrote a mirror: an empty draft leaves no key"
    )
    assert r["dirty"]["revision"] == "rev-7"
    mirror = json.loads(r["dirty"]["storage"][tick_key(TIP)])
    assert mirror == {"revision": "rev-7", "ticks": {"T-1": "done"}}
    assert r["emptied"] == {"revision": None, "storage": {}}, (
        "emptying the draft kept the stamp and the mirror key"
    )
    assert r["restamped"]["revision"] == "rev-9"
    assert json.loads(r["restamped"]["storage"][tick_key(TIP)])["revision"] == "rev-9"


# -- lifetime: reload survives, a tab is its own draft (Q1(b), Q5) ----------


def test_a_fresh_module_over_the_same_storage_recovers_the_draft(tmp_path):
    """Q1(b): reload survives. A fresh createTickDrafts over the SAME storage
    (a new page over the same tab's sessionStorage) recovers the exact draft;
    the mirror, not the old instance, is the reload's source."""
    written = _run(tmp_path, "reloadWrite")
    assert written["write"]["ticks"] == [["T-1", "done"], ["T-2", "dropped"]]
    assert list(written["storage"]) == [tick_key(TIP)]
    read = _run(tmp_path, "reloadRead", written["storage"])
    assert read["read"]["ticks"] == [["T-1", "done"], ["T-2", "dropped"]]
    assert read["read"]["revision"] == "rev-3"
    assert read["read"]["counts"] == {TIP: 2}
    assert read["read"]["corrupt"] is None
    assert read["storage"] == written["storage"], "a read-only recovery wrote to storage"


def test_two_tabs_on_one_tip_have_their_own_drafts(tmp_path):
    """Q1(b): a second tab has its OWN draft, never a shared one -- modelled
    as two fake sessionStorages (sessionStorage is per-tab)."""
    r = _run(tmp_path, "twoTabs")
    assert r["tab1"]["ticks"] == [["T-1", "done"]]
    assert r["tab2"]["ticks"] == [["T-1", "dropped"]]
    assert r["tab1"]["counts"] == {TIP: 1} and r["tab2"]["counts"] == {TIP: 1}
    assert r["tab1Keys"] == r["tab2Keys"] == [tick_key(TIP)]
    # each tab's reload recovers its own draft, not the other's
    assert r["tab1Reload"]["ticks"] == [["T-1", "done"]]


def test_two_tips_of_one_fork_coexist_with_their_own_counts(tmp_path):
    """Q5(a): one draft per tip, keyed by the tip's KEY; drafts on two tips of
    one fork coexist in the same tab, and the tab-switch UI's counts() names
    each tip's own pending count -- and omits a tip whose draft is empty."""
    tip_b = "LOG-002@k-9"
    tip_c = "LOG-003@k-9"
    r = _run(tmp_path, "twoTips", tip2=tip_b, tip3=tip_c)
    assert r["a"]["ticks"] == [["T-1", "done"], ["T-2", "dropped"]]
    assert r["b"]["ticks"] == [["T-9", "done"]]
    assert r["c"]["ticks"] == []
    assert r["a"]["counts"] == {TIP: 2, tip_b: 1}, "counts() merged tips or listed the empty one"
    assert r["keys"] == sorted([tick_key(TIP), tick_key(tip_b)])
    assert json.loads(r["storage"][tick_key(tip_b)]) == {"revision": None, "ticks": {"T-9": "done"}}


def test_the_tick_mirror_never_collides_with_the_item_draft(tmp_path):
    """The tick mirror has its OWN prefix: the same key string used as an
    editor item handle and as a tip key produces two independent keys; the
    tick module never reads a `refdes.draft.v1.` item draft, and a tick never
    touches it."""
    r = _run(tmp_path, "collide")
    assert r["fromItemDraft"]["ticks"] == [], (
        "the tick draft read the editor's item draft as its own"
    )
    assert r["tick"]["ticks"] == [["T-1", "done"]]
    assert r["itemDraftFields"] == {"status": "approved"}, "a tick polluted the item draft"
    assert r["keys"] == sorted([f"refdes.draft.v1.{enc(TIP)}", tick_key(TIP)])


def test_tip_keys_round_trip_through_the_mirror_key(tmp_path):
    """Tip keys are composite ids (`@`, `/`, `#`, unicode, `%` all legal in a
    key); the mirror key encodes them, and a reload recovers every tip."""
    tips = ["LOG-001@abc/key#1", "日志/线程@KEY", "100%+done=now", "a*b(c)'d-e_f.g~h"]
    r = _run(tmp_path, "oddKeys", tips=tips)
    assert r["keys"] == sorted(tick_key(t) for t in tips)
    assert r["ticksByTip"] == {t: [["T-1", "done"]] for t in tips}
    assert r["counts"] == {t: 1 for t in tips}


# -- hostile ids: the storage keys are user data, never code -----------------


def test_proto_is_a_real_tick_and_pollutes_nothing(tmp_path):
    """A task id of `__proto__` (or a mirror carrying one) must behave as an
    ordinary id -- present in the draft, in the mirror, recoverable on reload,
    clearable -- and must not touch Object.prototype (Object.create(null) /
    Map territory: a naive plain-object copy loop LOSES this tick on reload)."""
    r = _run(tmp_path, "protoTick")
    assert r["added"] is True
    assert r["after"]["ticks"] == [["__proto__", "done"]]
    assert r["after"]["count"] == 1
    assert r["reload"]["ticks"] == [["__proto__", "done"]], (
        "the __proto__ tick was lost through the mirror -- a copy loop tripped "
        "the prototype setter"
    )
    assert r["cleared"] is True
    assert r["afterClear"]["count"] == 0
    assert r["protoPolluted"] is False, "Object.prototype gained a property"
    assert r["protoHasDone"] is False
    assert r["protoHasOpen"] is False
    assert list(r["storage"]) == [tick_key(TIP)]


def test_hostile_and_empty_task_ids_are_handled(tmp_path):
    """`constructor`, `__defineGetter__` and the empty string are real keys
    that round-trip as ticks and clear cleanly; a non-string task id is
    refused as a no-op (never coerced, never thrown)."""
    r = _run(tmp_path, "hostileIds")
    assert r["hostileStrings"] == [["constructor", True, 1], ["__defineGetter__", True, 1], ["", True, 1]]
    assert r["nonStrings"] == [["123", False, 0], ["null", False, 0], ["undefined", False, 0],
                               ["[object Object]", False, 0], ["T-9", False, 0], ["true", False, 0]]
    assert r["final"]["count"] == 0
    assert r["clearNonString"] is False
    assert r["protoCtorIsString"] is False, "Object.prototype.constructor was overwritten"


# -- the corrupt mirror (drafts.js's rule, reused) ---------------------------


@pytest.mark.parametrize(
    "raw",
    [
        TRUNCATED,           # truncated JSON
        "null",
        "[1, 2]",
        '"just a string"',
        "42",
        '{"title":"x"}',     # parses, none of the draft keys
        '{"ticks":"nope"}',  # a recognized key with the wrong type
        '{"revision":5}',
        '{"ticks":{"T-1":5}}',
        '{"ticks":[["T-1","done"]]}',
    ],
)
def test_a_mirrors_that_is_not_a_tick_draft_never_reads_clean(tmp_path, raw):
    """An unreadable / wrong-shape mirror is evidence of unsaved ticks, never
    a clean slate: it is preserved under the module's own corrupt key, reported
    via corrupt(tipKey) with the raw bytes and a reason, and the draft opens
    clean so editing can proceed (drafts.js's rule, Q1(b))."""
    r = _run(tmp_path, "corruptRead", {tick_key(TIP): raw})
    assert r["read"]["ticks"] == []
    assert r["read"]["get"] == _clean_draft()
    assert r["read"]["corrupt"] is not None, f"{raw!r} read as a clean draft"
    assert r["read"]["corrupt"]["raw"] == raw
    assert isinstance(r["read"]["corrupt"]["reason"], str) and r["read"]["corrupt"]["reason"]
    envelope = json.loads(r["storage"][corrupt_key(TIP)])
    assert envelope["raw"] == raw, "the bytes are not recoverable under the corrupt key"


def test_corruption_is_rearmed_on_every_load(tmp_path):
    """The corrupt copy outlives the page: a reload (new process, same storage
    bytes) re-reports the SAME damage, so the evidence cannot be buried."""
    first = _run(tmp_path, "corruptRead", {tick_key(TIP): TRUNCATED})
    assert first["read"]["corrupt"] is not None
    second = _run(tmp_path, "corruptRead", first["storage"])
    assert second["read"]["corrupt"]["raw"] == TRUNCATED
    assert second["read"]["corrupt"]["reason"] == first["read"]["corrupt"]["reason"]
    assert second["read"]["ticks"] == []


def test_discard_releases_the_draft_the_mirror_and_the_corrupt_copy(tmp_path):
    """Discard (Q8(a): the editor's rules) is the explicit release: memory,
    the mirror key and the corrupt copy all go -- nothing re-arms on reload."""
    first = _run(tmp_path, "discardAll", {tick_key(TIP): TRUNCATED})
    assert first["before"]["corrupt"] is not None
    assert first["edited"]["ticks"] == [["T-2", "done"]]
    after = first["after"]
    assert after["count"] == 0 and after["ticks"] == [] and after["counts"] == {}
    assert after["corrupt"] is None
    assert first["storage"] == {}, "discard left a mirror key or the corrupt copy"
    reloaded = _run(tmp_path, "corruptRead", first["storage"])
    assert reloaded["read"]["corrupt"] is None, "a discarded mirror re-armed on reload"


def test_discarding_the_corrupt_copy_keeps_the_newer_draft(tmp_path):
    """Discard releases the CORRUPT bytes and the draft, and a valid draft
    that took over the slot in the meantime is the draft being discarded too
    (an explicit discard of the tip's draft clears both) -- never silent."""
    r = _run(tmp_path, "editedDiscard", {tick_key(TIP): TRUNCATED})
    assert r["before"]["corrupt"] is not None
    assert r["edited"]["ticks"] == [["T-1", "done"]]
    assert r["after"]["ticks"] == [] and r["after"]["corrupt"] is None
    assert r["storage"] == {}
    reloaded = _run(tmp_path, "corruptRead", r["storage"])
    assert reloaded["read"]["corrupt"] is None and reloaded["read"]["ticks"] == []


# -- storage faults cost persistence, not editing (drafts.js's rule) ---------


def test_unreadable_storage_costs_persistence_not_editing(tmp_path):
    """Private mode / blocked storage (getItem throws): no throw, the draft
    works in memory, and persistent() reports the degradation (pinned:
    persistent() is false from the first storage fault). Nothing can be read,
    so nothing is corrupt -- nothing is reported as damage."""
    r = _run(tmp_path, "storageGetThrows")
    assert r["persistent"] is False
    assert r["setReturn"] is True
    assert r["snap"]["ticks"] == [["T-1", "done"]]
    assert r["snap"]["corrupt"] is None
    assert r["storage"] == {}
    assert r["discardReturn"] == "no-throw"


def test_a_full_storage_costs_persistence_not_editing(tmp_path):
    """Quota exceeded on write: the draft lives in memory, no mirror exists,
    persistent() is false, and the empty-draft rule (no key) is unchanged."""
    r = _run(tmp_path, "storageSetThrows")
    assert r["snap"]["ticks"] == [["T-1", "done"]]
    assert r["storage"] == {}
    assert r["untickReturn"] is True
    assert r["empty"]["count"] == 0
    assert r["persistent"] is False


def test_an_unwritable_removal_does_not_throw(tmp_path):
    """removeItem throwing (blocked storage) is swallowed like the rest:
    discard clears memory and reports no throw."""
    r = _run(tmp_path, "storageRemoveThrows")
    assert r["snap"]["ticks"] == [["T-1", "done"]]
    assert r["discardReturn"] == "no-throw"
    assert r["after"]["count"] == 0


# -- source pins: the module is pure, self-contained, and served-clean ------


INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"]+)['"]""")


def _strip_js_comments(text: str) -> str:
    """The string-aware comment stripper from tests/test_serve_static.py: the
    purity scan runs on code, not prose."""
    out = []
    i = 0
    n = len(text)
    in_string = None
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "'\"`":
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                out.append(" ")
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tick_code() -> str:
    with open(TICK_DRAFTS_JS, encoding="utf-8") as fh:
        return _strip_js_comments(fh.read())


def test_the_module_is_pure_no_dom_no_network_no_storage_globals(tmp_path):
    """4b is the pure half: NO DOM, no network, no reaching for the page's
    sessionStorage -- the storage object is injected (the harnesses above
    prove the same fact by running the module with NO such globals defined)."""
    code = _tick_code()
    for forbidden in (
        "document", "window", "fetch", "XMLHttpRequest", "eval",
        "innerHTML", "sessionStorage", "localStorage", "globalThis",
    ):
        assert forbidden not in code, f"tick-drafts.js touches {forbidden!r}"
    assert "export function createTickDrafts" in code


def test_the_module_is_self_contained_and_never_touches_drafts_js(tmp_path):
    """W5b.4 reuses drafts.js's RULES, not its module: tick-drafts.js imports
    nothing (no import graph, no shared mutable memory Map) and must not
    contain the item draft's prefix -- the prefixes keep the kinds apart."""
    code = _tick_code()
    assert JS_IMPORT.findall(code) == [], "tick-drafts.js must be self-contained"
    assert "drafts.js" not in code
    assert "refdes.draft.v1." not in code
    assert TICK_PREFIX in code
    assert CORRUPT_PREFIX in code


def test_the_module_passes_the_served_js_rules(tmp_path):
    """test_serve_static.py's js_files() lists static/*.js at collection time,
    so the new file is picked up by its inline-handler / dynamic-code / ES2020
    parse checks automatically; this pins the same checks here."""
    listing = [n for n in os.listdir(STATIC) if n.endswith(".js")]
    assert "tick-drafts.js" in listing, "the file is not in the served static dir"
    code = _tick_code()
    assert not INLINE_HANDLER.search(code), "an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(code), "no eval/new Function in the editor"
    assert "javascript:" not in code
