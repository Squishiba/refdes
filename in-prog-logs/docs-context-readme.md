# docs-context README (slice DC-README)

Task: write `tools/docs_context/README.md`, the maintainer-facing README
for the docs-context viewer, with every claim grounded in files read or
commands run. Docs-only; no src/ changes.

## What landed

- `tools/docs_context/README.md` (149 lines): what it is (local viewer,
  a card per code_ref/file_ref/command/link, staleness flags), starting
  it (verbatim `--help` output, banner/exit-code behavior), the endpoint
  table (GET /api/doc, /api/mtime, /api/focus, /api/file; POST
  /api/ask, /api/focus) and the shared POST guards, follow-the-editor
  (DC-4a), ask + what llm.py needs (DC-3), the safety stance, how to
  run the tests, and what is NOT built (DC-4b VS Code extension:
  planned, not present).
- No changelog.d fragment: a tools-only README is not a user-visible
  behavior change (tools/ is not shipped; the tool itself is already
  covered by the unreleased docs-context-server.added.md fragment).

## Verification (all on 2026-11-07, venv /home/jorb/work/venv-refdes)

- `server.py --help` run; its exact output is quoted in the README.
- Live server (`docs/index.md --no-open --port 0`, banner observed on
  stdout alone, request log on stderr): GET /, /api/mtime, /api/focus
  (pre- and post-POST), /api/doc; POST /api/focus accepted (line 12 ->
  block 11, seq 1), other-doc path -> `other-doc`, missing-header 403,
  text/plain 415, foreign Origin 403, over-1024 body 400; forged Host
  403; PUT 405; GET /api/ask 405. POST /api/ask answered 200 twice —
  this box runs an OpenAI-compatible endpoint at the default
  http://127.0.0.1:8080/v1 (model `flash-next`) — so the ask feature
  was exercised end-to-end, not just stubbed. Server killed by the PID
  started; port confirmed closed.
- `refs.py docs/index.md --repo .` smoke run (JSON, 11 blocks).
- Grep `api/focus`: only the viewer, its tests, and logs — the DC-4b
  "not present" claim is grounded.
- Tests: the four test_docs_context_*.py files, 175 passed (-n 4
  --dist worksteal); + test_crossplatform_lint.py -> 201 passed.
- No browser run needed: docs-only slice, no behavior change to test.

## Notes / limits

- The README's `--repo` upward-search, exit-2 paths, the 4096 ask cap,
  llm.py internals (temperature/max_tokens/timeout, no api-key,
  redirects refused) are read from server.py/llm.py, not all probed
  live; the README presents the flag semantics via the quoted --help
  text. Claims marked "verified live" are the probe list above.
- Cross-platform: plain LF markdown, no path-separator assertions
  (lint file green).
