# EDITOR-API-007 — the create path silently ate a concurrent destination write

Task: fix EDITOR-API-007 (`in-prog-logs/current-main-resweep-editor-revision.tsv`)
at the pinned origin/main HEAD `8b6a52e`. Status: **pushed as PR #241** (branch
`fix/editor-create-lost-update-20261013`), scoped to the check window (the
rollback-bytes half shipped separately in #244). The residual read-to-`os.replace`
gap is an **accepted, documented scope limit** (section "Scope limit"), not an
open design question.

## What was wrong

`serve/edit.py::_create_locked`, for the two append destination shapes, read
the destination file, planned the appended item against those bytes, ran the
overlay candidate gate (two full `load_readonly`s — seconds, not
microseconds), and then `_atomic_replace`d the whole file with no check in
between. The overlay masks the destination, so the gate could not see what
landed on the destination's own bytes during the gate; the replace replaced
them anyway. A writer outside the project's cross-process lock (an editor, a
sync daemon, git) had its bytes silently discarded while
`POST /api/items/create` answered `200 kind: created`. The baseline repro
(`probe_api007.py` in the resweep scratch dir): an external `REQ-777` marker
appended inside the read→replace window did not survive the create it was
reported beside.

## The fix

One seam, in `create_item`/`_create_locked` only. No request field was added
to `CreateRequest`: the browser never reads the destination file, so a
client-supplied revision would be a field the server could not meaningfully
check — the honest baseline is the bytes **this create itself read**.

1. `_create_locked` hashes the destination bytes at the moment it reads them
   (`planned_revision = sha256(raw)`, from the read itself, not a second
   `open`). That hash is the `expected` argument of `_atomic_replace`: the
   check consumes the exact bytes the replace's own read takes in, on that
   read, before a byte is written — the narrowest window a plain file allows.
   A moved destination raises the private `_Moved` (nothing written);
   `_create_locked` maps it to the private `_DestinationMoved` value.
2. `create_item` retries the whole `_create_locked` from a fresh load while
   attempts remain (`CREATE_DESTINATION_ATTEMPTS = 2`, bounded so a
   destination under steady outside writing ends in a refusal instead of
   spinning under the lock). A retry replans everything — id, key, links,
   destination shape — so the item lands *on top of* the external bytes
   instead of over them. When attempts run out it returns a `Refused` whose
   reason says the destination kept changing and to retry the creation.
3. Nothing moved that could change the ledger contract: the check and the
   retry loop sit **before** any write and before `ids.reserve_id` — a
   moved/retried/refused creation writes no bytes and burns no id. The
   commit-or-rollback behavior of #244 is untouched.

The `new-md` destination shape needed nothing: `_atomic_create` links rather
than replaces, so a file that appears underneath it is already a refusal.

## Scope limit, accepted (not an open question)

This is not an absolute conflict guarantee and does not claim to be. On a
plain file there is no atomic compare-and-swap: between `_atomic_replace`'s
read of the destination and its `os.replace` (the temp write's syscalls in
between) a writer that does not take the project lock can still land, and
its bytes are lost. That is the residual TOCTOU `apply_edit`'s own
last-moment revision check has always had against the same class of writer.
What the fix removes is the *seconds-wide* window (read → id planning →
overlay gate → replace), which is the window the repro actually hit.

The owner decided to **accept** this residual gap as the scope limit of the
ticket. Design record: portable atomic CAS is not achievable on the platforms
this package ships (POSIX has no content-conditional atomic replace —
`renameat2`'s `RENAME_NOREPLACE` is create-if-absent; Windows `ReplaceFile`
is content-unconditional) — and every cooperating writer (the CLI, every
serve route) serializes on the same lockfile, so the gap admits only a writer
that bypasses the lock. That is exactly what the module docstring,
`create_item`'s docstring and the changelog fragment claim, and
`test_the_gap_between_the_last_check_and_the_replace_is_the_residual_loss`
is the canary: a write landing in the gap is lost with `Created`, asserted —
if a real CAS ever lands the test fails and the docs get updated.

## Tests (written first, red on `8b6a52e`)

`tests/test_serve_create.py`, helper `external_writer`: deterministic seam
on `textio.append_ending` (the create's own call inside the read→replace
window), mirroring the baseline probe rather than racing on timing.

- `test_a_destination_written_between_read_and_replace_is_not_eaten` — YAML
  append: one outside write → `Created`, outside bytes survive, item lands
  after them, ledger has the new id and not the outside one.
- `test_a_moved_markdown_destination_replans_onto_the_current_bytes` — the
  repro's multi-item Markdown shape.
- `test_a_destination_that_keeps_moving_is_refused_with_nothing_burned` —
  outside write on every attempt → `Refused` ("kept changing", "retry"),
  destination exactly fixture + externals, rest of tree byte-identical,
  planned id not reserved, next honest create gets exactly that id.
- `test_http_a_raced_create_retries_and_the_outside_bytes_survive` /
  `test_http_a_persistent_race_refuses_with_a_retry_reason` — the same two
  outcomes through `POST /api/items/create` on a real in-process `EditorApp`
  (200 retried / 422 refused with the retry reason the form shows; the
  refusal asserts no ledger burn).
- `test_the_gap_between_the_last_check_and_the_replace_is_the_residual_loss`
  — the accepted-limit canary (seam: `os.replace` itself): a write landing
  in the replace's own read-to-swap gap is lost with `Created`, pinned as
  documented behavior.

Red before the fix: the five race/HTTP tests fail, the first two with the
baseline's signature ("the external write was silently replaced" + `Created`).

## Verification (current, on the tree rebased onto origin/main at `e2d497b`)

- Focused: `PYTHONPATH=src python -m pytest tests/test_serve_create.py -q`
  → **83 passed** (77 pre-existing + 6 new: 5 race/HTTP + the canary).
- Sabotage: dropping the `expected` argument fails all 5 race/HTTP tests
  (the canary passes in both states — it pins the gap, which the check does
  not close); restoring is green.
- Full suite: `PYTHONPATH=src python -m pytest -q` → **4180 passed,
  2 skipped** (~5.5 min). The shared venv's installed `refdes` points at
  the main checkout, so every run here is `PYTHONPATH=src`-prefixed (verified
  via `refdes.__file__`).
- `ruff check --select E9,F` on the touched files → clean. The repo's
  full-ruff baseline is not clean by design (AGENTS.md), untouched.
- Probe: `.scratch/fix-editor-create-lost-update/probe_api007.py` re-runs
  the baseline scenario: one-shot mover → `Created` with the marker
  preserved; persistent mover → `Refused`, planned id not reserved; honest
  retry → lands and reserves its own id intact.

## Difficulties / decisions

- Refusal-vs-retry was the design question. Edit requests carry
  `expected_revision` because the client saw the file; create requests don't
  and can't, so a `Conflict`-shaped result (draft-vs-disk diff, client
  revision) would be the wrong shape, and a client field never checked
  against disk is the superficiality the brief warns about. A server-side
  check against the create's own read, with a bounded replan, fits the
  existing posture: refusal is a value, and it burns nothing.
- The retry re-runs `_create_locked` whole rather than rebuilding just the
  text, because the fresh load is also what re-plans the id — an outside
  append can claim the number this create had picked, and a retry that kept
  the old plan would duplicate it.
- Kept the loop total at 2 attempts deliberately: the tests pin one landing
  per attempt, and bumping the constant keeps the refusal test honest.
- Deferred, named: `_apply_locked` has the same two-read gap (its
  `file_revision` check and its `_atomic_replace` call); folding `expected`
  into that call is the same change for the apply half, out of scope here.
- The 2026-10-15 reviews (independent + plugin) and the #244 split are
  history: every review finding (private `_Moved`, trimmed comments,
  changelog fragment, tree/ledger test assertions, honest counts) is in the
  shipped shape above; the rollback-bytes half shipped in #244.
- Rebase onto origin/main after #244/#253/#334: main's bytes-based rollback,
  the accept-pair lock section and the retired-rollback wording stay exactly
  as on main; the `expected` check sits on top. The stale pointer comment
  aimed at the then-unmerged #244 and the `original = text` line it described
  are gone.
