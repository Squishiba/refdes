# Candidate-parts Phase 1 — data/docs only

## Task
Phase 1 of docs/design/candidate-parts.md (merged at 7b37229): mechanical data
+ docs changes only. The ENGINE worker (another session) handles schema.py /
build.py / lifecycle.py in parallel.

## Changes made
1. `src/refdes/standards/hardware/v3/base.yaml`, `component`:
   - `status` choices `[candidate, selected, obsolete]` →
     `[candidate, selected, rejected, obsolete]` (design §5.1, doc text updated
     per §5.1 too).
   - Added `check_severity: { candidate: info, selected: error, rejected: info,
     obsolete: info }` per design §4.1/§5.4 (was implicit `error` via engine
     default — `component` had no explicit `check_severity` before).
2. `docs/standard-library.md`:
   - New `hardware@3` changelog bullet (item 5) per design §8.
   - The "What's in it" lifecycle table row for `component` updated to
     `candidate → selected / rejected / obsolete` (kept consistent with the
     same feature; not in §8's list explicitly).
3. `changelog.d/hardware-v3-rejected-status.added.md` added.

## Not touched
No .py files (engine worker owns schema.py/build.py/lifecycle.py).
No new tests (engine worker owns tests).

## Verification
- Full `python -m pytest -q`: **126 failed, 1788 passed, 9 errors** — every
  single failure/error is the SAME root cause:
  `refdes.model.SchemaError: types.component.check_severity must be one of
  ['error', 'warning', 'info'], got {'candidate': 'info', ...}` raised by
  `src/refdes/schema.py:596`. The current tree's `schema.py` does NOT yet
  accept the mapping form — that validation/resolution is the engine worker's
  parallel job (schema.py/build.py). No other failure reason exists behind the
  visible tracebacks. Repo's own project pins hardware@3, hence repo-loading
  tests fail the same way.
- `ruff check --select E9,F`: nothing to run — no `.py` file was touched
  (touched files are base.yaml, a .md doc, a .md changelog fragment). The
  earlier run pointed ruff at non-Python files and is meaningless (ruff
  parses them as Python and reports invalid-syntax).
- No existing test asserts the bundled hardware@3 `component` enum or its
  scalar severity; the `[candidate, selected, obsolete]` strings in
  `tests/test_parse.py` and `tests/test_status_links.py` are local fixture
  schemas, not the standard — no test edits needed.
- v1/v2 standards untouched (byte-identical-when-unused holds trivially).

## Status
BLOCKED on sequencing: full suite can only pass once the engine worker's
schema.py/build.py changes are in the tree. Awaiting orchestrator decision on
whether to open this PR now (stacked on the engine PR) or wait for the engine
to land on main first, merge into this branch, rerun, then open.