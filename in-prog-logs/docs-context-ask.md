# DC-3-tests: contract tests for docs-context ask (red-first)

Task: write the red-first contract tests for the docs-context "ask Qwen"
reading aid (slice DC-3-tests) on branch `feat/docs-context-ask`, touching
only `tests/test_docs_context_ask.py` and this log. No `tools/` changes —
the implementer adds `llm.py`, `POST /api/ask`, and the three buttons.

## What the tests pin

- `docs_context/llm.py`: `ask_model` (urllib POST to `{base}/chat/completions`,
  temperature 0, stream false, model discovery via GET `/models`, loopback-only
  base_url enforced *before* any socket, `LlmError` kinds unreachable/timeout/
  bad_response), `build_messages` (system+user only, server-known facts, the
  three questions), and a public `discover_model` helper (the 200 response must
  name the model, so the server resolves it).
- `POST /api/ask`: `{block, ref, question}` resolved against the server's own
  current analysis; client `prompt`/`text`/`messages` ignored. 200
  `{answer, model, question}`; 400/403/409/415/502/504 per spec; Host guard,
  `X-Docs-Context: 1`, own-Origin check, nosniff/no-store, no CORS, GET -> 405,
  nothing written to the repo.
- CLI: `--llm-url` (default `http://127.0.0.1:8080/v1`) and `--llm-model`
  documented in `--help`, wired to the route, non-loopback URL exits 2 with a
  stderr message naming the loopback rule.
- `app.js`: three buttons, `/api/ask` + header, disabled in flight, answers
  labelled as a reading aid, rendered via textContent only.

## Status

- Red evidence (real tools, nothing implemented): `46 failed, 2 passed`.
  The 2 green are intentional unchanged-contract guards (app.js textContent
  scan; index.html/style.css contract).
- Satisfiability proven: a throwaway prototype of `llm.py` + server + app.js
  under `.scratch/dc3/proto` passes all 48 (`run_proto.py` driver injects it).
- `ruff check` clean on the touched file; `test_crossplatform_lint.py` green.

## Difficulties

- The fake LLM initially closed blocked requests without replying (busy test
  saw RemoteDisconnected) and `shutdown()` raced mid-response; the handler now
  replies after the gate and `fake_llm` joins in-flight handler threads before
  `server_close()`.
- The timeout stub must expose the whole public `llm` surface the server calls
  (`build_messages`, `discover_model`, `LlmError`), not just `ask_model`.
- Loopback guard is host-only (no scheme rule): `https://127.0.0.1:...` stays
  valid; the must-raise list uses real non-loopback hosts.
- CLI tests run the real `server.py`, so they stay red until the implementer
  lands the flags; the driver patches the server-test module's `TOOL` to the
  prototype for the green proof.

Finished: tests committed on `feat/docs-context-ask`, no PR (per task).
