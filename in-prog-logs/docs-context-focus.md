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

# DC-4a-impl: the focus route + follow control (green)

Task: implement `POST`/`GET /api/focus` in `server.py` (reusing the
`/api/ask` guards, factored shared, no `/api/ask` behaviour change) and the
follow checkbox + focus polling in `static/app.js`/`index.html`/`style.css`
so the red file passes. In-memory focus only; never writes; never opens the
posted path.

## What landed

- `server.py`: `_json_post(max_body)` factors the shared ask guards
  (X-Docs-Context, own-Origin, 415, drained body + size cap) and
  `_json_object` the shared decode/400 split — `/api/ask` behaviour
  byte-identical (same 403/415/400 responses). `DocState` gains
  `focus_lock/seq/line/block`, `focus_payload()` (GET, reads fields only,
  never parses), `block_at()` (containing block, else nearest start <=,
  else first; past-last clamps; from the SAME `(mtime_ns, size)` cache as
  `/api/doc`), `accept_focus()`. `_focus`: types/range on
  `{path, line}`, path == served doc by string compare after
  `removeprefix("./")` — never opened; other path ->
  `{"followed": false, "reason": "other-doc"}`. Routing: POST `/api/focus`
  only; GET reports; other methods 405 (unchanged paths keep 405).
- `app.js`: `pollFocus()` inside the EXISTING `tick()` (one setInterval
  kept); seq de-dupe server-side, block de-dupe client-side; follow
  checkbox gates moves; a new seq selects + scrolls (`scrollIntoView`,
  2nd call site); the "manual selection wins until the next focus" rule
  documented in the code; textContent-only DOM.
- `index.html`: `<label id="follow-label"><input type="checkbox" id="follow"
  checked>follow the editor</label>` in the header; no inline script, no
  external URLs. `style.css`: follow-label/checkbox styling.
- Changelog: extended the UNRELEASED `docs-context-server.added.md` with a
  follow-the-editor paragraph (DC-3 precedent: it appended to the same
  fragment).

## Verification

- Red confirmed first (28 failed on the base commit), then green:
  focus+server+ask+refs+crossplatform-lint = 178 passed. `ruff check`
  clean on `server.py` + the test file. Full suite ONCE: 5966 passed,
  2 skipped.
- Real browsers (Chromium + Firefox, port 8890, serving `docs/navis.md`
  from this worktree; server stopped by PID after checking
  `/proc/<pid>/cwd`): all six cases PASS in BOTH browsers — (a) a focused
  block gets `aria-current` and is scrolled into view within ~1.5 s;
  (b) follow off: a POST moves nothing, re-check: the next POST moves;
  (c) a manual click survives later polls with no new POST; (d) a POST
  for another path answers `{"followed": false}` and moves nothing;
  (e) no-header / foreign-Origin POSTs are 403 (own-Origin 200); (f) a
  hostile posted path/HTML appears nowhere in the page (textContent,
  title, no img, no inline scripts) — the accepted POST echoes only
  numbers. No page errors.

Status: DONE (this slice). Tests unedited, as required.
