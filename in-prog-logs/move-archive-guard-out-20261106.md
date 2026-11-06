# Move the Paseo archive guard out of refdes -- 2026-11-06

Task: Jared asked that anything Paseo-related live in its own project; this is
the archive-guard hook (`tools/archive-guard/`).

Done
- `git subtree split -P tools/archive-guard` in a scratch clone gave a 4-commit
  history (#160, #172, #173, #174). That became the new standalone repo
  `/home/jorb/work/paseo-archive-guard` (branch main, no remote yet), plus one
  commit adding a README and fixing the test runner's usage line.
- The standalone test runner passes there: 31 passed, 0 failed.
- Here: removed `tools/archive-guard/` and added a changelog fragment.

Checked
- Nothing in `.github`, `tests`, `docs`, `README.md`, `AGENTS.md`, `pyproject.toml`,
  `opencode.json` or `dispatch-handoff.md` references the hook.
- Historical logs in `in-prog-logs/` still mention the old path; left as record.

Not touched
- `.claude/hooks/block-unverified-archive.sh` and `.claude/settings.json` in the
  main checkout are untracked local copies that the live session loads. They keep
  working; pointing them at the new repo is a separate local change.

Status: finished once the PR merges.
