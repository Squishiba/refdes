# editor-journal-1 — blind test designer

Task: write the blind test suite for the planned
`src/refdes/editor_journal.py` (editor-save transaction journal) without
touching product code. Deliverable: `tests/test_editor_journal.py` (an
earlier draft of this log also listed
`tests/editor-journal-1.cases.json`; that file was never committed and is
not part of the PR — the mapping below was verification output, not a
deliverable).

## What was done

- 44 functional tests covering the whole contract: the `JOURNAL_DIR`
  constant; frozen `Entry`; `begin` (id return, manifest fields
  `path`/`existed`/`original_sha256`/`replacement_sha256`, originals stored
  under `orig/`, no replacement bytes journaled, unique ids,
  `JournalPending` naming id + "refdes recover", changes nothing when
  pending, all 8 unsafe-path classes + duplicates raise `ValueError` with
  no directory left behind, no staging sibling visible in `.refdes/`);
  `pending` (None / id / "unknown" for missing and garbled manifests);
  `refuse_if_pending`; `complete` incl. idempotence; `recover` (no journal
  -> `[]`, full and partial crash states, delete-created-files, report only
  changed paths in manifest order, idempotence, parent-dir creation,
  untouched non-journaled files, tampered/missing backup ->
  `JournalCorrupt` + nothing changed + journal kept, verify-all-before-
  restore, missing/garbled manifest -> journal removed + `[]`, unsafe
  manifest path -> `JournalCorrupt`, midway restore failure keeps the
  journal and a second run completes, awkward path names round-trip).
- 3 control tests (pass on base): no journal wiring in
  `src/refdes/serve/edit.py` (the real path — the contract says
  `serve/edit.py` and it lives under `src/refdes/serve/`) or
  `src/refdes/cli.py`, and a stdlib-only import check of the future module
  (vacuous pass on base).

## Design decisions / gotchas

- Functional tests import the module lazily via `_ej()` so each fails at
  base with ImportError while the controls pass at base (a module-level
  import would sink the controls).
- Manifest entry *field names* and the `orig/` subdirectory are
  contract-mandated, so tests assert them; the id key name, entries-list key
  name and `orig/` file names are implementation choices, so tests locate
  the entry list structurally and search raw manifest bytes for the id.
- Crash-during-begin semantics are tested via hand-built journal
  directories (missing manifest) and by garbling a real manifest.
- The midway-failure test chmods a target dir read-only (POSIX-only,
  skips as root; verified running, not skipped, as `jorb`).

## Verification

- Reference: a contract-faithful throwaway implementation in `.scratch/`
  (not committed) — all 45 functional tests pass against it (the 2
  repo-layout controls can't run in the scratch tree; that's the tree, not
  the tests).
- Base tree (`PYTHONPATH=src ... -m pytest -q tests/test_editor_journal.py`):
  3 controls pass, 44 functional fail (module absent).
- Checked the 47 collected node ids (44 fail / 3 pass) 1:1 against
  `--collect-only` during verification; no cases.json was delivered with
  the PR.
- `ruff check tests/test_editor_journal.py` clean.

Status: finished. No product code touched.
