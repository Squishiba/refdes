# VS Code activation regression test

Task: add the one named test `docs/design/editor-vscode-adapter.md` §7.2
(~line 576) names but that did not exist — `test_extension_activates_on_current_project_marker`
— as the regression guard for the bug PR #58 fixed: the extension's activation
glob and `findRoot()` both looked for the retired `refdes.yaml`, so the
extension never activated in a project holding `refdes-project.yaml`.

## What landed

- `tests/test_vscode_extension.py` (new, one test, read-only):
  - parses `editors/vscode/package.json` as JSON; asserts `activationEvents`
    contains a glob naming `refdes-project.yaml` and that no entry matches the
    retired-name regex `(?<![\w.-])refdes\.yaml\b` (which cannot match
    `refdes-project.yaml`, so no false positive);
  - extracts the `findRoot` function body from `editors/vscode/extension.js`
    by regex (asserting loudly if the function is gone), and asserts the body
    names `refdes-project.yaml` and never the retired name.
  - each assertion's message names the file and field that regressed.
- Scope kept to exactly that named test. `test_no_direct_item_file_writes_in_extension_source`
  is a separate named test and deliberately not added here.

## Verification

- `pytest -q tests/test_vscode_extension.py -v` → 1 passed in 0.02s.
- Full `pytest -q -x` → 2500 passed, 2 skipped in 165.01s.
- `ruff check tests/test_vscode_extension.py --select I` → All checks passed.
- Loud-failure checked out-of-band (no writes to the extension files): against
  a scratch copy of a `findRoot` that checks `refdes.yaml`, the body assertion
  reports `names project marker: False` and `retired hits: ['refdes.yaml']`,
  i.e. both halves of the guard fire on the old code.

## Changelog fragment: skipped

`changelog.d/README.md` — "Each change that deserves a changelog entry gets one
fragment". A test-only addition changes nothing a project reader sees, and the
user-visible fix already has its fragment (`vscode-activation-project-marker.fixed.md`,
from PR #58, still pending). No prior changelog entry in `CHANGELOG.md` is
purely about tests. So no fragment for this commit.
