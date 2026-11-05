# navis-ops extraction (slice N5.0)

Goal: move the Navis archive/restore decision logic out of `cli.py`
into `src/refdes/navis_ops.py`, a service the CLI and the coming serve
API both call (design §11: "the panel is a client of the same
projection, never a second implementation"). Behaviour-preserving
refactor only.

## What was done

- `navis_ops.py`: `select(rows, selector)` (moved verbatim from
  `_navi_select`), `apply(project_root, verb, rows, selector, *,
  allow_write)` -> frozen dataclass `Outcome(kind, row, candidates,
  changed, detail)`. `apply` performs the archive_record/restore_record
  write itself when the rules allow. It prints nothing, parses no
  argparse object, returns no exit code. Kinds: ok, noop,
  refused_no_write, ambiguous, not_found, keyless, not_archived, orphan,
  journal_pending, error. It imports only keys + navis_archive (no cli,
  no cycle).
- The `error` kind carries a `detail` string that is the text the CLI
  prints after its `error: ` prefix — str(exc) for a NavisArchiveError,
  the full "navis {verb} could not write the archive store: {exc}" for
  the OSError case, and str(exc) for journal_pending.
- `cli.py::_navis_write_verb` became a thin renderer: it calls
  `navis_ops.apply(...)`, then prints EXACTLY the same text to the same
  stream with the same exit code for every outcome kind. `show`/`ls`/
  `all` untouched. `_navi_select` kept as a one-line alias to
  `navis_ops.select` (navis show uses it).
- Net src change: +170 (new module) + 66 -106 (cli) = +130, under the
  200 target and the 350 CI gate.

## Verification

- Red-first: `tests/test_navis_ops.py` written first; with the module
  absent it fails at collection (`ImportError: cannot import name
  'navis_ops'`). After the module lands, all 15 tests pass — one per
  outcome kind, driven directly against the module (no CLI).
- Byte-identical CLI: `.scratch/navis-ops/equiv.py` drives archive and
  restore through every outcome kind (ok, noop, refused_no_write,
  ambiguous, not_found, keyless, not_archived, orphan, journal-pending,
  OSError), printing exit code, stdout, stderr, and the `.refdes/navis`
  tree (records decompressed). Random keys/timestamps are normalised to
  `<K#>`/`<TS>`. Baseline (origin/main) vs after: empty diff.
- Existing navis tests pass UNCHANGED: test_navis_archive_cli,
  test_navis_archive, test_navis{,_cli,_matrix,_mint,_mint_yaml,
  _site_panel} — 665 passed.
- Full suite: 5680 passed, 2 skipped.
- ruff (all rules) clean on `navis_ops.py` and `test_navis_ops.py`.
  cli.py shows the one pre-existing I001 (import-block sort) that is
  present on origin/main — the added `from . import navis_ops` line is
  alphabetically placed and introduces no new finding.

## Notes

- The journal-pending CLI path is gated earlier by `main()`
  (`_refuse_pending_journal`) before cmd_navis, so `refdes navis
  archive` prints main's journal refusal, not `_navis_write_verb`'s —
  the equiv probe records main's refusal, identical before/after. The
  module-level `journal_pending` kind is exercised directly in
  test_navis_ops.py, which is where the serve API will reach it.
- No docs, no changelog: internal, no user-visible change.
