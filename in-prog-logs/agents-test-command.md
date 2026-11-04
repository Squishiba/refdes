# docs: put the standard test command in AGENTS.md

Task (docs-only, from Jared): add the project's standard test command to
AGENTS.md so agents stop guessing at it.

## What changed

One new section, `## Running the test suite`, between "Before writing any claim
about CLI behavior" and "Before writing a new docs page": 14 added lines vs
origin/main, 11 of them content. Nothing else in AGENTS.md, and no other docs,
were touched. It gives the command `python -m pytest -q -n 4 --dist worksteal`
from the repo root with the venv installed as `".[dev,xlsx]"`, the
absolute-`PYTHONPATH` rule and its real condition, `-n 4` over `-n auto` on a
shared box with the sourced load fact, `--dist worksteal` as what CI runs and
what Jared's `-n 8` run favoured (~155 s vs ~105 s), and
full-suite-once-before-pushing / iterate-on-touched-files.

## Review round 2 (reviewer 3f721599)

Four findings, all applied: the relative-`PYTHONPATH` sentence now names the
real condition (probe: from the repo root `PYTHONPATH=src` imports the tree;
from `docs/` and `tests/` it imports the installed copy under
`/home/jorb/work/refdes/src`); install is `".[dev,xlsx]"` per
`.github/workflows/tests.yml:48` and `:87`; the parallel-load claim now cites
`test_rules_scan_the_tree_fast`'s 11.1 s of wall for ~3.4 s of CPU under 10-way
xdist (run 15); the worksteal numbers are attributed to Jared's `-n 8` run with
no `-n 4` speedup claimed. PR body reworded to say only the collection-only
check was run.

## Verification (docs claims only from output I ran)

- README.md:409 flags match the section word for word.
- `--collect-only -q -n 4 --dist worksteal` -> 5667 tests collected in 8.70s.
- tests.yml:48/:87 install `".[dev,xlsx]"`; xlsx tests gate on
  `pytest.importorskip("openpyxl")` (tests/test_sources_xlsx.py:18) and those
  three files collect 30 tests.
- README.md:26 documents `pip install -e .` with no extra, so README-only
  readers get no pytest — flagged for a README follow-up, not changed here.

## Status

Finished through review round 2. No changelog fragment (agent instructions are
not user-visible), per the task.
