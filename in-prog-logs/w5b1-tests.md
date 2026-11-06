# W5b.1-tests: red contract tests for `serve.edit.continue_thread`

Task: write ONLY `tests/test_serve_continue.py` + this log, for slice
W5b.1-tests of `docs/design/thread-workbench-w5b-plan.md` §4. No `src/`
edits. No PR requested. Base: `b9eba32d`, branch `feat/w5b1-continue-op`.

## Chosen signature (pinned in the module docstring)

`edit.continue_thread(project_root, request, config_path=None, *,
read_only=False) -> Applied | Conflict | Refused | Invalid` with
`ContinueRequest(who, ref, ticks: tuple[tuple[str, str], ...],
expected_revision)`. Entry-point shape mirrors `apply_edit`/`create_item`.
`ticks` is pairs (a mapping cannot express the refused second-tick-for-the-
same-id); `read_only` is keyword-only because W5b.1 has no HTTP face to
carry the `--no-write` flag.

## Red evidence

`PYTHONPATH=<worktree>/src ... pytest -q tests/test_serve_continue.py` ->
22 failed in 0.71 s, every one `AttributeError: module 'refdes.serve.edit'
has no attribute 'ContinueRequest'` (the helper builds the request first,
so the missing operation is the single shared red cause). No full suite
run: test-only slice, task said no full suite. `ruff check` clean on the
new file; `tests/test_crossplatform_lint.py` passes (12 passed).

## What is pinned

Happy path (one appended entry, whole updated list, tip's declared fields
copied verbatim + empty body, tip bytes unchanged, pure-suffix YAML,
markdown thread keeps its bytes); the three folded postures refused
(ambiguous/undeclared/cleared); unknown id, off-vocabulary state,
duplicate tick, sealed tip, non-open->non-open refused; un-tick lands
(Q6(b)); id from the destination's own prefix series; refusals burn no id
(R5); server-generated `follows` composite; stale revision -> Conflict
carrying the current list, no write; two simultaneous continuations ->
one Applied one Conflict; `read_only` refuses naming `--no-write`;
gate-blocking row -> Invalid, no write; older entry ref continues the tip
(Q4). 22 tests.

## Ambiguities I resolved (flag for implementer)

- Refusal-message needles ("ambiguous", "undeclared", "cleared", "sealed",
  "--no-write", the off-vocabulary state, the unknown task id) are pinned
  text, not just status. The plan names the postures/verbs; the needles
  follow that vocabulary, matching the siblings' refusal-message style.
- Q3(a) + the concurrency test pin that the write lock serialises, so
  exactly one of two simultaneous requests lands (no "both refused").
- The gate test uses a pre-broken row copied by the continuation,
  mirroring the siblings' delta-gate tests (newly-introduced -> Invalid).
- Probe note (`.scratch/w5b1/`): a writable `seal_write=True` build seals
  clean append-only log entries for a `sealing: build` type — the sealed
  test relies on that, not on a hand-written seal file.

Status: DONE — 22 red tests written and verified red, log written.
