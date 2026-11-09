# w5b4c2a-tests — contract tests for tick-save.js (test-author slice)

Task: pin the export surface and behaviour of the NOT-YET-WRITTEN pure module
`src/refdes/serve/static/tick-save.js` (W5b.4c-2a: the REQUEST/RESPONSE logic
of the pane's Save). Deliverable: ONE new file, `tests/test_tick_save.py`. No
src/ edits, no existing-test edits, no PR.

## What was verified first (by running, not remembering)

- Fast-forwarded the worktree to origin/main (9f15af87, the 4c-1b PR).
- Captured the REAL route JSON by driving a live EditorApp on port 0 with the
  tests/test_serve_continue_http.py fixture (`.scratch/w5b4c2a/
  capture_contract.py`): every status/field below is a captured payload, and
  all of them are the same shapes tests/test_serve_continue_http.py pins.
- Read api.py `_continue_item`/`_apply_outcome`, edit.py `continue_thread` +
  the four dataclasses, server.py `_deny`/token seam, tick-drafts.js
  (pendingTicks() = [[id, state], ...]), tick-pane.js, and both node-harness
  test files (their style is copied: one node process per scenario group,
  skip-no-node, encoding="utf-8", newline="", NODE timeout 120 s).

## Pinned export surface

buildSaveRequest({ref, revision, pendingTicks}) -> {ok:true, path, body} /
{ok:false, reason:<plain string>}; planSaveResponse({status, body}) ->
{kind, message, ...} with kinds saved/conflict/refused/invalid/forbidden/
error; conflictChoices({revision, pendingTicks, current}) -> {keepTheirs,
keepMine, copyOut}; describeConflict({pendingTicks, current}) -> rows
{taskId, mine, theirs, differs}. Test docstring spells each out.

## The REAL shapes (what differed from the slice brief)

1. Invalid is 422, NOT 400 (api.py `_apply_outcome` maps Invalid to 422; the
   brief guessed 400). The 400s are the malformed-body gate {error:"<text>"}
   (no kind key). Pinned: kind "invalid" covers both — 422 carries the
   gate's "blocked:" message, 400 carries the route's error text.
2. The 409 carries NO task rows: `{expected_revision, current_revision,
   current_text, diff}` where current_text is the RAW current file text
   (None in the rare _Moved race). Pinned: conflict carries
   currentRevision/currentText (verbatim, incl. null)/diff — the
   `[{taskId, state, text}]` rows the choices/describe take come from the
   caller as `current = {revision, rows}`, not from the 409.
3. Saved carries the real 200 fields: revision (new file revision), id (new
   entry id), handle (minted key), path (project-relative), message.
4. The token/Origin seam's 403 is text/plain "missing or invalid launch
   token" (`_deny`), NOT JSON; the read-only 403 IS JSON {kind:"refused",
   error:"...--no-write..."}. Pinned: both are kind "forbidden" — the JSON
   one carries the server's --no-write text, the text/plain one a fixed
   message naming --no-write AND the stale token (relaunch).
5. 405 is JSON {"error":"method not allowed"} for GET on the route, plain
   text for PUT; 415 is plain text. All unnamed statuses pin to kind
   "error" with a generic message naming the status and NEVER the raw body.
6. Added one field to conflictChoices' input vs the brief's signature:
   `revision` (the draft's expected revision) — copyOut's header must name
   both revisions and the brief's input carried no source for the draft's.

Conservative choices (no question tool): empty-string task id rejected
locally; keepMine.revision is "" when current carries no revision (so
buildSaveRequest refuses to post it — closed chain); 200-with-junk-body is
kind "error"; refusal messages control-stripped (C0+DEL) then capped at 300
pinned exactly as "x"*300; hostile ids (`__proto__`, markup, unicode) are
data everywhere (Map/Set semantics, JSON round-trip pin).

## Red evidence (module missing — all 57 tests fail)

`PYTHONPATH=<wt>/src ... pytest tests/test_tick_save.py -q -p no:cacheprovider`
-> **5 failed, 52 errors**. Every node-harness group fails with
`ERR_MODULE_NOT_FOUND ... tick-save.js` (52 errors, fixtures); the 5 source
pins fail on FileNotFoundError/listdir. That is the committed state — red is
the deliverable (test-author slice, 4c-1a precedent).

## Green proof (contract satisfiable, no src/ change committed)

A spec-conformant reference module was written TEMPORARILY at
src/refdes/serve/static/tick-save.js, the file ran **57 passed**, and it was
deleted before commit (`git status` shows only the new test file). While it
stood, test_serve_static.py's parametrisation picked it up automatically
(`js_files()` listdirs static/*.js at collection): the
`[tick-save.js]` case of test_no_inline_handlers_or_dynamic_code_in_served_js
and test_served_js_parses_as_es2020_modules both ran and passed — the
implementer gets those checks for free. (The 4c-1a precedent kept its green
stub in .scratch/ with a redirected test copy; this slice's test file points
at the served path only, so the stub was in-tree and deleted — tree is clean.)

## Coverage (3 node processes + 5 no-node pins; 57 tests)

- build: captured request path+body (ticks order, pair copies, exact key
  set); percent-encoded hostile ref; __proto__/markup/unicode ids as data;
  deep-copy snapshot proof; 19 local-reject cases (empty ref, non-string/
  empty revision, empty/non-array ticks, bad pairs, bad ids, states outside
  open|done|dropped) each with a plain-string reason.
- plan: real Applied -> saved (revision/id/handle/path); real Conflict ->
  conflict (verbatim currentText/diff, null-text race); real Refused ->
  refused (server text exact); cap/strip exact; hostile echo inert; Invalid
  422 + malformed 400 -> invalid; read-only 403 names --no-write; token 403
  names token+--no-write; empty 403; transport {status:0}; 405/415/500/junk
  200/no-status -> generic with status, raw bodies never leak; every kind
  carries a plain-string control-free message.
- conflict: keepTheirs {discard:true} exact; keepMine re-stamps survivors
  (MY order) + dropped list, never merges (unticked current rows absent);
  copyOut header names both revisions + `id: state` lines (incl. vanished),
  no untouched rows; exactly the three ratified outcomes (key-set pin);
  missing current revision; describe in CURRENT order with
  mine/theirs/differs, vanished ticks appended theirs:null; empty draft =
  clean current list; __proto__ matched only by literal text.
- source pins: file in served static dir (auto-pick note), imports nothing,
  no document/window/fetch/XMLHttpRequest/eval/innerHTML/localStorage/
  sessionStorage/globalThis/X-Refdes-Token/Origin (comment-stripped),
  served-js rules, and all four exports are functions under node with NO
  page globals defined (purity by execution; the fetch ban is the scan's
  job — node >= 18 has its own global fetch).

## Cross-platform

subprocess.run has encoding="utf-8" + timeout; harness write_text uses
newline=""; no relpath-as-sep asserts; no Path.read_text(newline=); tests/
test_crossplatform_lint.py: green. ruff check on tests/test_tick_save.py:
clean. Full suite NOT run (per task: test-author slice ships red; the
implementer runs it once — 4c-1a precedent).

## What only the browser can verify (4c-2b, not this slice)

The Save button firing, the conflict panel rendering describeConflict rows
with textContent, and the X-Refdes-Token/Origin headers on the fetch — all
DOM/glue/token work the module never touches; verify in Chromium/Firefox
when 4c-2b lands.

## Status

Complete. Branch feat/w5b4c2a-tick-save-model pushed, tests only, no PR.
