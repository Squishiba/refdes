# EDITOR-API-007 — the create path silently ate a concurrent destination write

Task: fix EDITOR-API-007 (`in-prog-logs/current-main-resweep-editor-revision.tsv`)
at the pinned origin/main HEAD `8b6a52e`. Status: **finished**, committed on
this worktree's branch (hash at the end of this log), not pushed.

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
(l :461-469) has always had against the same class of writer. What the fix
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
