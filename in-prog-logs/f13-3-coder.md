# f13-3: editor write-route responses embed the server's absolute paths

Task: 409/422/200 payloads of the editor edit and create routes quoted the
machine project root in free-text fields (`message`, `describe`, diagnostics)
while the sibling `path` field was project-relative. Required: no response
string may contain the absolute root; under-root paths become the relative
forward-slash spelling (line suffix rides along), outside-root paths must
never stay absolute; one helper at the serialization choke point.

## What was done

- `src/refdes/serve/api.py`: added `_write_outcome(app, result)` as the single
  choke point -- `handle()` now wraps the POST results of `/api/item/<ref>/edit`
  and `/api/items/create` through it (server.py:829 calls `api.handle`, and
  the tests drive `api.handle` thread-free, so both paths are covered).
  The old `_apply_edit`/`_create_item` bodies are untouched; their `shown()`
  closures stay as-is (relative `path` values pass through the scrub unchanged).
- `_relative_paths` walks the whole payload (dicts/lists/strings);
  `_relative_paths_in_text` rewrites every absolute-path token:
  - under root -> project-relative forward-slash spelling; `items/REQ-007.md:6`
    keeps its line suffix; the root itself -> `.`
  - outside root -> bare file name (documented choice in the docstring),
    `<outside project>` when there is no leaf
  - token regex has a lookbehind boundary so `http://x/y`, `and/or`, `5/6`
    and relative `path/to/x` are NOT touched (the first draft mangled
    `http://`; the `p://` reads as a drive root without the boundary)
  - drive-letter roots compare case-insensitively; both separator spellings
    match (tokens are separator-normalized before comparison)
  - on Linux a Windows-shaped root must not go through `os.path.abspath`
    (it prefixes cwd and destroys the drive spelling) -- that was the one
    real bug the scratch probe caught.
- Changelog fragment `changelog.d/editor-responses-relative-paths.fixed.md`.

## Verification

- `.scratch/f13-3/probe.py`: drives `api.handle` over the shared
  serve_support fixture project (keyless). Asserted, walking every string of
  every payload: 200 applied, 409 conflict (message/diff/current_text), 422
  invalid (diagnostics) and create all carry no root in either separator
  spelling; messages show `items/reqs.yaml`, `items/decs.yaml`, describe
  shows `items/reqs.yaml:7`. Helper unit cases: run-13 `:6` suffix, Windows
  case-fold root, outside-root basename, URL/`and/or`/`5/6` untouched,
  root->`.`.
- `PYTHONPATH=src .../pytest -q tests/test_serve_edit_http.py
  tests/test_serve_edit_retired_ids.py tests/test_serve_edit_keyless_handle.py
  tests/test_serve_upload.py` -> 168 passed, 1 skipped (the skipped upload
  case needs a case-insensitive filesystem, pre-existing).
  tests/test_vscode_extension.py + tests/test_scalar_for_list_field.py green.
- `ruff check src/refdes/serve/api.py` clean (same as the HEAD baseline).

## Review round (PR #372)

Designer's acceptance file `tests/test_serve_edit_response_paths.py` landed
(198b2d9); the windows-latest CI run failed its
`test_a_conflict_whose_file_text_names_the_root_is_all_relative`. Three
findings, all in the helpers; RED-first tests added to the same file
before each fix:

1. HIGH (Windows CI): the patcher quotes a `: `-bearing value through
   `json.dumps` (`_double_quoted`), so file bytes -- and `current_text`/
   `diff` -- carry the root DOUBLED (`C:\\Users\\...`). The per-character
   `\\`->`/` map yielded `C://Users//...`, the under-root prefix test
   failed, the token collapsed to its basename. Fix: collapse separator
   runs before comparison (`_SEP_RUNS`). Pinned platform-neutral by
   feeding the helper the `json.dumps` escaping of a Windows-shaped root
   the test names itself.
2. LOW: a root quoted *with* its trailing separator became the empty
   string, not the `.` the changelog promises. Fix: `rel = ... or "."`.
3. LOW: `_relative_paths` skipped dict keys and passed tuples through;
   the designer's payload walker covers keys. Fix: walk keys and tuple
   elements (payloads are json-shaped today -- a new guard test asserts
   that -- this is defense in depth). Docstring updated.

Verification: the 4 new tests RED before the fix (the json-shape guard
passes by design), targeted suites green, full suite green. Changelog
fragment reworded for the escaped spelling and the trailing-separator
`.`. `ruff check` on the two touched files: only the 3 RUF059 findings
that pre-exist on the designer's lines at HEAD remain; my lines are
clean (AGENTS.md: no silencing unrelated pre-existing findings).

Finished. Touched: api.py, the acceptance test file, the changelog
fragment, this log.
