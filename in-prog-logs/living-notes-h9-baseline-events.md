# living-notes H9 — baseline snapshot events and the item-page history disclosure

Status: finished. Branch `feat/history-h9-baseline-events`, one commit,
PR to main (do not merge).

## What landed

- `history.baseline_events(project, kind, name)` — one snapshot event per
  keyed local item, kind = baseline kind, fingerprint = baseline name.
  Takes `project_write_lock`, idempotent by event id, rolls back events
  and its own objects on partial failure, skips keyless items.
- `lifecycle.stamp()` calls it on the success path only (write=True, gate
  passed). HistoryError/OSError -> `project.warn`, the stamp stands.
- `render.baseline_snapshots` + `history_disclosure`; `item.html.j2` gained
  `<section class="history-disclosure">` after the body: one row per
  containing baseline, newest open, captured text verbatim-escaped, edited-
  after-captured marker, and a plain "No snapshot was recorded for this
  baseline: ..." row for a baseline with no snapshot in the store (pre-store
  stamp, or a failed snapshot write) -- never invented text. The
  whole section is absent when there is nothing to show.

## TDD RED lines (each first failed for the named reason)

- stamp writes 0 events (writer missing) -> baseline_events added.
- `--no-write` stamp wrote files -> call site gated on write=True.
- gate-failed release wrote events -> moved after the gate.
- re-stamp duplicated events -> idempotent event id (fingerprint=name).
- disclosure rendered on an unstamped project -> history None + whitespace
  contract (falsy path must emit exactly the original "\n\n").
- legacy baseline showed current text as historical -> unavailable row.
- panel leaked raw `<script>` -> escape test drove template escaping.

## Tests

- New `tests/test_history_baseline.py` (24): writer semantics (4 stamp
  tests, idempotence, no-write, gate-fail, lock spy, per-item rollback,
  rollback removes only this call's objects, disagreeing-event refusal,
  stamp-level warning contract, re-stamp object/event counts,
  second baseline captures new state, late items get no rows),
  disclosure (absent/shown/unavailable/marker/escape/two-builds-identical/
  readonly-no-write/events-change-no-hash-no-seal-no-baseline/late-items).
- `tests/test_lifecycle.py` +2 (events on stamp, none on refusal),
  `tests/test_no_write.py` capture count now filters `kind: followed`
  (H9 adds `kind: revision` events; the anchor's own kind is what it counts).
- Touched suites: 175 passed post-rebase. New files ruff-clean; the 19
  findings left in touched files all reproduce on origin/main.

## Differential (old = git archive of origin/main, new = this branch)

Same nasty fixture (unicode, quotes, empty body, late item), shared minted
keys, build -> revision rev-a -> build in both, then `diff -rq`:

- `.refdes/baselines/rev-a.yaml` differs in the `stamped_at:` line only
  (runs were 13 s apart; digests/hashes/entries byte-identical).
- `Only in .refdes: history` (new tree) -- the events+objects store.
- The 4 stamped item pages differ; verified exact: new page == old page +
  the single `\n<section class="history-disclosure">...</section>` block.
- Unstamped pages, index, items.json, styles: byte-identical.

## Hash/seal impact

Proven by test (`test_events_change_no_hash_no_seal_no_baseline`): events
live under `.refdes/history/`, outside the hashed/sealed/baselined surfaces;
content hashes, seals, and baseline digests are unchanged by stamping.

## Review round (orchestrator, HIGH defect)

`baseline_events` rollback deleted objects the call only reused: the guard
compared a digest against a list of paths (never true), so every path --
including older baselines' objects -- went into `created_objects` and a
mid-call OSError/HistoryError removed them. Fixed by deciding "created by
this call" from existence BEFORE the write (digest computed first,
`object_path` checked, `save_object` then writes/validates). Events side
was already right (existing event files are skipped before writing).
Three tests added (`test_failed_restamp_must_not_delete_older_baselines_
objects`, `..._with_corrupt_later_object_keeps_older_objects`,
`test_restamp_counts_new_and_reused_objects`); the corrupt-object test
fails the failure AFTER a reuse, which is when the bug destroyed an older
baseline. All three RED on the old code, GREEN on the fix. Touched suites
172 passed; new test file ruff-clean.

## Review round 2 (three reviewers, batched)

1. The event-file pre-check adopted any existing event -- a re-stamp of a
   deleted baseline file after an item edit silently kept the OLD body as
   the snapshot (fabricated history). Now: digest computed first, existing
   event's `object:` compared, mismatch raises HistoryError naming baseline,
   key, and both digests (same guard append_event applies). Tests:
   `test_restamp_with_changed_item_refuses_disagreeing_event` and
   `test_writer_failure_warns_and_the_stamp_stands` (the stamp-level
   warning contract, previously unpinned).
2. Legacy-row copy was false for the failed-write case (and the unchanged
   early-return never retries -- deliberately kept: retrying there would
   snapshot an OLD baseline with TODAY's content). Copy now says "No
   snapshot was recorded for this baseline: it was stamped before the
   history store existed, or its snapshot write failed (see the stamp's
   warning)." Tests, docs (output.md, lifecycle.md), plan, and PR body
   updated to match.
3. baseline_snapshots docstring claimed store diagnostics that don't exist
   at render time -- corrected to the true absent-panel behavior.
4. BaselineEvents now returns `events_reused` (the counter existed, was
   computed, and was dropped).
5. Disclosure rows: newest open (code unchanged); PR body/docs corrected
   from "one collapsed row"; the misleading `_selector` test name renamed.
6-7. Plan §H9 "Adds" no longer claims a baseline selector (moved to a
   Not-built note); lifecycle.md now says the snapshot stores the semantic
   payload, not rendered HTML (semantic_payload, history.py:190).
8. `_in_baseline` display-id fallback: comment added -- ids.py allocates
   ids once and the ledger never reuses them, so the id-reuse attribution
   the reviewer flagged is not reachable.

Touched suites: 180 passed. New test file ruff-clean; the 16 findings in
touched src files reproduce on origin/main.

## Review round 3 (final, batched)

1. Rows now ordered by baseline `stamped_at` (ties by name), not filename
   sort, so the opened row is the newest stamp
   (`test_rows_are_ordered_by_stamp_time_not_by_name`, clock-controlled).
2. The no-backfill design (why an unchanged re-stamp must NOT call
   baseline_events): the unchanged path proves only the HASHED state
   matches -- an unhashed (`timeline`/`ignore`) field can differ -- so a
   backfill would attribute today's text to an old baseline. The
   lifecycle.py comment and the warning now say this plainly, including
   the remedy (re-stamp under a new name).
3. Render reading the baselines directory makes a corrupt baseline file
   fail the build -- verified IDENTICAL to main (same configuration-error
   message, rc=2; not a new failure mode). Pinned by
   `test_corrupt_baseline_file_fails_the_build_as_configuration_error`.
4. Event-with-missing-object (redaction/corruption) falls back to the
   no-snapshot row, whose copy now names redaction
   (`test_missing_snapshot_object_shows_the_no_snapshot_row`).
5. test_no_write counts `followed` events by parsed YAML `kind`, not
   substring.

Touched suites: 183 passed.

## Known environment noise (not from this branch)

Full suite here: 15 failed, 5040 passed, 2 skipped. All 15 are
test_scaffold/test_sealing_optin_note gitignore tests that fail on
pristine origin/main code in a worktree context (10 fail in the same two
files on the archived origin/main tree; CI on main is green). No file they
touch is in this branch's diff.
