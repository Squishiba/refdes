# Surrogate-key recovery (user simulation BUG 2)

## Investigation

- Read the complete `user-sim-release-gate-run1.md` and `docs/design/keys.md`.
  The implementation-status claim covers the implemented layers, but Layer 3
  has a real diagnostic/recovery gap when minting has no historical key record.
  Section 2 permits minting; section 3 forbids label fallback; section 6's
  missing-key guard consults baselines/seals/memberships, not inbound links.
- Read `src/refdes/adopt.py` in full. Its gate protects a transaction that
  also migrates historical hashes and storage; allowing identity inference
  here could carry history onto a different item that reused a label.
- The installed `refdes` entry point cannot import this fresh checkout
  without `PYTHONPATH=src`; all probes use that source path. Reconstruction
  lives in `.scratch/key-recovery/repro/`. `init` uses the working directory,
  so the initial explicit-config attempt refused the existing root marker;
  reran in the scratch project's directory.

## Decided locally (not blocking, recorded for review)

- **Diagnosis:** report the observable live label and its different/missing
  key, with regeneration as a possibility, not a proven history. A reused
  display id and a regenerated key can look identical. Keep key-only
  resolution and name neither deletion nor reference age as exhaustive causes.
- **Recovery:** add explicit `keys restore DISPLAY-ID@ORIGINAL-KEY ...`.
  The author confirms continuity using git/history, then supplies the original
  key. Restore the item's identity, leaving inbound references/history intact.
  Accept multiple targets so several lost keys can be repaired together.
  Keep adoption's existing gate. Considered automatic adopt-by-label and an
  adopt recovery flag; both mix identity recovery with storage migration and
  can silently attach an old reference to a replacement item. Considered
  rewriting inbound links to the new key; that abandons original identity and
  history, and changes referring content hashes/seals.
- **Validation:** build the proposed item-source overlay before any write,
  and reload after the transaction, rolling back on failure. Existing orphan
  errors may disappear, but no structural build errors may remain. A check
  violation remains allowed under the transaction engine's existing policy.
  Refuse to discard a current key recorded in history; restoration must not
  silently orphan history established under the replacement identity.

## Progress

- Reconstructed the report exactly using `init`, `id`, loss of `key:`, `id`,
  `check`, and `keys adopt`: fresh key on `GRP-001`, inbound link still carrying
  the old key, misleading original error, and adoption refusal all reproduced.
- `build.py` now consults the live display-id index only for diagnosis, with
  separate missing-label/live-label/imported-label advice. Key-only resolution
  is unchanged. The shared helper covers links, checks, and calc references.
- Implemented `key_restore.py` plus `cli.py`'s `keys restore` command. The
  source patcher has a dedicated restoration entry point; generic SetField
  remains forbidden from editing identity. Candidate validation uses the
  existing read-only source overlay, with no scratch copy or incidental writes.
- Scratch CLI dry run and real restoration succeeded; `--no-write check`
  subsequently reports `2 items, 0 errors, 0 warnings`.
- Regression tests cover the real lost-key sequence, exact diagnostic text,
  missing keys, CRLF/quoted/flow/block/Markdown preservation, idempotence,
  dry-run/--no-write byte snapshots, full validation and rollback, batch repair,
  imported ownership, historical hashes and inbound append-only seals.
- Initial related suite: 390 passed; one old diagnostic assertion needed the
  intentional new wording and one socket test was denied by the sandbox.
  Reran with sandbox escalation for the required loopback socket.

### Additional judgment recorded for review

Captured-history events (`history.py::load_events`) also record item/successor
keys. The restoration guard now includes them, not just the three older stores
listed in the key design. Discarding a captured replacement identity has the
same orphaning risk. Tests cover both event positions. Historical storage is
never rewritten or rebased by recovery.

- Related regression suite passed: 394 tests.
- Final focused recovery suite passed: 28 cases, including new checks-violation,
  concurrent-author-edit, and partial-batch-write cases. The first full run had
  2652 passes, 2 skips, and one failure in the new older-baseline fixture:
  empty Markdown is invalid, so the simulated absent item now uses a section
  block. The corrected fixture passes; a final full run is in progress.
- `ruff check --select E9,F src tests`, import sorting on the new files, and
  `git diff --check` pass. Pre-existing build.py import sorting is untouched.
- CLI verification includes `keys restore --help`, malformed-key dry-run
  refusal (exit 1), `--no-write` idempotence, and the recovered scratch project's
  unchanged inbound composite and clean check. The schema probe JSON is kept
  in `.scratch/key-recovery/schema.json` (component `part_of` inspected).
- GitHub authentication initially appeared invalid inside the network sandbox;
  the required escalation verified authentication successfully.

## Verification complete

- Final full suite: **2653 passed, 2 skipped**, 195.14 seconds, using
  `PYTHONPATH=src pytest -q --basetemp=.scratch/key-recovery/pytest-full-final`
  with the loopback socket permission required by the existing server tests.
- Full E9/F lint gate and staged diff checks passed. All changes were staged
  by explicit path; no unrelated edits are included.

Implementation, regression coverage, docs, changelog, and recorded design
decisions are complete. Publishing the `immense-dodo` branch for the requested PR.
