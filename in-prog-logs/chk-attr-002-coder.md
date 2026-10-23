# chk-attr-002 — imported item diagnostics attributed to `<import:NAME>:1`

Task: imported items reported diagnostics at the fabricated
`<import:platform>:1` pseudo-path; the artifact's own `source.file`/
`source.line` were discarded in `imports._absorb`.

## Change

`src/refdes/imports.py`:

- Added `_upstream_source(origin, raw)` (bottom of file): if the artifact
  record's `source` is a dict with a string `file` and an integer `line`
  (booleans rejected, as `bool` subclasses `int`), returns
  `(f"{origin}:{file}", line)`; otherwise the old
  `(<import:origin>, 1)` fallback.
- `_absorb` now calls it and passes the result into the `Item`. Nothing
  else touched — items stay `external=True` with the same ids/keys/hashes.

`changelog.d/imported-item-diagnostic-source.fixed.md`: fragment in the
style of the existing `.fixed.md` fragments.

## Dependency checks (per contract)

- `grep` over `src/`: `imports.py` was the only producer of the
  `<import:` spelling; nothing reads it. (`image_freeze.py:43`'s
  `startswith("<")` is image-link syntax, unrelated.)
- Write refusals gate on the `external` flag, not on the path:
  `serve/edit.py:403`, `serve/api.py:187`, `build.py:950`.
- `editors/vscode/extension.js:176` skips diagnostics whose file starts
  with `<`; the new `platform:items/...` location will no longer be
  skipped there, and the extension would try to open a path that does not
  exist locally. Out of scope for this task (file not in the allowed
  touch-list) — flagging it for the editor owner.
- `tests/test_lifecycle.py:1225,1249` construct `Diagnostic(file=
  "<import:upstream>")` as literals; unaffected, and the suite passes.

## Verification

- Probe in `.scratch/chk-attr-002/probe.py` (run dirs `run1`/`run2`):
  real upstream build → artifact, downstream import named `platform`,
  upstream item with dangling `refines`. Check reports
  `ERROR platform:items/req.yaml:3 [REQ-001] ...`; local control item
  keeps `items/req.yaml:3 [REQ-002]`; hand-written artifact with the
  `source` key deleted falls back to `<import:platform>:1` with no
  crash. All three asserted ("PROBE OK").
- `PYTHONPATH=src ... -m pytest -q tests/test_imports.py` → 10 passed.
- Full suite `pytest -q tests/` → 4386 passed, 2 skipped.

Status: finished.

## PR #361 review round

Review approved the core change and required the VS Code follow-through
(the blind phase ended; editors/ is now in scope), done on this branch:

- `editors/vscode/extension.js`: new named helper
  `isImportedItemPath(file)` -- skips the `<` pseudo-path **and**
  import-qualified paths (first segment before `/` or `\` contains a `:`
  that is not a Windows drive letter: one letter, colon, separator), so
  `platform:items/req.yaml` no longer publishes a phantom diagnostic at
  `<workspace>/platform:items/req.yaml`; `C:\...` absolutes keep the
  existing absolute-path handling. `publishDiagnostics` now calls the
  helper.
- Test: the extension does have a JS test setup -- pytest extracts JS
  functions verbatim from the source and runs them under node -- so
  `tests/test_vscode_extension.py` gained
  `test_imported_item_paths_are_never_published_as_files` on that
  pattern, pinning 10 spellings (pseudo-path, import-qualified with both
  separators, no-separator, drive-relative `C:items.json` -> skip; local
  relative, POSIX/Windows absolutes -> publish). node v22 present; all 10
  tests in the file pass.
- Changelog fragment: added the sentence that the VS Code extension keeps
  ignoring imported-item diagnostics.
- `tests/test_imports.py` re-run: 10 passed.

## PR #361 review round 2 (P2: import names may contain "/")

Reviewer reproduced: `imports[].name` is an unrestricted string
(configcheck.py ~527 takes any non-empty `self.string`), so an import
named `vendor/platform` yields `vendor/platform:items/req.yaml`, whose
first segment `vendor` has no colon -- the segment-based helper missed it
and a phantom diagnostic was published.

- Rewrote `isImportedItemPath` to decide on the first colon in the WHOLE
  string: no colon -> false; colon at index 1 with a letter at index 0
  and a separator at index 2 (`C:\x`, `C:/x`) -> false (real drive path);
  anything else with a colon -> true. `<` rule kept. Comment now names
  the "/"-in-name case and documents the one-sentence trade-off: a local
  path with a colon outside a drive prefix is treated as import-qualified
  and stays out of the panel.
- Test cases now include `vendor/platform:items/req.yaml` -> true and
  the reviewer's exact list; the Windows-absolute cases are the
  reviewer's `C:\work\x.md`/`C:/work/x.md` spellings.
- `tests/test_vscode_extension.py` (11) + `tests/test_imports.py` (10) +
  `tests/test_import_diagnostic_source.py` (5): 26 passed.
