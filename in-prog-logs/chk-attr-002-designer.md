# chk-attr-002-designer — blind test design

Task: write tests for CHK-ATTR-002 (imported item diagnostics attributed to a
fabricated `<import:NAME>:1`) without touching product code. Blind to the
implementation; wrote tests from the contract only.

## What I verified on base (before writing anything)

- Reproduced the symptom end-to-end in `.scratch/chk-attr-002/`: built a real
  upstream project whose `REQ-IF001` has a dangling `refines: [REQ-MISSING]`,
  built it to `_site/items.json` (`cli build --keep-going`; the artifact is
  written despite the error), imported it downstream, ran `check`. Base output
  (stderr): `ERROR   <import:platform>:1 [REQ-IF001] — refines points at
  'REQ-MISSING', ...` while the local control reads `items/local.yaml:3`.
- Verified the artifact format per docs/output.md "Field notes": every item
  record carries `source: {"file": "items/req.yaml", "line": 3}` (path is
  project-root-relative; the item's definition line).
- Verified the diagnostic plumbing: `build.resolve_links` emits dangling-link
  errors with `file=item.source_file, line=item.source_line, item_id=item.id`
  (src/refdes/build.py ~1060), so setting the imported item's
  source_file/source_line is all the fix needs; nothing else moves.
- Verified the external-item write gate (`serve/edit.py:403` "imports are
  read-only here") is keyed on `item.external`, not on the `<import:` spelling.
- Grep: the literal `<import:` spelling is only in `imports.py:99` and two
  assertions in `tests/test_lifecycle.py` (which assert project-level import
  diagnostics, not per-item locations — untouched by this change).

## Deliverables

- `tests/test_import_diagnostic_source.py` — 6 tests:
  - 2 new-behavior (expect FAIL on base): structured location
    `platform:items/req.yaml:3` on the diagnostic, and the `check` stdout/
    stderr line text (the contract's symptom).
  - 4 controls (expect PASS on base): local item location unchanged; artifact
    record without `source` keeps `<import:platform>:1` (no crash); record
    with a `source` missing an integer line keeps the fallback; imported item
    stays external/read-only incl. the editor refusal.
- `tests/chk-attr-002.cases.json` — the node-id map with expected_on_base.

## Validation

- On base (this worktree): `2 failed, 4 passed` — the two fails are exactly
  the new-behavior tests.
- Contract compliance check: I temporarily applied a literal implementation of
  the decided behavior to `imports.py` (dict probe: string file + int line →
  `f"{origin}:{file}"`, else fallback), ran the suite green (6/6), then
  restored `imports.py` from a pre-probe copy; `git diff --stat -- src/` is
  clean. No product code is committed.

## Notes / gotchas

- The fixture's import path must be `../upstream/_site/items.json` (relative
  to the downstream root) — my first draft used a path that resolved inside
  `downstream/` and the import failed with "no artifact"; fixed.
- `check` prints diagnostics at ERROR level to stderr; summary line to stdout
  (model.Diagnostic.__str__ / cli._report), so the text assertion reads
  `capsys ... .err`.
- Running in the worktree: `PYTHONPATH=src /home/jorb/work/venv-refdes/bin/python
  -m pytest -q tests/test_import_diagnostic_source.py`.

Status: finished. Tests + cases.json + this log are the whole deliverable.
