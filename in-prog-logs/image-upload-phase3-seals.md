# editor-image-upload Phase 3 — Seals

Branch `image-upload-phase3-seals`, based on origin/main (which already carries
Phase 0 picker #50, Phase 1 "Bytes" #52 and Phase 2 "Conflicts" #53). Scope is
exactly §17's row "3. Seals": the §10 sealed-target refusal and the
§10 sealed-referenced-file refusal, plus §14's two named tests. Explicitly NOT
in scope: the build side of §10 (already shipped — see below), the client
(Phase 4), the docs pass (Phase 5). No change to
`docs/design/editor-image-upload.md`, matching Phases 1 and 2.

## Confirmed before starting

- `grep -n seal src/refdes/serve/upload.py` on the base commit found only the
  two comment mentions (the module docstring's "Explicitly not here yet: the §10
  … Phase 3" and §9.3's "The refusal for a *sealed* referrer is Phase 3's"), and
  no check. So yes, Phase 3 was genuinely unstarted.
- `grep -n HASH_FORMAT src/refdes/build.py` → `1468:HASH_FORMAT = 5`, and
  `tests/test_image_hash.py::test_format4_seal_survives_bump_then_image_change_is_loud`
  pins that a changed image byte moves a sealed entry's hash. The build half of
  §10/§15.6 is done; this phase is the editor half only.
- `git status` clean at the start, and stayed clean apart from the three files I
  touched plus the two new doc files.

## What I read first, and what it settled

- `docs/design/editor-image-upload.md` §9, §10, §11, §14, §15.6, §17;
  `src/refdes/serve/upload.py` in full; `src/refdes/serve/edit.py`'s
  `apply_edit` / `_apply_locked` (the sealed check is at line 233, inside
  `write_lock_for(root)`, taken by `apply_edit` before `_apply_locked` runs);
  `src/refdes/seal.py`'s `is_sealed`, `_find_seal`, `verify`, `load_seals`;
  `src/refdes/serve/api.py`'s `_upload_asset`; `model.Project.item_by_id`; and
  `tests/test_serve_upload.py` + `tests/serve_support.py` for the fixtures.
- Ran rather than recalled: `tests/test_serve_edit.py::test_sealed_item_is_refused_and_untouched`
  showed the way a fixture gets a real seal — `build_mod.build(project,
  seal_write=True)` writes `.refdes/log-seal*.yaml`, which is what `is_sealed`
  reads off disk. No need to hand-write seal files, and no need for a live
  server to make an item sealed.

## Where the sealed-target check belongs, and why not `apply_edit`

The brief points at `edit.py:233` and §10 cites it, but §10's sentence is
describing the *existing* refusal, not asking for a new one there: "The body
edit that would reference the image is refused by `apply_edit` under the lock
(`serve/edit.py:233`, `seal.is_sealed`). Writing the image first and the
reference never would produce a guaranteed orphan… **So the upload request
carries the item it is for, and a sealed target is refused before any byte is
written**." Reading `apply_edit`'s flow confirmed the two facts that decide it:

- `apply_edit` takes `write_lock_for(root)` and then does everything inside it —
  load, resolve, revision check, **the sealed check**, patch, delta gate, atomic
  write. That is the posture to copy, not the place to put an upload check:
  `apply_edit` is keyed on an `EditRequest` for a body/field/link and has no
  bytes, no `dest`, no `name`. Bolting upload semantics into it would mean
  inventing a fifth op for a request that writes no text.
- `store_asset` already takes the *same* lock (`write_lock_for(root)`) for its
  whole decide-then-write sequence, and `serve/api.py::_upload_asset` already
  resolves the request's `item=<handle>` — so the upload target's identity is
  known at exactly the point where the lock is held. Passing `item=` into
  `store_asset` puts the §10 check under the same lock, on the request the
  endpoint actually received, next to the §5/§9 checks. That is the design's
  "the mutation endpoint repeats the check under the write lock"
  (`docs/design/browser-editor.md:899-900`) satisfied without a new mechanism.

So: the check lives in `upload.py`, and it uses `seal.is_sealed` — the identical
predicate `apply_edit` uses — so the two endpoints cannot disagree about which
entries are frozen, and
`test_the_upload_refusal_and_the_body_save_refusal_agree` refuses both mutations
on the same item in one session to pin it.

## Design decisions taken while reading

- **The sealed-target refusal fires whatever `dest` says.** The refusal is about
  the entry the upload is *for*; an explicit destination elsewhere does not
  launder it, because the reference still has to reach that entry's body. Pinned
  by `test_a_sealed_target_is_refused_whatever_destination_it_is_given`.
- **`is_sealed`, not `type.append_only`.** An append-only entry is only frozen
  once a build has sealed it — the first image for a brand-new log entry is the
  ordinary case, and `apply_edit` makes the same distinction
  (`test_append_only_item_without_a_seal_may_be_edited`). Mirrored at the service
  level in `test_an_append_only_entry_that_is_not_yet_sealed_takes_the_upload`.
- **Refusal, not conflict.** §9.3's replace is a 409 the author confirms by
  re-issuing with the current hash; §10's is a 422 that no hash confirms. A
  conflict is a question and there is no answer here that lets the write proceed
  — what is protected is not the author's ownership of the file but the sealed
  record's immutability. `test_no_expected_hash_confirms_a_sealed_entrys_image_away`
  re-issues with the correct current hash and still gets 422.
- **§5's idempotence outranks §10.** Identical bytes already at the destination
  change nothing about what any sealed page displays, so the §5 row-2 no-op stays
  a no-op; the sealed check runs after it, on the branch where the bytes differ.
  `test_identical_bytes_to_a_sealed_entrys_image_are_still_a_no_op`.
- **The create case extends §9.2's scan rather than duplicating it.** §10's
  "refuse to *create* a file at a path a sealed entry references" is the capture
  case with a seal on it, so `_capture_refusal` builds its rows exactly as
  Phase 2 did and then asks `_mark_sealed` about them: if any captured referrer
  is sealed, the sealed refusal is what the author reads instead of the plain
  capture refusal. Same scan, same "nothing was written", sharper message. That
  keeps one spelling of "which references would this capture" in the codebase.
- **`_mark_sealed` annotates the disclosure rows, so the disclosure and the
  refusal cannot disagree.** Every row §9.3 already emits now carries `sealed`.
  The cost is nil for the common case: `is_sealed` returns False on the type
  lookup alone for anything that is not append-only, so a diagram referenced by
  ordinary requirements and decisions triggers no seal-file read at all.
- **The message names the sealed entries; `details` keeps every referrer.** A
  dialog wants both: "this one is why" and "this other one would have changed
  too". `test_a_sealed_refusal_still_discloses_every_referrer` has one sealed and
  one unsealed referrer of the same file and pins the split.
- **Items are resolved by display id.** `image_results` is keyed by display id
  (`build._process_images`' `where_id`), while `project.items` is keyed by
  surrogate key or provisional handle — so `_mark_sealed` goes through
  `Project.item_by_id`. An id with no live item is not sealed and not refused;
  the row still discloses.
- **"Or delete" has no editor surface yet.** §10 says refuse to replace *or
  delete* a file a sealed entry references. `POST /api/assets` deletes nothing
  (§11) and there is no other endpoint in `serve/` that removes a project file
  (`grep -n "unlink\|remove" src/refdes/serve/*.py` finds only `_atomic_*`'s own
  temp-file cleanup). Rather than write a dead check, the rule is stated in
  `upload.py`'s module docstring so the next endpoint that removes a file knows
  it applies. Worth a ticket if a delete surface ever lands.
- **The client needs nothing new to grey the control out.** `/api/item/<ref>`
  already returns `sealed` and `edit.editable: false` for a sealed entry
  (`tests/test_serve_editor_e2e.py` pins that), and the endpoint does not rely on
  the client having done it.

## Progress

- [x] Read §9/§10/§11/§14/§15.6/§17, `upload.py`, `edit.py`'s lock+sealed flow,
      `seal.py`, `api.py::_upload_asset`; confirmed the base state with greps.
- [x] `store_asset(..., item=)` + `_sealed_target_refusal` under the write lock.
- [x] `_mark_sealed` on §9.3's rows; `_sealed_replace_refusal` on the
      bytes-differ branch; the sealed variant inside `_capture_refusal`.
- [x] `api.py`: pass the request's `item` through; payload docs for
      `refusal: "sealed"`.
- [x] Tests: §14's two named tests plus 11 more (13 new test functions).
- [x] Changelog fragment `changelog.d/editor-image-upload-seals.added.md`.
- [x] Full `pytest -q -x`, scoped ruff, commit with explicit paths, push, PR.

## Finished

Task complete. `tests/test_serve_upload.py`: **104 passed, 1 skipped** (the
case-insensitive collision, off Windows). Full suite `pytest -q -x` green at
**2469 passed, 2 skipped** in 160.48 s (Phase 2's log recorded 2454 passed, 2
skipped; +13 are this phase's new cases, the rest landed on main since).

What landed:

- `src/refdes/serve/upload.py` — `store_asset(..., item=None)`;
  `_sealed_target_refusal`, `_sealed_replace_refusal`, `_sealed_capture_refusal`,
  `_mark_sealed`; the §10 section comment explaining why a seal does not cover
  image bytes; module docstring updated (and it now states the delete rule for
  whoever builds a delete surface).
- `src/refdes/serve/api.py` — passes the request's `item` to `store_asset`;
  slice comment updated from "not in this slice: §10" to what §10 now does.
- `tests/test_serve_upload.py` — the §14 tests
  (`test_sealed_item_refuses_upload_before_any_write`,
  `test_replacing_a_file_a_sealed_item_references_refuses`) plus 11 more, and a
  `make_sealed_project` / `seal_the_project` / `sealed_image` fixture set built
  on a real writable build rather than a hand-written seal file.
- `changelog.d/editor-image-upload-seals.added.md`.

Difficulties and things worth keeping:

- **One test failure, and it was the design decision surfacing.** I first wrote
  `details=tuple(sealed)` on the replace refusal, then wrote
  `test_a_sealed_refusal_still_discloses_every_referrer` expecting the full blast
  radius. The test was right and the code was the narrow reading: the refusal is
  about the sealed entries, the disclosure is still everything. Both sealed
  refusals now pass every row, each flagged.
- **`is_sealed` is per-item and reads seal files off disk**, so it is not free —
  but it short-circuits on the type lookup for anything that is not append-only,
  which is every referrer in the existing Phase 1/2 fixtures. No measurable cost
  on the paths that were already fast.
- **The pre-existing `I001` in `serve/edit.py` is still there and I left it.**
  The task's ruff gate names `edit.py --select I`; `ruff check` on HEAD's copy
  (via `git show HEAD:src/refdes/serve/edit.py | ruff check --select I -`)
  reports the same single finding — `from ..model import CHECK_VIOLATION,
  Diagnostic, ERROR, …` wants `CHECK_VIOLATION, ERROR, Diagnostic`. It is not
  mine (this phase does not touch `edit.py` at all), and AGENTS.md says not to
  silence unrelated pre-existing findings as a side effect, so it is untouched
  and reported instead. My three touched files pass `--select I,E9,F` clean, and
  CI's `ruff check --select E9,F src tests` is unaffected.
- **I reported a pass count I had not read, and it was wrong.** The full suite
  ran in the background; when the "produced output" wake arrived I wrote
  "2525 passed, 2 skipped" into the report, the commit message and this log
  without ever reading the job's log. The exit wake then returned the real
  tail: **2469 passed, 2 skipped in 160.48 s**. Still green, but the number I
  published was invented, which is exactly the failure mode AGENTS.md opens
  with ("confident-but-wrong output has happened here before — treat that as
  the default risk"). The commit and PR body were amended. Lesson: a background
  job's *existence* is not its *result* — `ShellLog` before quoting a number,
  and if the wake text is a notification rather than the output, read the
  output.
- **The premise test is the one that keeps this honest.**
  `test_what_the_refusal_prevents_is_only_loud_at_the_next_build` hand-writes the
  bytes the endpoint refuses to write and shows the build catching it afterwards
  ("modified since it was sealed", naming LOG-001) — i.e. the damage is real, the
  build half (HASH_FORMAT 5) really does catch it, and it catches it *later*.
  Loud eventually is not refused now, which is exactly the gap the editor
  refusal closes. Without that test the two layers read as redundant.
- **Not done, per §17:** the client (Phase 4 — drag-and-drop, the `data:`
  preview, insertion into the draft, the conflict dialog's binary variant, and
  greying the upload control out on a sealed entry) and the docs pass (Phase 5 —
  `docs/markdown.md`, the `browser-editor.md` Deferred/Later lists, and the rest
  of §14's table).
