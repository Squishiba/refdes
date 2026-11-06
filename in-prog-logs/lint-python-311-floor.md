# LINT-311: catch Python 3.12/3.13-only APIs before CI does

Status: finished. Branch chore/lint-311-floor, tests/test_crossplatform_lint.py
only (no product changes — there were no pre-existing violations to fix).

Started from main at b9eba32d (after `git fetch origin main && git merge --ff-only
origin/main`, already up to date).

## What landed (tests/test_crossplatform_lint.py only)

Extended the existing rule/ratchet mechanism — no new mechanism:

- R3 `R3-read-text-newline-kwarg`: flags `.read_text(..., newline=...)`
  (keyword is 3.13; `write_text(newline=)`/`open(newline=)` stay clean).
  Fix text: "use Path.open(newline='').read() or read_bytes().decode()".
- R4 `R4-post-311-stdlib-api`: qualified attribute/import use of
  itertools.batched, math.sumprod, typing.override, warnings.deprecated,
  copy.replace, os.path.isjunction, Path.is_junction, Path.full_match,
  Path.walk (only when the receiver is plausibly a Path: name assigned
  from a Path expr, `/` join, Path() call, path-method chain, subscript —
  so every `os.walk`/`ast.walk` call site in the tree stays clean), and
  `shutil.rmtree(onexc=)` (3.11 spells it `onerror=`; bare `rmtree` call
  flagged only when imported from shutil). tomllib stays clean.
- R5 `R5-syntax-newer-than-311`: `ast.parse(source, feature_version=(3,11))`
  over every scanned file; on 3.12+ interpreters it catches PEP 695
  (`type X = ...`, `def f[T]()`, `class C[T]:` — verified on 3.13). It does
  NOT catch PEP 701 f-string changes (feature_version does not re-tokenize
  f-strings; verified) — the 3.11 CI job's own parse is what rejects those,
  and scan_repo now turns a plain-parse SyntaxError into an R5 finding
  instead of crashing the scan. Limits recorded in docstrings.
- Scopes: R3/R4/R5 run over src/refdes, tests and tools (tools/ newly
  scanned). `RULE_SCOPES` values became scope tuples; `_rule_for` ->
  `rules_for` (a file can carry several rules); scan_repo parses each
  file once and runs all applicable rules.

## Evidence

- Red-first: HEAD implementation + the new tests in a throwaway copy
  (.scratch/lint311-red) -> the 9 rule-specific new tests FAIL (NameError
  on R3/R4/R5/rules_for); the two tree-wide tests fail on that copy's
  missing src/tools dirs, an artifact of the copy, not the rules. In the
  worktree after the change: 26 passed.
- Proof of bite: .scratch/lint311-bite (copy of src/tests/tools with
  `read_text(encoding="utf-8", newline="")` appended to
  tests/test_serve_navis_mint.py) -> ratchet test fails with
  "R3-read-text-newline-kwarg tests/test_serve_navis_mint.py:612:
  Path.read_text(newline=...) is Python 3.13+ (floor is 3.11) -- fix: use
  Path.open(newline='').read() or read_bytes().decode() ...".
- Pre-existing violations: zero for all three rules. R3/R4: grep + the rules
  themselves (test_new_rules_find_no_hits_on_the_real_tree). R5: all 296
  scanned files parse under feature_version=(3,11) (command run on 3.13.5).
- Timing: test_rules_scan_the_tree_fast passes. Measured scan_repo CPU:
  5.03s/292 scans before (2 rules), 6.04s/296 files after (5 rules) —
  10% of the 60s ceiling. Docstring updated. These CPU figures are
  machine dependent: ~6s on this box, ~9s on a loaded one.
- Full suite: 5952 passed, 2 skipped, -n 4 --dist worksteal (3:36).
- ruff (E9,F and I) clean on the touched file.

## Not verifiable locally

No 3.11 interpreter on this box: the skipif'd PEP-695 snippet tests and the
whole 3.11 CI job (which is the real floor enforcement for f-strings) are
only exercised on CI.
