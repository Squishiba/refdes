# N6.2a-tests: red-first wire tests for ServeClient.post()

Task: create `tests/test_vscode_extension_http_client.py` only — contract
tests for the planned `ServeClient.post(pathname, body)` plus
`navisArchive`/`navisRestore`/`navisMint` wrappers, against live
`refdes serve`. Slice S6.2's client half; plan
`docs/design/navis-vscode-panel-plan.md` §4 (headers/routes/mapping) and §7.3
(line 303: "node driving the real serveClient.js ... against a live
EditorApp"). Base `c47812b5`, branch `feat/n62a-serve-post`, tree clean at
start.

## What landed

One new file, `tests/test_vscode_extension_http_client.py` (~620 lines),
nothing under `editors/`, no existing test touched. Four scenario groups,
one node process each (the neighbours' cross-platform posture: `shutil.which
("node")` + skipif, `NODE_TIMEOUT_S=120`, `encoding="utf-8"` on node stdout,
fixtures `newline=""`, port 0, bounded thread/process timeouts).

1. **Live writable** — real `EditorApp` on port 0 (project: two
   hand-fabricated keys sharing a 6-char prefix for the 409, plus a
   keyless multibyte marker added after a writable `navis ls` so the mint
   has a target), real `serveClient.js` attached via `ServeClient.attach`.
   Pins the §4 result table on the wire: archive 200/`changed:true`,
   re-archive `changed:false`, restore 200, restore-active 409
   `not_archived`, mint 200 `changed:true` → idempotent `changed:false`,
   minted multibyte key archived/restores with the key on disk, 404
   `not_found`, 409 `ambiguous` with `candidates`, and a raw-http control
   pair (localhost-Origin on Host 127.0.0.1 → 403 "forbidden"; matching
   Origin → 200).
2. **Live `--no-write`** (`read_only=True`) — all three wrappers get 403
   with the JSON **parsed** (`kind:"refused"`, `--no-write` in the error),
   disk unchanged via `snapshot_tree`. This is the pin the GET path cannot
   satisfy (GET hands non-200 bodies back as strings).
3. **Capture server** — stdlib `http.server` on port 0 records the exact
   bytes; a `HangServer` accepts and never answers; a closed port is
   refused. Pins method/path/body bytes, `Origin` == the IPv4 form,
   `Content-Type`/`Accept` json, the token header (from
   `security.TOKEN_HEADER`, two-sided), `Content-Length` == UTF-8 **byte**
   length of a multibyte body (with an assertion that bytes > chars, the
   JS-string-length trap), no `Transfer-Encoding`, the 500-HTML → raw-text
   / 409-JSON → parsed-object split, the token never leaking through
   V8's JSON.parse error quote, not-ready → the exact
   `"refdes serve is not running"`, refused → `{error}` in bounded time,
   hang → `{error}` on the client's own 10 s timeout.
4. **Source pins** — `post(pathname, body)` signature, its body naming
   `method: "POST"`, the explicit `http://127.0.0.1:` + `this.port` Origin,
   `application/json`, `TOKEN_HEADER`, `Content-Length` from
   `Buffer.byteLength`, no `Transfer-Encoding` in the file; the three
   wrappers delegating to `this.post` with the exact routes/bodies; the
   token in the header line only.

## RED evidence (untouched tree, `c47812b5`)

`pytest tests/test_vscode_extension_http_client.py`: **6 failed, 2 passed**
in 1.4 s. The 6 failures are exactly the post()/wrapper probes — the
drivers report
`{post: false, navisArchive: false, navisRestore: false, navisMint: false}`
and the source pins fail on "no post(pathname, body)". The 2 passes are
GREEN BY CONSTRUCTION guards, named as such in the module docstring: no
`require("vscode")` and the §4 write ban over `serveClient.js` (the S6.2
additions are POSTs, not file writes).

## Full suite (once, before push)

`pytest -q -n 4 --dist worksteal`: **6125 passed, 2 skipped, 6 failed** —
the 6 are this file's reds. `ruff check --select E9,F src tests` clean;
`test_crossplatform_lint.py` 26 passed; `ruff check` on the new file clean.

## Ambiguity resolutions (pinned in the module docstring)

- Live servers can never receive a non-ASCII selector (selectors are
  keys/ordinals), so the multibyte `Content-Length` byte-count is pinned
  on the capture server (arbitrary body); the live half pins a multibyte
  Navi *text* round-tripping (minted marker bytes on disk + archive of the
  minted key). Plan §4 line 182-187.
- Restore-of-active = 409 `not_archived` (docs/navis.md:372, captured).
- Origin control is raw http in the driver (not through `post()`) — a
  dropped explicit Origin hits exactly that 403 wall (security.py:57-65).
- Hang case rides the client's existing `REQUEST_TIMEOUT_MS=10000`
  (serveClient.js:40): `{error: "timed out"}`, bounded.
- Method names/signatures pinned: `post(pathname, body)`,
  `navisArchive(selector)`/`navisRestore(selector)` →
  `post("/api/navis/archive|restore", {navi: selector})`,
  `navisMint()` → `post("/api/navis/mint", {})` (plan §4 lines 167-173,
  docs/navis.md "The serve API").

## Not verified here (by construction)

Any VS Code UI behavior (plan §7.2: needs a real window; the manual
checklist is Jared's). The `start()`-spawned child dying mid-request: the
plan §7.3 "dead child yields an error object not a hang" sentence is
pinned via refused/hang/not-ready `{error}` shapes — a real spawned child
is exercised by the shipped launch-line tests, and the wire result of
dialing a dead port is the same `{error}` contract.

Status: test-author half complete.

## N6.2a-impl (implementer half)

Implemented `post(pathname, body)` + `navisArchive`/`navisRestore`/
`navisMint` in `editors/vscode/serveClient.js` only (89 inserted lines,
0 removed — GET path byte-identical). Headers per §4: explicit
`Origin: http://127.0.0.1:<port>` from `this.port`, `Content-Type`/
`Accept: application/json`, `[TOKEN_HEADER]: this.token`,
`Content-Length: Buffer.byteLength(payload)`; JSON-parsed body for every
status, raw text on non-200 parse failure, `{error}` (no `${err}`
interpolation — V8 quotes a body slice) on 200 parse failure, not-ready
literal, refused/timeout `{error}` on the 10 s timeout. Added
`changelog.d/navis-vscode-post.added.md`.

Red→green: 6 failed / 2 passed before → 7 passed / 1 failed after the
implementation; 8 passed after the authorised test fix below.

**Structurally-red test — reported, then fixed by authoriser ruling:**
`test_a_no_write_server_refuses_all_three_and_the_json_reaches_the_caller`
passed every wire assertion (3x 403, parsed `kind:"refused"`,
`--no-write` in the error) and failed only its final
`snapshot_tree(root) == before`: the test's own `run_client` wrote
`post-driver.js` into `tmp_path`, which the `no_write` fixture *is* the
project root. Reported first (hard rule 1); the authoriser then approved
exactly one narrow edit to that test: driver script goes to
`tmp_path_factory.mktemp("driver")` (signature `tmp_path` →
`tmp_path_factory`), project root and fixture untouched, snapshot
assertion unchanged. Control probe: writing a stray file into `root`
inside the test makes it fail (removed after).

Tests run: new file (8/8), test_vscode_extension.py,
test_vscode_adapter_contract.py, test_vscode_navis_tree.py,
test_vscode_docs_focus.py, test_crossplatform_lint.py — all green;
`node --check` clean. Pre-fix CI (heads 5ac94ea/e956d2b): pr-size
pass; the three Tests jobs failed on exactly the one test above
(ubuntu 1 failed/6124 passed/8 skipped, windows 1 failed/6038
passed/94 skipped). Post-fix CI is expected green on all four checks.
No real VS Code window: this slice has no UI, so only the wire
contract is proven.

Status: implementation complete.
