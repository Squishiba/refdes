# f13-3 designer — editor write-route response paths

Task: write the blind test suite for f13-3 (edit/create route JSON payloads
must not embed the server's absolute project root; replace with the
project-relative spelling at one choke-point helper). No product code.

## What was done

- Probed the live `api.handle` payloads on the base code (scratch scripts in
  `.scratch/f13-3/`) to pin which fields leak:
  - applied 200: `message` and `describe` embed the absolute target path
    (`plan.describe()` ends in `at {abs_path}:{line} [start:end]`);
  - conflict 409: `message` embeds `Conflict.path` verbatim; `diff` headers
    and diagnostics' `file` are already relative; `current_text`/`diff` carry
    the root whenever the project's own file text quotes it (verified with an
    author-pasted path in a requirement's `text`);
  - created 200: `message` embeds the destination ("created: ... in {abs}");
  - invalid 422 (enum gate) and refused 422: clean on base -> controls.
- `tests/test_serve_edit_response_paths.py`: 12 tests, thread-free
  `api.handle` drive copied from test_serve_edit_keyless_handle.py. Covers:
  applied/409/422-invalid/refused/created no-root walks, relative spelling
  with line suffix (`at items/reqs.yaml:7`, md shape too), exact
  conflict/create messages, root-in-file-text relativizing `current_text`
  and `diff`, one recursive walk over all three success/error shapes across
  three projects asserting native/separator-flipped/lowercase spellings
  absent, plus controls (payload keys, `path` field, gate wording,
  diagnostics dict, revision, handle).
- `tests/f13-3.cases.json`: node ids -> expected_on_base (8 fail / 4 pass),
  ids cross-checked against `pytest --collect-only` -- delivered on the
  frozen-test branch (the PR body's frozen test SHA), not in the PR diff.

## Verification

- On base: 8 failed / 4 passed, exactly matching the manifest.
- Both required suites stay green untouched: test_serve_edit_http.py +
  test_serve_edit_retired_ids.py = 48 passed; combined run of all three
  files shows no cross-file interference.
- Satisfiability: a throwaway pytest plugin (`.scratch/f13-3/`, not
  committed product code) wraps `api.handle` with the contract's
  relativization at the choke point; all 12 tests pass under it — the
  assertions match the contract's spelling and are not over-tight.

## Findings / notes for the implementer

- The drive must post the display id `REQ-001` to get `handle: "REQ-001"`
  back; saving through the `~` handle reports the `~` handle (existing
  EDIT-03 contract, not part of this change).
- The conflict's `message` embeds the path with no `path`-field help from
  `shown()`; the create message likewise. A single payload-walk helper at
  the return of `_apply_edit`/`_create_item` satisfies every test.

Status: finished. Tests committed; no product code touched.
