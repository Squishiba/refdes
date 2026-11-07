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

## W5b.1 implementation pass

Implemented `serve.edit.continue_thread` and `ContinueRequest` in
`src/refdes/serve/edit.py`; no tests, HTTP/UI/CLI endpoints, templates, JS,
or changelog fragment were added. The operation appends one entry to the tip's
own file, copies the tip's scalar declared fields and complete task list,
applies ticks, mints id/key, writes server-spelled `follows`, and uses the
same destination/revision/journal/reserve path as `create_item`.

Green evidence:
- `tests/test_serve_continue.py`: 21 passed, 1 failed.
- Touched-file lint: `ruff check src/refdes/serve/edit.py --select I001,F,E4,E7,E9`
  passes. Existing `E501` findings remain on untouched lines.
- Neighboring tests (`tests/test_serve_continue.py`,
  `tests/test_serve_edit*.py`, `tests/test_serve_create.py`,
  `tests/test_serve_api.py`, `tests/test_crossplatform_lint.py`):
  535 passed, 1 failed (same setup flaw below).
- Full suite: 5959 passed, 2 skipped, 1 failed.
- Added `src/` lines: 346, under the 350 PR size gate.

Stopping point: `test_a_continuation_the_delta_gate_would_block_is_invalid_and_writes_nothing`
fails before calling the operation because it asserts the task-row state
diagnostic is present from `_load` (`parse.load_items` only). That diagnostic
is emitted by `build.validate_items`, not parse. Proposed test change: build
the snapshot before that assertion, e.g. `build_mod.build(project, seal_write=False,
reseal=False)` after `_load(tmp_path)`, as `_mint_and_seal` does. Probe
`.scratch/w5b1-impl/probe_gate.py` shows the operation itself returns
`Invalid`, names `closed`, and writes nothing.

Status: Implementation DONE for W5b.1; test suite blocked by the one red-test
premise above.

## Review follow-ups (2026-11-07, PR #448)

Merged `origin/main` into the branch (no conflicts; the worktree base had
diverged 15 commits, and ff-only is impossible for a branch with its own
commits — orchestrator authorised the plain merge over a force-push rebase).
Test fixes, all authorised: the delta-gate precondition above now builds the
snapshot (`build_mod.build(project, seal_write=False, reseal=False)`, as
`_build_before` does) before asserting the `tasks`/`closed` diagnostic; the
Q2 test asserts `f"key: {result.handle}"` (`Applied.handle` is the minted key,
`edit.py`'s continuation `Applied(..., handle=key)`) instead of the
`tautological hasattr` spelling; the unused module-level `TIP_ROWS` is
deleted. A probe of `continue_thread` found non-ASCII task text written
escaped (`\xNN`/`\uNNNN`), so `_continuation_lines`'s flow dump gained
`allow_unicode=True`; the red test
`test_non_ascii_task_text_is_written_as_is_not_escaped` fails before that
src change (asserts the literal text, no escape sequences, round-trip fold)
and passes after.

Evidence: `tests/test_serve_continue.py` 23 passed (21+1+1);
`tests/test_crossplatform_lint.py` passes;
`ruff check` (I,F,E,W) on the two touched files shows only the pre-existing
E501 lines (baseline-identical via `git show HEAD:...`).

Status: W5b.1 DONE — implementation and green test file; full suite runs
once pre-push.

## Round 2 — review items (2026-11-07, mimo chunk 1): DONE at 304c7edc, STOPPED by pr-size

M1 (scalar-only is intended: the fold carries list/dict fields and non-
follows links; re-declaring would duplicate edges/checks): fixed the false
`_continuation_lines` docstring and the comment above `continue_thread`,
pinned the behaviour with a test (local schema: `tags` list field + `relates`
link at the tip; new entry carries scalars/tasks/follows only;
`chains.resolve_current` still answers the tip's tags) and added the dated
note to the plan's Q2. Doc fixes can't be red-first; the mutation check
stands in (relaxing both skip-guards so the code copies the list field makes
the test fail at the `tags:` assertion; reverted). L1: date fallback now
rides `emit()` (red-first shown: bare `date: 2026-11-07` under YYYY-MM-DD
reloads as a YAML date). L2: plan_new_id refusal passes "" as ref. L3:
`Applied.plan: PatchPlan | _ContinuationPlan`. Local evidence: 25 passed in
the file, full suite 6001 passed / 2 skipped, ruff baseline-identical.

STOPPED by pr-size (round 1 sits at 348/350 src added lines; the approved
round-2 edits add +17): reverted (plain push) so the PR stayed green on the
approved tree; the split was reported to the orchestrator.

## Option (b): compression (2026-11-07)

Cherry-picked round 2 (b177a121) and compressed the W5b.1 block's round-1
comments/docstrings (header block -> deleted, the two one-line docstrings ->
deleted, M1 decision text -> 4-line docstring keeping its full meaning) so
src additions land at exactly 350. Proof: `.scratch/ast_proof.py` (strip
docstrings, `ast.dump` head vs 304c7edc) prints IDENTICAL -- only
comments/docstrings changed; a walrus micro-optimization found by that proof
was reverted. `tools/pr_size.py` (CI-style): 350/350, verdict PASS. File
25 passed, full suite 6001 passed 2 skipped, ruff baseline-identical.

Status: round 2 + compression pushed (b99b585d); awaiting CI.
