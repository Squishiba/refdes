# W5b.4a tests — the preview pane's save context (test-only slice)

Task: write ONLY a new test file pinning the W5b.4a contract on
branch `feat/w5b4a-pane-context` (red-first; the implementation is a later
slice). No src/ edits, no existing-test edits, no PR.

## Contract pinned (tests/test_task_pane_tick_context.py)

Interactive preview pane, per tip: `.refdes-taskpane-panel` carries
`data-refdes-tip-key` (the tip item's minted key, docs/design/keys.md) and
`data-refdes-revision` — EXACTLY what the save compares. Mechanism verified
by reading the source, not memory: `file_revision` = sha256 of file bytes
(serve/edit.py:314); `continue_thread` compares the sha256 of the TIP item's
source file (`_item_path(before, tip)` at edit.py:2457, hashed at :2524),
served via `POST /api/item/<ref>/continue` (api.py:1485, Applied 200 /
Conflict 409 / Refused 422). Seam rules: response-only (built site and the
preview generation on disk carry neither attribute; disk pane byte-identical
to built pane); keyless tip = glyph rows, no controls, no context;
--no-write = no controls, no context.

## Tests (8) and red evidence (all FAIL on current main, 8 failed in 0.85s)

1. served panel = tip's minted key + sha256 of tip's file, computed
   independently from bytes; disk pane carries neither. Red: KeyError
   'data-refdes-tip-key' (:286).
2. Load-bearing round trip: revision from markup POSTs and applies; an
   unrelated SetField to a different item in the SAME file moves the file;
   replay of the stale revision with a tip-legal tick is 409 whose
   current_revision equals the file's new sha256; one continuation in the
   file. Red: KeyError 'data-refdes-revision' (:304).
3. After a disk edit, the NEXT served preview names the new sha256 (polled
   30 s). Red: KeyError (:354).
4. Fork ACROSS TWO FILES (log.yaml + branch.yaml): two panels, each naming
   its own tip's key and its own file's revision; the two revisions differ,
   which catches "hashed one file for all panels" and "hashed the viewed
   entry's file". Red: KeyError (:402).
5. Build walk: no attribute in any byte of _site; disk pane == built pane
   (these pass today); response pane carries both. Red at the response
   assert (:445).
6. --no-write: no checkbox/key/revision/module (passes today) PAIRED with a
   writable twin that ships all three (red :475) — the guard is not a dead
   path.
7. Hostile authored key `evil"><script>alert(1)</script>`: the attribute's
   unescaped value equals it, the page carries no live script / raw-quote
   breakout, and the revision on the same panel is real. Red: KeyError
   (:495).
8. Keyless tip (nobody minted): glyph rows as text, no checkbox/key/
   revision/module. Today the response has checkboxes so even "[ ]" fails
   (red :520 — whole test red); paired with the warmed twin shipping
   controls + context.

## Probe findings that shaped the fixtures (.scratch/w5b4a/probe.py, run2)

- `cli check` mints keys; warm fixture key gmkpfxkas65; panel tag today is
  `<div class="refdes-taskpane-panel" id=... data-refdes-panel="1">` with
  no new attributes.
- A stale-revision continue with an ILLEGAL-at-current-tip tick is 422
  Refused (tick validation precedes the revision compare), so test 2's
  second tick is done->open, legal at the continuation tip — only then is
  the stale revision the endpoint's sole refusal reason (409).
- Writable loads freeze bare `follows:` to the target's CURRENT tip, so a
  two-file fork chains on check; repaired by rewriting the new edge to
  `LOG-001@<head-key>` (same de-chain as
  test_task_pane_ticks.py::_write_fork_serve).
- Hostile authored key: read-only load keeps the key and renders (page
  200); `check` on it exits 1, so the hostile fixture never runs check.

## Verification

- New file: 8 failed (red, expected) under
  `PYTHONPATH=<worktree>/src ... pytest -q -n 4 --dist worksteal -p
  no:cacheprovider tests/test_task_pane_tick_context.py`.
- tests/test_crossplatform_lint.py: 26 passed (no new rule hits; file
  writes bytes only, no 3.12+ APIs, no PEP 695).
- `ruff check tests/test_task_pane_tick_context.py`: clean (scoped; the
  repo-wide baseline is not clean by design of this slice).
- Full suite NOT run (task: no full suite; test-only slice, red by design).

Status: finished. Branch pushed, no PR.

## Implementation (W5b.4a-impl, this slice)

Implemented the server half. src/ additions: 41 lines (pr_size budget 350).

- `serve/server.py`: `_pane_save_context(project, pane)` — called from
  `_decorate_task_ticks` after the pane model is built, before the
  has-ticks gate. Maps each tab's tip label to the live item and sets
  `tip_key` (the item's artifact key) + `tip_revision`
  (`edit.file_revision(edit._item_path(project, tip))`). A tip with no
  key, no in-root path, or an unreadable file gets no context.
- `templates/taskpane/pane.html.j2`: the panel div gains
  `data-refdes-tip-key` / `data-refdes-revision` only `{% if tab.tip_key %}`
  — the build model never sets one, so built bytes are untouched;
  autoescaping is the barrier for authored keys (test 7).

Reuse decision (task asked to say so): `continue_thread` does NOT resolve
its target file inline — `_continue_locked` calls the existing `_item_path`
helper (edit.py:992) for the tip and hashes the bytes it read. No helper
extraction was needed; the decoration reuses that same `_item_path` (plus
`file_revision`, the same sha256-of-bytes spelling) from server.py, so
markup and save resolve identically and the revision is read at render
time (test 3's poll).

Green: new tests 2,3,4,5,6,7 + both twins; W5b.3 suite 24/24; neighbours
(test_serve_preview_task_pane, test_serve_preview_decorations,
test_serve_continue, test_serve_continue_http, test_task_pane,
test_threads_render, test_serve_edit, test_serve_static,
test_crossplatform_lint) 263/263. Full suite: 2 failed, 6162 passed,
2 skipped — the 2 are the STOP points below. ruff on server.py: no new
findings (the UP012 hit at :507 is pre-existing, present on the HEAD copy
too). No JS, no endpoint change.

## STOP points (HARD RULE 1 — reported, not edited)

1. `test_the_served_panel_names_the_tips_key_and_the_file_revision` :288
   asserts `TIP_ATTR.findall(panel["slice"]) == ["LOG-002"]`, but
   `TIP_ATTR` matches the per-checkbox `data-refdes-tip` attr that W5b.3
   ships on EVERY tickable row (pinned green by
   test_task_pane_ticks.py::test_every_checkbox_names_the_tip_its_tick_writes_against).
   The warm ONE_TIP fixture has 2 tickable rows → the list is
   `["LOG-002", "LOG-002"]` in ANY implementation that keeps W5b.3 green.
   The file's own fork test (:396) uses the `set(...)` form. Proposed
   change: `assert set(TIP_ATTR.findall(panel["slice"])) == {"LOG-002"}`.
2. `test_a_tip_with_no_key_grows_glyph_rows_and_no_context` :520/:522/:524
   requires a keyless tip on a WRITABLE server to render glyph rows and no
   checkbox/module. W5b.3 pins the opposite on the same shape: its `served`
   fixture is a plain write (no `check`, probe: tip.key == '') and ~10 of
   its green tests demand checkboxes on it. The docstring's premise "W5b.3
   gave it no checkboxes" is factually false (the log's own red note says
   the response HAS checkboxes). Unimplementable without editing W5b.3.
   Proposed change: keep the context-absence assertions (:522-523, :526-527
   — implemented and passing: keyless tips carry no key/revision attrs);
   drop the control/module-absence claims for the writable keyless case
   (the read-only case is already covered by test 6).

Implemented per the compatible reading: keyless tips carry NO context
(key/revision attrs) — that half of test 8 (:526-527) is green; the
checkbox strip is not implemented (STOP point 2).

Status: implementation finished; full suite run; PR opened with the two
STOP points reported.
