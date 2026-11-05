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

# DC-2-impl: the server and the page (this slice)

Implemented `tools/docs_context/server.py` + `static/{index.html,app.js,style.css}`
against the contract file. No test edits; no src/ changes; docs/ untouched.
Path safety is refs.py's, imported: `/api/file` runs `refs._read_text_file`
(error cards, never an open outside the repo), `/api/doc?path=` validates
against the same realpath/`.git` posture for its 400-vs-404 split. Stdlib
only, ThreadingHTTPServer on 127.0.0.1, GET/HEAD + 405 JSON for the rest,
Host allowlist (name AND port), nosniff + no-store everywhere, no CORS,
`/static` by strict name regex (raw wire path, so `%2e%2e`/`%00` probes die
on the regex). `/api/doc` cached by (mtime_ns, size) per page; `/api/mtime`
is stat-only. CLI: one banner line on stdout, `--no-open`, repo found upward
via `.git`/`refdes-project.yaml`, exit 2 (stderr) for missing/non-.md/
outside-repo docs. The page: block list (kind, lines, flagged-count badge,
~200-char label with ref spans underlined), cards per ref (numbered code
window with cited lines highlighted, command verbs + known/unknown + help
pre, link target/anchor badges + heading/excerpt, external links as plain
text), header "N blocks, M refs, K flagged", j/k + arrows, aria-current,
1.5 s mtime poll with selection (by start_line, else nearest) and scroll
preserved. All untrusted text via textContent/createElement. Light/dark via
prefers-color-scheme; columns stack <=760px, no overflow at 375.

## Test bug found (NOT edited, per task rule 1)

`request()` (tests/test_docs_context_server.py:148) passes `headers=None`
into `http.client.HTTPConnection.request()`; on Python 3.13 that raises
`TypeError: 'NoneType' object is not iterable` client-side before any
request is sent. 23 of the 31 tests die in the test process, not in the
server. Proposed one-line change: `headers=headers or {}`. Evidence: with
only that change (a copy of the file under .scratch/, repo test file
untouched), 31/31 pass. Unaffected-by-the-bug tests (CLI banner/exit codes,
static text checks, host guard -- all raw sockets) pass as written: 8/8.

## Evidence

- 31/31 (patched copy), 8/8 (raw-socket subset), refs 58 + crossplatform
  lint pass, ruff clean on server.py.
- Real browsers, PASS in Chromium (headless, /usr/bin/chromium) and Firefox
  (playwright-core) for: block list (58 blocks, summary "58 blocks, 34 refs,
  2 flagged"); command card known + usage: help; link card target/anchor ok
  + heading + excerpt; broken doc (stale path:line, missing file, broken
  anchor, unknown command) -> 4 flag badges + flags; live edit appends a
  paragraph -> re-render <4 s keeping selection (line 31) and scrollTop
  (400->400); hostile doc (<script>/<img onerror> in paragraph AND heading)
  renders literally, window.__pwn undefined, 1 script (app.js), 0 img;
  375x640 stacked, scrollWidth==innerWidth. Screenshots: .scratch/browser/.
- Known cost: first analyze of a command-heavy page (navis.md, 21 known
  commands) takes ~8.4 s -- DC-1's `_help_subprocess` spawns one subprocess
  per card, uncached. Later requests hit the (mtime, size) cache. A card-
  level cache is DC-3 material; the page shows "loading…" meanwhile.
- The harness's first broken-doc draft flagged "target page not found" on a
  page-relative link (`docs/navis.md#...` from .scratch/browser/) -- correct
  behavior; the harness doc, not the product, was fixed.

Status: done. All slice DC-2-impl deliverables landed; the contract file
itself stays red on the client-side `headers=None` bug pending authorization
of the one-line fix.
