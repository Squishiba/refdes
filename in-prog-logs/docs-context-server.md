# DC-2-tests: contract tests for the docs-context viewer server

Slice: TEST AUTHOR ONLY. Wrote `tests/test_docs_context_server.py` red-first
for `tools/docs_context/server.py` (not implemented — an implementer continues
on this branch). Nothing under `tools/` was created.

## What the tests pin (spec DC-2)

- `make_server(doc, repo, port=0) -> (httpd, base_url)`; binds 127.0.0.1,
  ephemeral port; run in a thread, always shut down in a `finally`.
- CLI: one flushed banner line `docs-context: http://127.0.0.1:<port>/`,
  `--no-open` accepted, default `--repo` found upward via the fixture `.git`,
  exit 2 + stderr for missing / non-.md / outside-repo docs.
- Routes: `/` (index.html), `/static/<name>` (name-regex only), `/api/doc`
  (blocks equal to `refs.analyze`, repo-relative `doc`, fresh-on-edit, cached
  by (mtime_ns, size) via a resolve counter), `/api/mtime` (stat-only, proved
  by patching `refs.analyze`/`refs.parse_doc` to raise), `/api/file` (±15
  window, refs.py error cards, 400 on missing/non-int line).
- Security: forged/wrong-port Host -> 403 `bad host`; nosniff + no-store on
  200/404/405/403; no CORS headers; repo tree snapshot (sha256 of names+
  bytes) equal after hitting every route; traversal matrix (`../`, `%2e%2e`,
  backslash, `%00`, absolute, `.git/`, symlink-out skipif nt) with
  `builtins.open` recording proving nothing outside the repo is opened;
  HEAD requests leave the server answering.
- Static page: served byte-identical, app.js JS content-type, index.html
  references `/static/app.js`, no inline `<script>` body, no http(s):// URLs,
  app.js free of innerHTML/eval/new-Function and polls `/api/mtime`.

## Notes

- Import pattern copies DC-1 (`sys.path` insert of `tools/`, namespace import
  `from docs_context import refs, server`); the server is imported by module
  attribute contract (`refs.resolve` patchable, i.e. server.py does
  `from docs_context import refs` and calls `refs.resolve` — per spec).
- Probes in the traversal matrix are given in WIRE form (server decodes once);
  `quote()`-encoding of probes was the one self-inflicted red I fixed while
  writing (double-encoding made `%2e%2e` probes test nothing).
- Cross-platform: all fixtures `newline=''`/`write_bytes`, snapshots use
  `as_posix()`, symlink probes guarded by `os.name != "nt"`, every client
  socket has a timeout, banner read via a deadline thread (no `select`),
  servers/children killed in `finally`. Verified: ruff clean on the file;
  `scan_source` (crossplatform lint) reports zero findings for it.
- RED evidence (run this slice): collection fails with
  `ImportError: cannot import name 'server' from 'docs_context'` — every test
  is red at import for the missing module, as required. Full suite not run
  (per task instruction).

Status: done. 31 tests, all red on the missing `server.py`.
