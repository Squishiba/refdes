# EDITOR-API-007 — the create path silently ate a concurrent destination write

Task: fix EDITOR-API-007 (`in-prog-logs/current-main-resweep-editor-revision.tsv`)
at the pinned origin/main HEAD `8b6a52e`. Status: **pushed as PR #241**
(branch `fix/editor-create-lost-update-20261013`), on HOLD — the plugin
review's P1 (the read-to-`os.replace` gap, section 2 of the follow-up below)
is an accepted open design question, not merged. The commits on this branch
are `git log` of this branch.

## What was wrong

`serve/edit.py::_create_locked`, for the two append destination shapes, read
the destination file, planned the appended item against those bytes, ran the
overlay candidate gate (two full `load_readonly`s — seconds, not
microseconds), and then `_atomic_replace`d the whole file with no check in
between. The overlay masks the destination, so the gate could not see what
landed on the destination's own bytes during the gate; the replace replaced
them anyway. A writer outside the project's cross-process lock (any process
that does not take `.refdes`'s `project_write_lock` — an editor, a sync
daemon, git) had its bytes silently discarded while `POST /api/items/create`
answered `200 kind: created`. The baseline repro
(`probe_api007.py` in the resweep scratch dir) is exactly this: an external
`REQ-777` marker appended inside the read→replace window did not survive the
create it was reported beside.

## The fix

One seam, in `create_item`/`_create_locked` only. No request field was added
to `CreateRequest`: the browser never reads the destination file, so a
client-supplied revision would be a field the server could not meaningfully
check — the honest baseline is the bytes **this create itself read**.

Steps 1 and 2 below describe commit `997f6f7` (the pre-fold shape). The
branch tip folds the check into `_atomic_replace` as an `expected` argument
(see the 2026-10-15 follow-up, section 1); read them as the design's first
form, not the shipped code.

1. `_create_locked` hashes the destination bytes at the moment it reads them
   (`planned_revision = sha256(raw)`, computed from the read itself, not a
   second `open`).
2. Immediately before `_atomic_replace` — after the gate, as late as the
   code can make it — it re-checks `file_revision(path)` against that hash.
   A mismatch returns a private `_DestinationMoved` value (never an
   exception, never one of the four public outcomes; `create_item` owns it).
3. `create_item` retries the whole `_create_locked` from a fresh load while
   attempts remain (`CREATE_DESTINATION_ATTEMPTS = 2`, bounded so a
   destination under steady outside writing ends in a refusal instead of
   spinning under the lock). A retry replans everything — id, key, links,
   destination shape — so the item lands *on top of* the external bytes
   instead of over them. When attempts run out it returns a `Refused` whose
   reason says the destination kept changing and to retry the creation.
4. Nothing moved that could change the ledger contract: the final check and
   the retry loop sit **before** any write and before `ids.reserve_id`, so a
   moved/retried/refused creation writes no bytes and burns no id. The
   existing commit-or-rollback behavior (reserve after the write, roll the
   file back if the reserve fails) is untouched.

The `new-md` destination shape needed nothing: `_atomic_create` links rather
than replaces, so a file that appears underneath it is already a refusal.

## The remaining limit, stated honestly (per the review criterion)

This is not an absolute conflict guarantee and does not claim to be. On a
plain file there is no atomic compare-and-swap: the final `file_revision`
re-read and the `os.replace` inside `_atomic_replace` are two syscalls, and a
writer that does not take the project lock can still land in the gap between
them — same residual TOCTOU `apply_edit`'s own last-moment revision check
(`edit.py:471-476` at this head) has always had against the same class of
writer. What the fix
removes is the *seconds-wide* window (read → id planning → overlay gate →
replace), which is the window the repro actually hit; what remains is the
microsecond gap no check-then-replace closes. The cooperating-writer story is
unchanged: `write_lock_for` + `project_write_lock` already exclude any
`refdes` CLI writer from the whole section; the check is for the writers the
lock was never promised to stop. This wording is in the module docstring,
`create_item`'s docstring, and the check-site comment, so nobody has to
re-derive it.

## Tests (written first, red on `8b6a52e`)

`tests/test_serve_create.py`, helper `external_writer`: deterministic seam
on `textio.append_ending` (the create's own call inside the read→replace
window), mirroring the baseline probe rather than racing on timing.

- `test_a_destination_written_between_read_and_replace_is_not_eaten` — YAML
  append shape: one outside write → `Created`, outside bytes survive, item
  lands after them, ledger has the new id and not the outside one.
- `test_a_moved_markdown_destination_replans_onto_the_current_bytes` — the
  repro's multi-item Markdown shape.
- `test_a_destination_that_keeps_moving_is_refused_with_nothing_burned` —
  outside write on every attempt → `Refused` ("kept changing", "retry"),
  nothing written, the planned id not reserved, and the next honest create
  gets exactly that id.
- `test_http_a_raced_create_retries_and_the_outside_bytes_survive` /
  `test_http_a_persistent_race_refuses_with_a_retry_reason` — the same two
  outcomes through `POST /api/items/create` on a real in-process `EditorApp`
  (200 retried / 422 refused with the retry reason the form shows).

Red before the fix: all five fail, the first two with the baseline's exact
signature ("the external write was silently replaced" + `Created`).
Sabotage after the fix (guard → `if False`): the three service tests fail
again; restore confirmed green.

## Verification

- `PYTHONPATH=src python -m pytest tests/test_serve_create.py -q` → 60
  passed (55 pre-existing + 5 new; all 55 untouched ones still pass).
- Full suite `PYTHONPATH=src python -m pytest -q` → **3607 passed, 2
  skipped** (~4.5 min). (Note: the shared venv's installed `refdes` points
  at the main checkout — every run here is prefixed `PYTHONPATH=src` so the
  worktree's `src/refdes` is what imports; verified via `refdes.__file__`.)
- CI ruff scope `python -m ruff check --select E9,F src tests` → clean. The
  repo's full-ruff baseline is not clean by design (AGENTS.md), untouched.
- Probe: `.scratch/fix-editor-create-lost-update/probe_api007.py` (this
  worktree's scratch, per AGENTS.md) re-runs the baseline scenario against
  the fix: one-shot mover → `Created REQ-778` with the marker preserved and
  reserved once; persistent mover → `Refused`, nothing written, `REQ-778`
  **not** in the ledger; honest retry → lands and reserves its own id with
  the outside bytes intact. It fails on the sabotaged build (marker
  survived: False) and passes on the fixed one.

## Difficulties / decisions

- Refusal-vs-retry was the design question. Edit requests carry
  `expected_revision` because the client saw the file; create requests
  don't and can't, so a `Conflict`-shaped result (which carries the client's
  `expected_revision` and the draft-vs-disk diff) would have been the wrong
  shape, and a client field never checked against disk is exactly the
  superficiality the brief warns about. A server-side check against the
  create's own read, with a bounded replan, is what fits the existing
  posture ("refusal is a value", plan-under-the-lock, burns nothing).
- The retry re-runs `_create_locked` whole rather than rebuilding just the
  text, because the fresh load is also what re-plans the id — an outside
  append can claim the number this create had picked, and a retry that kept
  the old plan would duplicate it.
- Kept the loop total at 2 attempts deliberately: the tests pin one landing
  per attempt, and bumping the constant still keeps the refusal test honest
  (the last attempt's write still moves the destination).
- `git status` was clean of foreign changes before starting (AGENTS.md);
  no stash, no push, no PR, main checkout untouched.

Commit: see the `fix(serve)` commit on this branch (subject
`fix(serve): refuse/retry a create whose destination moved under it (EDITOR-API-007)`).

## Follow-up 2026-10-15 — independent review findings addressed

The independent review (in-prog-logs/fix-branch-review-20261014.txt) held
this branch for two things; both are addressed here.

1. **The final check-to-replace gap (review: mitigation, not closure).**
   Confirmed: at `5bd62cf` the check (`file_revision(path)`) and the
   replace's own read of the destination were *two full-file reads* — the
   window from the check to the swap included the second read plus the temp
   write. The check is now folded into `_atomic_replace` as an `expected`
   argument: the function checks the bytes on the read it performs to
   protect the replace, so no plan-window read of the destination remains
   between check and swap. The gap that is left — that read to
   `os.replace`, spanning the temp write's syscalls — is the irreducible
   one on a plain file, and the module/create docstrings say exactly that.
   This branch closes EDITOR-API-007's reported signature (the seconds-wide
   plan window, reported as `200 created`), not the irreducible
   uncooperating-writer race; the in-prog log's limit section above and the
   docstrings carry that scope. The new test
   `test_the_gap_between_the_last_check_and_the_replace_is_the_residual_loss`
   pins the exposure to exactly that gap (seam: `os.replace` itself, one
   notch later than the retry tests' `append_ending` seam): a write landing
   there is *still lost* with `Created` — documented, asserted behavior, so
   a future real CAS fails the test and updates the docs.
2. **HIGH rollback failure, reproduced (also on main at `8b6a52e`).** In
   the append shapes `original` was `raw.decode("utf-8")`, a str; a failed
   `ids.reserve_id` fed it to `_restore`'s `open(path, "wb").write(...)` —
   the open truncates the file to zero bytes, the write raises
   `TypeError` (not caught by `_restore`'s `except OSError`), and
   `create_item` raised where it is documented to return a result. Fix:
   `original` stays the raw bytes (the decoded text is a local `text`);
   the rollback restores bytes. Tests
   `test_a_failed_id_reservation_restores_the_destination_bytes` /
   `..._a_markdown_destination` (seam: `ids.reserve_id` raising `OSError`)
   are red at `5bd62cf` with exactly the reproduced signature
   (`TypeError: a bytes-like object is required, not 'str'` at the
   `_restore` write) and green with the fix, asserting the full original
   bytes are back and nothing is reserved.
   Sabotage: dropping the folded `expected` argument fails the two
   retry tests; restoring is green.

Focused: 69 passed on the rebased tree (61 pre-existing + 8 new). Sabotage
of the bytes fix (`original = raw.decode("utf-8")`) fails both rollback
tests; restoring is green. Full suite on the rebased tree (base
`509a487`): **3833 passed, 2 skipped**. CI-scope ruff
(`--select E9,F src tests`) clean.

## Follow-up 2026-10-15 (second pass) — plugin review + the split

The Paseo plugin review of PR #241 (chunk 1 space-bunny, agent 8246b42a:
CHANGES REQUESTED; chunk 2 mimo: APPROVE) plus the coordination notes:

1. **The P1, on design, not on a line.** The review's chunk 1 confirmed the
   residual gap by tracing the seam (mkstemp/chmod/write/fsync between the
   hashed read and `os.replace`), and the committed
   `test_the_gap_between_the_last_check_and_the_replace_is_the_residual_loss`
   proves it: a write landing in the replace's own read-to-swap gap is lost
   with `Created`. Design conclusion on this branch: **portable atomic CAS
   is not achievable in this architecture.** POSIX offers no
   content-conditional atomic replace (renameat2's `RENAME_NOREPLACE` is
   create-if-absent, not a compare; Windows `ReplaceFile` is
   content-unconditional too), and this codebase targets all three platforms
   CI covers (ubuntu, windows). What *is* sound and already true: every
   cooperating writer — the CLI (`cli.main` wraps `project_write_lock`) and
   every serve route (`write_lock_for` + `_disk_write_lock`, held across
   the whole plan/check/swap span) — serializes on the same lockfile, so
   the gap admits only a writer that bypasses the lock, whose bytes no
   check-then-replace on a plain file can promise over. That is exactly
   what the docstrings and the changelog fragment claim, and the
   residual-gap test is the canary that fails if a real CAS ever lands.
   The PR stays on HOLD for a human call on accepting that scoped
   guarantee (the plugin review's one merge ask was the changelog
   fragment, now added).
2. **The rollback half is split to PR #244** (rollback-only, rebuilt on
   main): the `original`-stays-bytes fix and its two tests
   (`test_a_failed_id_reservation_*`) left this branch; `original = text`
   here is the main bug, pointed at #244 by the comment at the site. No
   duplication between the PRs.
3. **Review nits addressed:** `changelog.d/create-destination-race-refusal.fixed.md`
   added (chunk 1 MEDIUM); the `_Moved` signal is now a private exception
   raised by `_atomic_replace` (return type stays `str | None`), so a
   non-`expected` caller can never receive it (chunk 1 LOW 2); the quoted
   return annotation is gone (LOW 4); the 22-line check-site comment is
   six lines plus pointers (LOW 5); the markdown rollback test now asserts
   `"rolled back" in result.reason` and the refusal/rollback tests assert
   the whole tree, not just the destination bytes (chunk 2 findings 1-2 —
   those two tests then moved to #244 with the split; the service refusal
   test's tree/fixture assertions and the HTTP refusal test's no-ledger
   check stay here); the residual-loss docstring now says "at least this
   window" (chunk 2 finding 3 — it passes with the check sabotaged away,
   so it pinned "at least", not "exactly"); this log's header, test split
   (the honest count is 61 pre-existing + 8 new, not 66 + 3), the
   `apply_edit` line cite, and the superseded "The fix" steps are fixed
   (chunk 1 findings 6-9).
4. **Deferred, named:** `_apply_locked` has the same two-read gap
   (file_revision at 472, `_atomic_replace` at 476); folding `expected`
   into that call is the same one-argument change for the apply half of
   the class, out of this ticket's scope (chunk 1 LOW 3).

Focused on this pass: 67 passed (61 pre-existing + 6 new — the 5 race/HTTP
tests + the residual-gap canary; the 2 rollback tests are #244's). Sabotage:
dropping the `expected` argument fails all 5 race/HTTP tests; restoring is
green. After rebasing this pass onto `7e49a20` (the #242/#247 merges, no
change to `edit.py`): focused 67 passed again, full suite
**3870 passed, 2 skipped**, ruff (`--select E9,F src tests`) clean.



