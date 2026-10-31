# Move AgentCoder out of refdes (2026-10-31)

Jared asked for AgentCoder to live in its own project: it is not part of refdes.

What moved (source refdes main b07d5e3), to `/home/jorb/work/agentcoder` (new git repo, not yet pushed anywhere):
- `tools/agentcoder/` with its history (`git subtree split` in a scratch clone, then `subtree add` -- 5 commits).
- `tests/test_agentcoder_{tool,queue,workspaces,land_push}.py`, `tests/drv-push.cases.json`,
  `tests/fixtures/agentcoder_queue/`, a copy of `tests/fixtures/agentcoder347/`.
- `docs/agentcoder-queue.md`, `in-prog-logs/agentcoder-*.md`, `fix-agentcoder-reuse-workspaces.md`,
  `drv-push-{coder,designer}.md`, and the five `changelog.d/agentcoder-*.md` fragments.
Layout kept identical (`tools/agentcoder/...`) so the tests moved byte-for-byte.

Left in refdes on purpose: `tests/fixtures/agentcoder347` and `tests/test_inline_calc_agentcoder_trial.py`
(a refdes inline-calc test that uses that fixture), plus historical in-prog-logs that merely mention AgentCoder.
Edited: `docs/index.md` (nav row removed).

Verified by running:
- new repo: `pytest -n 8 tests` -> 203 passed (49 s); `grep` finds no `import refdes`, `-m refdes` or `refdes check/build` in the moved code or tests.
- this branch: full suite `-n 8` (without `tests/test_serve_edit_links.py`) 5348 passed, 2 skipped; that file alone 12 passed
  (it is excluded from parallel runs only because of its random parametrize id, a separate fix).
  Count check: 5563 before - 203 moved = 5360 = 5348 + 12.
- `tests/test_docs_anchors.py`, `tests/test_inline_calc_agentcoder_trial.py`, `tests/test_serve_static.py`: 83 passed.

Not done / for Jared: the new repo has no remote and no CI yet; the idle "AgentCoder queue mode spec" agent's
worktree still points at refdes; the orchestrator's own `.scratch/jobs/*.spec.json` driver specs refer to the old path.
