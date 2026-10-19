# EDITOR-API-007 follow-up: the edit path's revision check must consume the replace's own read

Task: port PR #241's create-path fix (destination-race refusal, accepted scope
in `editor-api-007-create-destination-lost-update.md`) to the apply/accept path
in `src/refdes/serve/edit.py`. Status: **finished locally** — implemented,
tested, changelog fragment added; branch `fix-apply-expected-read`.

## What was wrong

`_apply_locked` checked `request.expected_revision` against the target file,
ran the overlay candidate gate (full loads, seconds), then called
`_atomic_replace(path, payload)` with no revision argument. Between the last
`file_revision(path)` read and the replace's read of the destination, a writer
outside the project write lock (editor, sync daemon, git) could land bytes on
the file; the replace swapped them away and the save answered 200. The
lockfile half of an accept had the same shape in `_land_lockfile`: it read the
lockfile under the project lock, computed staged bytes, then replaced with no
check consuming that read.

## The fix (same posture as #241)

- `_atomic_replace(path, payload, expected)` reads the destination, hashes
  it, and raises the new `_Moved(current)` — carrying the sha256 of the bytes
  it read — when the hash is not `expected`.
- `_apply_locked` threads `request.expected_revision` into the target replace.
  A `_Moved` there restores the entry pins (`_restore_lockfile(accept)`) and
  returns a `Conflict` whose `current_revision` is the replace's own read —
  no third read of the file, so the conflict reports exactly the bytes that
  defeated the swap.
- `_land_lockfile` computes `expected = sha256(current)` from the bytes it
  read under the lock and threads it into the lockfile replace. A `_Moved`
  returns the refusal "…changed on disk while this accept was landing; the
  pair landed nowhere — re-accept against the current lockfile"; nothing
  lands, the outside bytes stand.
- Docstrings updated (module step 7, `apply_edit`, `_atomic_replace`,
  `create_item` — the latter no longer claims create is narrower than apply).

## Accepted residual (deliberate scope limit, same as #241)

Between `_atomic_replace`'s destination read and its `os.replace`, a writer
outside the project lock can still land and be swapped away. No
check-and-replace on a plain file closes that. `apply_edit`'s docstring says
so, and there is a canary test that proves the gap and is *meant* to show the
loss: `test_the_gap_between_the_replaces_read_and_the_swap_is_the_residual_loss`
(reuses `replace_gap_writer` from `tests/test_serve_create.py`).

## Tests

- `tests/test_serve_edit.py`:
  - `test_a_file_moved_between_the_last_check_and_the_replace_is_a_conflict`
    — `late_writer` appends a block after the landing section's last
    `file_revision` read; asserts Conflict, the outside bytes survive, the
    edit is not applied, and files outside the target are untouched.
  - `test_the_gap_between_the_replaces_read_and_the_swap_is_the_residual_loss`
    — the accepted-gap canary above.
- `tests/test_citations_lockfile_locking.py`:
  - `test_a_lockfile_moved_between_the_landing_read_and_the_swap_refuses_the_pair`
    — an outside writer lands on `citations.yaml` between the landing read
    and the replace; asserts Refused ("re-accept"), the lockfile keeps the
    outside bytes, the item body is untouched.
  - Existing `_atomic_replace` test wrappers now forward extra args.
- Sabotage-checked: removing the threaded revision from the target replace
  fails the race test; passing `None` for the lockfile replace fails the
  lockfile race test. Both restorations re-run green.
- Self-review caught a variable-shadowing bug in the first draft:
  `_land_lockfile` already uses the name `expected` for its pin-value map in
  the moved-file branch, so threading the sha under that same name made the
  re-stage write receive a map where a hex digest belongs — every legitimate
  re-stage would have refused. The sha now lives in `expected_sha`; verified
  by sabotage (shadowing the map back in fails two pre-existing
  lockfile-locking tests, so the re-stage branch is covered).

## Verification

- `pytest -q tests/test_serve_edit.py tests/test_citations_lockfile_locking.py
  tests/test_serve_create.py` — green (122 passed).
- Full suite and `ruff check <touched files> --select E9,F` — see final run
  below.
- Changelog: `changelog.d/apply-edit-check-consumes-replace-read.fixed.md`.
