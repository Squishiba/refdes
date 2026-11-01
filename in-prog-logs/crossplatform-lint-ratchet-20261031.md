# crossplatform-lint ratchet (2026-10-31)

Task: add an AST-based cross-platform lint with a ratchet baseline, so the
two Windows-CI regressions of this month (#398 text-mode fixture writes,
#396 unnormalized `os.path.relpath` diagnostics) become mechanically
visible before CI. Branch off origin/main (fast-forwarded the stale
worktree b07d5e3 -> c1ef196 first).

## What landed

- `tests/test_crossplatform_lint.py`: rules R1/R2 as named `check_*`
  functions with docstrings; ratchet test compares per-file counts against
  `tests/crossplatform_lint_baseline.json`; fails on rises, new files, AND
  falls (with the regenerate command in the message). 12 tests: rule
  self-tests (each known case encoded as a source snippet), compare-unit
  tests, a message-format test, and a scan-speed test.
- `tests/crossplatform_lint_baseline_update.py`: regenerates the baseline
  (writes bytes; idempotent — verified two runs give identical md5).
- README "Tests" paragraph, `changelog.d/crossplatform-lint-ratchet.added.md`
  (repo convention puts dev-process changes in changelog.d: precedent
  `parallel-tests.changed.md`).

## Rule tuning (the interesting part)

Spec's narrow R1 (content argument = multi-line string constant/f-string/
join) hits 677 places on main and MISSES case (a): the 5d98def `_setup`
writes `write_text(text)` where `text` is a for-loop target. Tuned R1
(allowed by the spec): flag text-mode writes whose content is
statically-multi-line incl. names bound in-function (params, loop targets,
assignments, module constants), gated on the module reading raw bytes
(`read_bytes`/binary `open`) — the defect needs byte-exact assertions; a
module round-tripping through text mode cannot see the CRLF. Net: 394 hits
in 51 files (tests), 6 hits in 3 files (src, R2: scaffold.py x3
normalized in a *later* statement, citations.py x2 + lifecycle.py x1 in
f-strings). The two defect files themselves are baseline-zero, which makes
the red/green proof crisp.

## Evidence (all run, output in PR body)

- Red: `5d98def:tests/test_navis_mint_yaml.py` -> 1 R1 hit (line 46, the
  `_setup` loop); `c65bdfc:src/refdes/navis_archive.py` -> 1 R2 hit (line
  114).
- Green: current main ratchet passes; fixed heads clean:
  origin/feat/navis-yaml-mint mint_yaml 0 hits (baseline 0),
  origin/feat/navis-slice3 navis_archive.py 0 hits (baseline 0), its
  test_navis_archive.py 8 = baseline 8.
- c65bdfc test_navis_archive.py scores 7 R1 hits — *under* its main
  baseline of 8 (the test-side write_text debt is itself main's recorded
  debt), so the deterministic red proof for #396 is the src file. Stated
  in PR.
- Ratchet red-demo: perturbed baseline 12->11 for test_boards.py, ratchet
  test failed listing file:line + fix + command; restored from
  .scratch backup (untracked file, so no git checkout).

## Decisions / limits (also in PR)

- Scan-speed test asserts <10 s (not the 5 s budget) so a loaded CI box
  can't turn CPU contention into a red suite; measured ~2.9 s locally.
- R1 does not follow content through call expressions
  (`write_text(json.dumps(x))` unflagged); byte-read gate is module-wide;
  R2 accepts any enclosing `as_posix()`. All recorded in the module
  docstring.
- Full suite, ruff (E9,F + default on my two files): see below.
