# Refdes local-agent handoff

Written by Claude (Cowork) on 2026-08-28, for whichever agent picks this up next — Dispatch on the desktop, or Jared at the keyboard tomorrow. This isn't a raw transcript; it's the distilled state of the work, which will be far more useful to hand to a fresh agent than a dump of tool calls.

## The goal

Jared is offloading some of his Claude usage onto a local model reached over
the network, not run on the Windows desktop itself. The target project is
**refdes**, a Python hardware-design documentation tool, at
`C:\Users\Jared\Refdes` on this machine. little-coder (built on the `pi`
CLI) is the harness that will drive the local model against the repo;
Claude (this conversation, or whichever Claude is coordinating) plays
lead/reviewer.

(A previous draft of this section named a specific model, quant, GPU, and
throughput estimate. Left out here rather than re-asserted: none of it was
verifiable from this repo, and a wrong hardware/model claim is worse than
none. Whoever hands off the next task should fill in what's actually true
at the time.)

## What's already done

The 460KB, 11,696-line `tests/test_refdes.py` monolith has been split into `tests/conftest.py` (shared fixtures) plus 30 focused test modules (largest is `test_revise.py` at ~38KB), verified equivalent both by test-outcome diff and by AST-level function/constant diff against the original. The original file has been `git rm`'d by Jared already.

`pyproject.toml` now has a `[tool.ruff]` section: line-length 100, target py311, and `extend-select = ["I"]` (import sorting only). `ruff format` was deliberately **not** enabled — it would reformat ~3900 lines across 55 files, too large a blast radius for now. A handful of small source fixes went in to make the repo ruff-clean (an unused import in `calc.py`, an unused import in `scaffold.py`, three `l` → descriptive-name renames for ambiguous loop variables in `links.py`, `parse.py`, `revise.py`).

Three previously-deferred test assertions (discarded CLI exit codes) have been resolved: `test_build.py` and `test_workspaces.py` got real assertions added with justification; `test_lifecycle.py` was correctly left as a bare call (the value being discarded there isn't an exit code, and the test already verifies more strongly by reloading from disk).

The pre-existing `test_log_amendments_are_links_not_edits` failure noted in
an earlier draft of this file is **resolved** — it passes now (verified
2026-08-29, `main` @ `cd6bf4a`: `pytest -q` → 650 passed, 0 failed). Don't
treat any reference to it elsewhere as current.

## Next task — ready to hand to little-coder

This is written and ready to run as-is. Recommended to start in plan mode (Alt+P) first, to see whether the model flags the brace-escaping hazard unprompted before it starts editing.

```
In tests/test_calc.py, tests/test_revise_migrations.py and tests/test_seal.py
only, modernise the code flagged by ruff's UP rules.

Start by running, scoped to exactly these three files -- NOT `src tests`,
which would touch dozens of files this task has no business changing:

  ruff check tests/test_calc.py tests/test_revise_migrations.py tests/test_seal.py --select UP --fix

Then fix by hand the remaining UP031 findings (percent-format strings).

CAUTION: several of those strings contain literal { and } characters as part
of YAML content. If you convert one to an f-string, every literal brace must
be doubled ({{ and }}) or the file written by the test changes silently.
Converting to .format() has the same hazard. Leaving a string as percent-format
and adding a targeted noqa is an acceptable outcome if conversion is unsafe.

Do not modify any other file.
Do not change what any string evaluates to -- only how it is constructed.
Do not add dependencies.

Done when:
  ruff check tests/test_calc.py tests/test_revise_migrations.py \
             tests/test_seal.py --select UP        reports no findings
  pytest -q                                         shows 650 passed, 0 failed

Do NOT run a repo-wide `ruff check .` (or `ruff check src tests`) as a gate.
It is not clean today -- ~99 pre-existing findings, unrelated to this task,
because the installed ruff's default rule set is broader than
`pyproject.toml`'s `[tool.ruff]` comment assumes. That is expected and not
a signal: don't chase it, and don't let a repo-wide ruff run talk you into
touching a file outside the three named above.

If the gate fails twice, stop and report which conversion broke and why.
Do not modify a test's expected values to make it pass.
```

## Context on why this file exists

This session's shell bridge to this Windows machine (the isolated command sandbox the desktop app spins up) was unavailable when Jared asked about running this tonight from bed, so this handoff was written and dropped into the Refdes folder instead, for Jared or a Dispatch-driven session to pick up once at the machine. Nothing in the task above requires that bridge.
