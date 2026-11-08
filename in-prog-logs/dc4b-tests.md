# DC-4b-tests: red-first tests for the VS Code extension's focus posts

Task: write `tests/test_vscode_docs_focus.py` ONLY (slice DC-4b-tests) —
the VS Code side of "follow the editor". The extension
(`editors/vscode/extension.js`) must POST the active editor's cursor to a
running docs-context server (`POST /api/focus`, DC-4a, merged in #433) under
the orchestrator's conservative defaults. Nothing under `editors/` was
touched; no existing test file edited. Branch `feat/dc4b-vscode-focus`,
no PR (per task).

## Harness

The neighbouring `tests/test_vscode_extension.py` node posture is copied
(`shutil.which("node")` + skipif, `subprocess.run` JSON over stdout, fixed
timeout), extended to a whole-extension drive: a node script hooks
`Module._load` so `require("vscode")` returns a fake surface, loads the real
`extension.js`, calls `activate(context)`, fires
`onDidChangeTextEditorSelection` / `onDidChangeConfiguration` events, and
prints per-phase JSON. A real `http.server` thread on 127.0.0.1:0 in the
pytest process is the fake docs-context server: it records every POST
exactly (method, path, headers, body bytes) and a node-side
`GET /__captures` (snapshot-and-clear) lets tests interleave
"fire → sleep → snapshot" phases. Text greps cannot observe a 300 ms
debounce, so the behaviour is driven, not pattern-matched.

The workspace fixture is real on disk (findRoot/`path.relative` need real
paths): `ws/refdes-project.yaml`, `docs/a.md`, `docs/b.md`, `docs/sub/
deep.md`, root `a.md`, `outside/x.md`. `refdes.command` is pointed at a
node script that exits 1 so the index refresh activate() spawns fails fast
and silently on every platform.

## Tests (13) and the default each pins

1. `test_setting_is_declared_off_by_default` — package.json contributes
   `refdes.docsContext.url`, string, default `""` (default 1).
2. `test_empty_url_makes_no_network_call_at_all` — guard: empty setting,
   zero requests. (PASSES today by construction — the tree never posts;
   documented in the module docstring as the trivial guard, not a red pin.)
3. `test_enabled_url_posts_the_active_cursor` — POST /api/focus;
   `Content-Type: application/json`, `X-Docs-Context: 1`,
   `Origin` == configured url; body exactly `{"path": "docs/a.md",
   "line": 5}` (1-based); ONE request (default 2).
4. `test_paths_are_workspace_relative_with_forward_slashes` — nested +
   root-level relative posix paths (default 2, cross-platform).
5. `test_rapid_selection_changes_debounce_to_one_post` — five moves in
   one burst → one post with the LAST pair (300 ms debounce).
6. `test_same_path_and_line_are_not_reposted` — same pair again posts
   nothing; a changed pair posts (default 5).
7. `test_only_the_active_workspace_file_editor_is_posted` — event naming
   a non-active editor posts the ACTIVE editor's pair; untitled document
   and outside-workspace file post nothing (default 2's gate).
8. `test_pending_requests_are_not_stacked` — against a 1 s-slow server,
   six moves produce 1–2 posts, never six (drop/coalesce).
9. `test_body_carries_only_path_and_line` — body keys exactly
   `{path, line}`; the content marker appears in no body byte, header
   value, or header name (default 4).
10. `test_non_loopback_url_is_ignored_with_one_output_line` — a
    `.invalid` host posts nothing and yields one output-channel line
    naming the docs-context setting; no popup (default 3).
11. `test_localhost_and_ipv6_loopback_urls_are_honoured` — localhost url
    posts with that origin; `[::1]` is accepted (no refusal line; the
    IPv4-only server refuses it, which default 2's swallow covers).
12. `test_clearing_the_url_stops_posting_immediately` — set `""` + config
    change → the next cursor move posts nothing (default 6).
13. `test_server_errors_are_swallowed_with_one_throttled_line` — three
    500s: posts land, ≤1 output line for the burst; a closed-port burst
    adds ≤1 more; zero popups; no crash (default 2's fire-and-forget).

## Findings for the implementer (pinned, not suggestions)

- **Content-Length, not chunked.** The first prototype used bare
  `req.write(body); req.end()`, and node sent `Transfer-Encoding:
  chunked` — which the REAL DC-4a server answers with 400
  (`server.py:_read_ask_body` refuses chunked). The capture server
  decodes chunked bodies so a chunked client is still observable, and
  test 3 asserts `content-length` present and no `transfer-encoding`:
  the extension must send the body Content-Length-framed (e.g.
  `req.end(body)` with the header, `Buffer.byteLength`), or focus is
  silently dead against the real server.
- Wire facts pinned: exact header spellings as in the spec, `line` =
  `selection.active.line + 1`, path via workspaceFolders +
  `path.relative` → slash-joined.
- "one output-channel line" is pinned loosely: some line matching
  `/docs.?context/i` (the spec names the setting `refdes.docsContext.url`,
  naming it in the message is the natural vocabulary), 1..3 lines for the
  refusal burst; the refusal line must NOT appear for loopback hosts
  (checked with `/ignor|refus|host/i` absence for `[::1]`).

## Status

- Red: 12 failed / 1 passed on the untouched tree (the pass is the
  documented empty-url guard; every pin of a default fails red), ~28 s.
- Satisfiability: a throwaway prototype (focus watcher in a copy of
  `extension.js`, setting in a copy of `package.json`, driven via the
  module's env-var path overrides) turns all 13 green (~30 s). The tree
  carries only the test file. Prototype kept in `.scratch/dc4b-proto/`.
- `ruff check tests/test_vscode_docs_focus.py` clean;
  `tests/test_crossplatform_lint.py` passes (fixture writes all
  `newline=''`, no byte asserts, no platform path asserts, 3.11 syntax).
- Cross-platform notes: server on 127.0.0.1:0 with daemon threads shut
  down in the `with`; node fetches carry a 5 s timeout; the node driver
  writes its last line with `fs.writeSync(1, ...)` (an async stdout write
  to a pipe is truncated by `process.exit` — this bit the prototype run,
  8 tests saw empty stdout); driver+fixtures written `newline=''`. Full
  suite not run: red-by-design test-only slice, per task.

## Ambiguities resolved / flagged

- "inside the workspace" = under a configured `workspaceFolder` (the spec
  text), not `findRoot`; `..` is then unconstructable.
- Non-loopback judgement uses the URL hostname, so `127.0.0.1.evil.example`
  is NOT loopback (suffix tricks fail — the real server's Host guard uses
  the same rule).
- Unparseable/non-http urls are ignored SILENTLY (the spec's one line is
  for "any other host").
- The de-dupe key is the (path, line) pair, per default 5's wording;
  a config change clears it so a re-enable posts again.
- Nothing in the defaults is unworkable. One note for the orchestrator:
  "at most one throttled line" is pinned as ≤1 per burst (window length
  not pinned), and test 8 accepts 1..2 posts against the slow server
  (drop OR coalesce, per the spec's "drop or coalesce").
