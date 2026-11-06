# DC-4a-tests: contract tests for "follow the editor" (red-first)

Task: write the red-first contract tests for the docs-context viewer's
follow-the-editor feature (slice DC-4a-tests) on branch
`feat/docs-context-focus`, touching only `tests/test_docs_context_focus.py`
and this log. No `tools/` changes — the implementer adds the
`POST`/`GET /api/focus` pair in `server.py` and the follow control in
`static/app.js`/`static/index.html`. DC-4b (the VS Code extension that posts
the cursor) is a later slice and not tested here.

## What the tests pin

- `POST /api/focus` `{path, line}`: block under the cursor computed from the
  server's OWN cached analysis — block containing the line, else the nearest
  block starting at or before it, else the first block; a line past the last
  block clamps to the last. `./` normalised; any other path (incl. `..`,
  absolute, NUL, case-variants) is `200 {followed:false, reason:"other-doc"}`
  by string comparison alone, asserted never opened via a `builtins.open`
  recorder. Guards mirror `/api/ask`: Host, `X-Docs-Context: 1`, own-Origin,
  415 on non-JSON, 1024-byte body cap (exactly-1024 accepted, over-1024
  drained without desync), types/`line` range 1..10_000_000, nosniff/no-store,
  no CORS.
- The accepted focus lives in memory only (tree-snapshot test); `GET /api/focus`
  returns `{seq, line, block, path}` (seq 0 + nulls before any POST), is cheap
  (analyze/parse_doc monkeypatched to raise), increments seq on every accepted
  POST incl. the same line twice (a concurrency test: 8 parallel posts ->
  seq 8), and leaves the remembered focus untouched for other-doc/4xx.
- Cache sharing: a focus POST on an unchanged file adds zero `refs.resolve`
  calls (the ask/server monkeypatch-counter pattern); after an edit the next
  POST reflects the NEW analysis.
- `app.js`: polls `/api/focus` inside the existing `tick()` (asserted: exactly
  one `setInterval`), a `follow` checkbox read via `.checked`, focus-driven
  `select()` + a second `scrollIntoView` call site, the comment string
  "manual selection wins until the next focus", textContent-only DOM.
  `index.html`: `<input type="checkbox" id="follow" checked>` in a label that
  says follow, still no inline script / external URLs.

## Ambiguities resolved (pinned in the module docstring)

- GET `path` = the served doc's repo-relative path always (spec types it
  `str`; nulls are line/block only).
- "accepted" = answered `followed:true`: other-doc POSTs and 4xx change
  nothing, not even seq.
- POST responses carry exactly the enumerated keys (no seq in the POST reply).
- Body of exactly 1024 bytes accepted; extra keys ignored (as on `/api/ask`).

## Status

- Red: `28 failed` on the untouched tree (every test, for the missing route
  404/405 or the missing markup/strings — no collection errors, no typos).
- Satisfiability: a throwaway prototype (focus struct + route in `server.py`,
  poll + checkbox in `app.js`/`index.html`) turns all 28 green; with it,
  focus+server+ask+refs+crossplatform-lint = 178 passed. The prototype was
  reverted; the tree carries only the test file.
- `ruff check` clean on the touched file; slowest test 1.14 s; every client
  call has a socket timeout, servers are port 0 and shut down in `finally`.
- Full suite not run: this slice is red by design (test-only), per the task.

Finished: tests committed on `feat/docs-context-focus`, no PR (per task).
