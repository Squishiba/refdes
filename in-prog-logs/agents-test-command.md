# docs: put the standard test command in AGENTS.md

Task (docs-only, from Jared): add the project's standard test command to
AGENTS.md so agents stop guessing at it.

## What changed

One new section, `## Running the test suite`, inserted between "Before writing
any claim about CLI behavior" and "Before writing a new docs page". Nothing
else in AGENTS.md, and no other docs, were touched. 13 added lines, 0 removed
(`git diff --stat AGENTS.md`).

The section states: the exact command
`python -m pytest -q -n 4 --dist worksteal` from the repo root with the project
venv; the absolute-`PYTHONPATH` requirement; why `-n 4` and not `-n auto` on a
shared machine; why `--dist worksteal` (with Jared's measured numbers, credited
to him, not re-measured); that CI runs `-n auto --dist worksteal`; and
full-suite-once-before-pushing / iterate-on-touched-files.

## Verification (docs claims only from output I ran)

- README.md:409 read: `# Parallel: ./.venv/bin/python -m pytest -q -n 4 --dist
  worksteal` — flags match the section word for word, so no divergence to
  report on the pytest flags.
- Command line accepted, collection only (per the task's override, no full
  suite): `PYTHONPATH=<worktree>/src ... python -m pytest --collect-only -q -n 4
  --dist worksteal` -> "5667 tests collected in 8.70s".
- `pip install -e ".[dev]"` checked against `pyproject.toml:59` — the `dev`
  extra is what carries `pytest` and `pytest-xdist`, so it is the right install
  for this command. Note: README.md:26 documents `pip install -e .` without the
  extra; following the README alone leaves you with no pytest. Flagged here for
  a README follow-up, not changed (task says touch nothing else).

## Status

Finished. Changelog fragment not added (agent instructions are not
user-visible), per the task.
