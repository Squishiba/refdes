# fix(vscode): ServeClient.post with no body sends an empty JSON object

Task: `ServeClient.post(pathname, body)` (added in #458) breaks when `body`
is `undefined`: `JSON.stringify(undefined)` is `undefined`, so the
`Buffer.byteLength(payload)` in the header block throws a TypeError *inside*
the promise executor — the returned promise rejects with `ERR_INVALID_ARG_TYPE`
and no request is ever made. Callers today (`navisArchive`/`navisRestore`
pass `{navi: selector}`, `navisMint` passes `{}`) always pass a body, so the
bug is latent, not live.

## What I read / ran

- `editors/vscode/serveClient.js` (`request`, `post`, the three navis
  wrappers), `editors/vscode/navisActions.js` (pure answerer — it never calls
  `post()` itself; `planResult` branches on `body.kind`), `grep -rn "\.post("`
  over `editors/vscode/*.js`: no path-only caller exists.
- `src/refdes/serve/server.py:_api` (POST path) and
  `src/refdes/serve/navis_write.py:handle`.
- Ran a real writable `refdes serve` (`.scratch/probe-post-body/probe.py`,
  `PYTHONPATH=<worktree>/src`, port 0) and raw-POSTed the cases:
  - `{}` + `application/json` → mint 200 `kind:"ok"`; archive 400
    `kind:"bad_request"` "navi is required: ..." (a kind-carrying body)
  - empty body (`Content-Length: 0`) → 400 `{"error":"invalid JSON"}` —
    **no `kind`**, which is exactly what `navisActions.planResult` reads
  - JSON `null` / `[1]` / `5` → 400 `kind:"bad_request"` "expected a JSON
    object" (`navis_write.py:57-58`)
  - missing / wrong `Content-Type` → 415; missing `Content-Length` → 411

## Decision (narrowest)

- `post(path)` / `post(path, undefined)` → send `{}` with
  `Content-Type: application/json`, byte-identical to today's explicit `{}`.
  Chosen over "send no body" because the server's empty-body 400 carries no
  `kind` to branch on.
- `post(path, null)` → unchanged: `JSON.stringify(null)` is `"null"`, so the
  wire body is the 4-byte `null` literal and the server's `kind:"bad_request"`
  answers it. Pinning it keeps the fix from over-reaching.
- A body `JSON.stringify` refuses (circular, BigInt) → the promise REJECTS
  with a plain `Error` naming the problem, from a `try/catch` inside the
  executor: never a synchronous throw, never a hang, never unhandled.
- Only `serveClient.js` changed (src/ untouched, so the #402 size gate is a
  non-issue). No changelog.d fragment: not user-visible.

## Red → green

New file only, `tests/test_vscode_post_body.py` (8 tests; harness style
copied from `tests/test_vscode_extension_http_client.py`: node + real
serveClient.js, capture server for the bytes, live writable `EditorApp`,
`encoding="utf-8"`, `newline=""` fixtures, skipif no node).

Before the fix, 4 failed / 4 passed:

- `test_post_with_no_body_sends_an_empty_json_object_on_the_wire` — FAIL:
  the capture server saw 3 requests where 5 belong (the two no-body calls
  never dial), and both record a rejection instead of `{status: 200}`.
- `test_post_with_no_body_reaches_a_real_server_as_an_empty_json_object` —
  FAIL: `post("/api/navis/mint")` rejects, so no key is minted.
- `test_a_circular_body_rejects_the_promise_with_an_error_naming_the_problem`
  — FAIL on its wire-traffic guard (3 captures ≠ 5), same root cause.
- `test_post_with_an_object_body_is_unchanged` — FAIL, and this one was MY
  bug: I asserted `Content-Length: 6` for `{"a":1}`, which is 7 bytes. Fixed
  in the test; the server-side claim was never involved.

Green (named as pins, green by construction today): the `null` literal, the
BigInt rejection, the not-ready literal, and the clean exit. After the fix:
`8 passed`.

## Verification

- `tests/test_vscode_post_body.py` 8 passed.
- `tests/test_vscode_extension_http_client.py`, `test_vscode_navis_actions.py`,
  `test_vscode_extension.py`, `test_vscode_navis_tree.py`,
  `test_vscode_adapter_contract.py`, `test_vscode_docs_focus.py`,
  `test_vscode_post_body.py` → 98 passed (the source pins over
  `serveClient.js` — the `post(pathname, body) {` signature, the explicit
  Origin/Content-Type/`Buffer.byteLength` pins, the token-never-in-an-error
  pin — all hold with the fix).
- `tests/test_crossplatform_lint.py` 26 passed.
- `ruff check tests/test_vscode_post_body.py` clean (one RUF059 fixed);
  `serveClient.js` is not a Python file, and the repo is not ruff-clean
  overall so no wider run.
- Full suite once: 6258 passed, 2 skipped.

## After the merge (origin/main had moved to #466)

Merged origin/main (a plain merge, no rebase) and re-verified on the merged
tree. The merge brought the first real `post()` caller surface,
`editors/vscode/navisCommands.js` (N6.2b-2): `grep` shows it calls only
`client.navisArchive(selector)` / `navisRestore(selector)` / `navisMint()`
(navisCommands.js:173-174, 228) and never `post()` itself, so the fix changes
nothing it sends. Full vscode set (`tests/test_vscode*.py`, 8 files incl. the
new `test_vscode_navis_commands.py`): 124 passed. Full suite on the merged
tree: 6288 passed, 2 skipped.

## Notes for the reviewer

- `tests/test_vscode_extension_http_client.py`'s module docstring says post()
  "Never rejects". That prose sketch predates this task's decision; per the
  task's "do not edit existing tests" I left it alone — the new file's header
  states the refined contract, and post() rejects only for a body that cannot
  be serialised (a caller bug), never for anything the wire can carry.
- Not verified: nothing on a real Windows runner (no Windows box here). The
  new tests follow the cross-platform rules (utf-8 node decoding,
  `newline=""` fixtures, no POSIX-only tools, no path-separator assertions);
  CI's windows job is the real check.
