# Living notes — Phase H3: "edited after captured", a diagnostic and never a failure

Implemented on `ao/refdes-127/living-notes-h3` (merged `origin/main` first;
already up to date).

## What landed

- `history.edited_after_captured(project) -> list[EditedAfterCaptured]`
  (`(item, event, captured_digest)` per the plan) plus the shared
  `history.capture_index(project)` (item key -> representative capture
  event + edited flag). Read-only: the store is opened, never written; a
  project with no `.refdes/history/` stays silent and gains no directory.
- `build.py`: `warn_edited_after_captured(project)` — one call in `build()`
  after `compute_hashes` and before `seal.verify`, reporting through
  `project.warn` only. The warning names the item, the capture event
  (kind + derived id), and the successor.
- `render.py items_json`: captured items carry a `captured` (event id) /
  `edited_after_captured` (bool) pair; uncaptured items carry neither key,
  so an uncaptured project's payload stays byte-identical (the `boards`
  convention, per the plan).
- Tests: `tests/test_history_edited.py` (10 cases: sabotage warning once
  naming item/event/successor with exit 0 and "0 errors"; unchanged item
  silent; unit-level tuple shape; build still writes the site; the
  two-digest split via an `on_change: log` edit that moves history but not
  `content_hash`; superseded-vs-corrected captures; merges keep both
  parents live; no-history project silent and dir-free; the items_json
  pair and its absence). One new case in `tests/test_no_write.py`
  (diagnostic reports under `--no-write`, whole tree byte-identical).
- Changelog: `changelog.d/edited-after-captured.added.md`.

## Resolved ambiguities (decisions, flagged for the reviewer)

1. **Test file name.** The plan says `tests/test_history_edit.py`; the
   handoff says `tests/test_history_edited.py`. Followed the handoff.
2. **Field granularity.** The handoff says "what changed at field
   granularity where the plan says so" — the plan never says so for H3
   (§3's sample line is "current semantic content differs", and H3
   explicitly does not do a diff UI). Implemented at semantic-digest
   granularity; no field-level diff.
3. **Superseded captures go quiet.** The plan does not spell out the
   diagnostic's treatment of a superseded capture; §2 case one's "treats
   the original as superseded" is the rule followed: a capture event whose
   successor no longer edges to its predecessor is excluded from the
   comparison (the event itself is untouched). A successor that is gone,
   or whose edges are all still-bare (unsettled), cannot disprove the
   edge, so that capture stands. Merges are unaffected — both parents'
   captures stay live (test asserts this).
4. **Multiple live captures of one item.** "Newest snapshot" cannot be
   ordered (`occurred_at` is display metadata, §2), so an item counts as
   edited only when its current digest matches *none* of its live
   captures; the representative event is a matching capture, else the
   lowest derived id — stable without a clock.
5. **No capture timestamp in the warning.** §3's sample line prints
   `captured 2026-09-15T14:08Z`, but H2 capture events deliberately carry
   no clock (H2 log decision 1), so the warning names the event by kind
   and derived id instead.
6. **A store that refuses to be read.** H1's loud-refusal philosophy would
   crash a build on a corrupt store; H3's "never a failure" rule wins at
   this call site — `warn_edited_after_captured` catches `HistoryError`/
   `OSError` and warns that the check declined. `items_json` degrades to
   no keys (the build's warning already said so).
7. **One H2 test narrowed.** `test_the_announcement_never_pollutes_machine_output`
   asserted `"captured" not in stdout`; the plan's new `captured` index key
   legitimately puts that word in `index --compact`'s JSON. The assertion
   now targets the announcement phrase (`"now follows it" not in stdout`),
   preserving its intent.

## Deliberately not touched

- Sealing (H5), CLI commands (H4), `tasks:`, release gates (H8), site
  history disclosure (H9), VS Code surfaces.

## Verification

- `python -m pytest -q`: 1588 passed (incl. 10 new H3 cases + 1 no-write case).
- `ruff check --select E9,F` on all touched files: clean.
