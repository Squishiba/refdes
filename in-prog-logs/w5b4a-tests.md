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
