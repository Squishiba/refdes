# w5b4b-tests — contract tests for the tick draft module (W5b.4b, test-author slice)

## What landed

One new file: `tests/test_tick_drafts.py` (23 test functions, 31 with
parametrization) pinning the contract of `src/refdes/serve/static/tick-drafts.js`
before it exists. Red-first: every test fails today — the node scenarios die
with `ERR_MODULE_NOT_FOUND` on the module path, the source pins with
`FileNotFoundError` (both quoted in the assertion messages, so the red
explains itself). No existing test and no src/ file was touched.

## Harness posture

Copied from the neighbours as instructed: `test_serve_drafts_corruption.py`
(one node process per scenario, harness written to tmp_path, argv-seeded
storage, in-function `pytest.skip` when node is absent) and
`test_editor_draft_mirror.py` (reload = a fresh `createTickDrafts` over the
same storage; the two-process chain `reloadWrite → reloadRead` is the real
cross-process reload). Timeout 120 s per node spawn. The harness defines NO
`document`/`window`/`fetch`/`sessionStorage` globals, so the module's purity
(ESM import succeeding) is proven by execution, not only by the source scan;
the one scenario that imports `drafts.js` (the collision test) installs the
window/sessionStorage stubs it needs and nothing else.

## Pinned surface (the implementer's job; changes here are contract changes)

`createTickDrafts(storage)` -> `{ get(tipKey), setTick(tipKey, taskId,
wantedState, originalState), clearTick(tipKey, taskId), pendingCount(tipKey),
pendingTicks(tipKey), setRevision(tipKey, revision), revision(tipKey),
discard(tipKey), corrupt(tipKey), counts() }` — plus ONE method added to the
brief's list: `persistent()` -> bool, false from the first storage fault
(getItem/setItem/removeItem throwing). That is the pinned "reports it" channel
for degraded storage; drafts.js reports silently via console+banner, which a
DOM-free module cannot do, and the pane (4c) needs a non-DOM signal for the
indicator.

Conservative choices pinned (all noted, none contradict the brief):

- Mirror key `refdes.tickdraft.v1.` + encodeURIComponent(tipKey); corrupt copy
  under `refdes.tickdraft.corrupt.v1.` + the same encoding (brief gave the
  first as "e.g."; pinning it makes the collision test meaningful).
  Envelope on the corrupt key is `{raw, reason}` JSON, same as drafts.js.
- Draft shape `{revision, ticks: {taskId: wantedState}}`; `get` returns exactly
  that object (`{revision: null, ticks: {}}` clean).
- `setTick`/`clearTick` return booleans: true when the draft changed, false on
  a no-op (wanted===original on an absent id, clearing an absent id).
- Non-string `taskId` (number, null, undefined, object, array, boolean) is
  REFUSED as a no-op — never coerced. The array id `['T-9']` (stringifies to a
  legal id) must still be refused, which kills the coerce-to-string reading.
- A revision stamp on a draft with no pending ticks is dropped (revision()
  null, no mirror) — drafts.js's `stampRevision` rule; emptying a draft
  resets the stamp. A draft with an empty ticks map never writes a mirror.
- Corrupt rule as brief: never read as clean; draft opens clean, editing
  proceeds, bytes preserved + reported via `corrupt(tipKey)`; re-armed on
  every fresh instance over storage still holding the copy; `discard` clears
  draft + mirror + corrupt copy; storage that throws on read reports NO
  corruption (nothing readable exists — drafts.js's private-mode rule).

## Coverage map

Lifecycle (set/un-tick-back-to-original per Q6(b)/re-tick moves to insertion
end), W5b.2 pair-order for the `continue` body, revision ride-off, reload
survival (Q1(b)), two tabs never sharing (Q1(b)), two tips coexisting with
per-tip `counts()` (Q5(a)), prefix isolation against `refdes.draft.v1.`
item drafts (shared storage, same key string), tip keys with `@ / # % + =`
and unicode round-tripping through `encodeURIComponent`, `__proto__`/
`constructor`/`__defineGetter__`/empty-string ids incl. Object.prototype
pollution probes (before/after own-property snapshot + sentinel probes), the
10-case corrupt matrix, discard (plain, corrupt, after-editing, survives
reload), getItem/setItem/removeItem fault degradation, and three source pins:
no `document/window/fetch/XMLHttpRequest/eval/innerHTML/sessionStorage/
localStorage/globalThis` (string-aware comment stripping copied from
test_serve_static.py), no imports at all (self-contained; "does not import
drafts.js" is implied by zero imports), and the served-js regexes re-run
locally.

## Verified claims

- Red: 31 failed, all with the module-missing evidence (ran
  `pytest tests/test_tick_drafts.py`).
- `tests/test_crossplatform_lint.py`: 26 passed with the new file present.
- `ruff check tests/test_tick_drafts.py`: clean (scoped, repo not ruff-clean).
- `tests/test_serve_static.py`: 69 passed today; it WILL pick the new module
  up: `js_files()` = `os.listdir(STATIC)` filtered to `.js` at collection
  (tests/test_serve_static.py:28-29) feeds the parametrized
  `test_no_inline_handlers_or_dynamic_code_in_served_js` (:82) and
  `test_served_js_parses_as_es2020_modules` (:132). `test_every_module_import_resolves`
  walks only what index.html/preview.js import — untouched by a file nothing
  imports yet.
- drafts.js byte-unchanged: `git status` clean in src/, `git diff
  origin/main -- src/refdes/serve/static/` empty.
- Neighbour node suites green with the new file present (corruption + mirror:
  28 passed).
- Full suite NOT run: the task line says "Absolute PYTHONPATH; no full suite"
  for this slice; this slice adds only a test file.

## Not provable without a real browser (W5b.4c's, verified with Playwright)

The DOM half: the per-tick pending count in the pane header, the unsaved
indicator/badge and Discard affordance, the `beforeunload` prompt arming on
pending ticks (this module has no window listener by design — 4c arms it),
real sessionStorage's per-tab isolation (faked here), quota behavior on real
browsers, and reload semantics of a real tab. The pure contract above is what
4b ships.

## Notes

- No changelog.d fragment: test-only slice, no user-visible change.
- Python 3.11 floor kept (no PEP 695, no Path.read_text(newline=)); node
  subprocess passes `encoding="utf-8"` (Windows cp1252 rule); harness written
  with `newline=""`; unicode flows to node only inside `json.dumps` (ASCII
  escapes), so no argv-encoding exposure.
