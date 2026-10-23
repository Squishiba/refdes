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

Finished. Touched only api.py, the changelog fragment, and this log
(acceptance tests left to the designer, per the contract).
