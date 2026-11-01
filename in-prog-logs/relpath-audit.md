# relpath audit (chore/relpath-audit)

Audited the six baselined R2 sites (`os.path.relpath` results not
normalised to `/` in the same expression, tests/test_crossplatform_lint.py
rule R2) for real Windows bugs. Verdict: three REAL (diagnostic text),
three LOCAL (scaffold probes, already normalised one statement later);
none feeds a hash, lockfile, or persisted format, so no hash_format /
lockfile-compatibility blockers were found.

## Per-site findings

- citations.py:2040 (cache-missing) -- REAL. `os.path.relpath(blob,
  project.root)` interpolated into `status.detail`, which `severity()`
  publishes as a build diagnostic (user-visible). On Windows printed
  `.refdes\copies\<sha>.pdf`. Fix: `.replace("\\", "/")`. Red-first
  test: `test_cache_missing_diagnostic_names_the_copy_with_forward_separators`
  (tests/test_citations.py) -- patches `os.path.relpath` to
  `ntpath.relpath` (pure string arithmetic, so it runs the Windows
  separator computation on any OS; on Windows the patch is a no-op and
  the same assertion proves native behaviour). Confirmed red (message
  contained `.refdes\copies\`), green after.
- citations.py:2107 (case-mismatch warning) -- REAL. relpath of the
  on-disk spelling interpolated into `project.warn` text. Same fix.
  Test: `test_case_mismatch_warning_names_the_disk_path_with_forward_separators`;
  patches `citations_mod.case_mismatch` to answer the hit directly (the
  sibling real-path test skips on case-sensitive file systems, this one
  runs everywhere). Confirmed red (`(docs\SCH.pdf)`), green after.
- lifecycle.py:1026 (stamp conflict remedy) -- REAL. relpath of
  `baseline_path` interpolated into `raise_detail` ->
  `StampOutcome.conflict_detail`, printed by `cli.py:774` to stderr.
  Same fix. Test:
  `test_conflict_detail_names_the_baseline_with_forward_separators`
  (tests/test_lifecycle.py). Confirmed red
  (`.refdes\baselines\rev-a.yaml`), green after.
- scaffold.py:331/415/468 (`_git_covers`,
  `vscode_local_rule_ignores`, `vscode_settings_state`) -- LOCAL.
  Each normalised `rel` with `.replace(os.sep, "/")` in the statement
  right before the value reaches the git check-ignore probe, and the
  pardir guard compared against `os.pardir + os.sep`, correct on both
  platforms; the probe string fed to git always carried `/`. No real
  bug -- behaviour-neutral change: moved `.replace(os.sep, "/")` into
  the relpath expression and spelled the guard `os.pardir + "/"` (the
  normalised string is what the guard now sees; `/` is
  Windows-neutral). The 105 tests in test_scaffold.py pass unchanged
  (no red-first test possible for a behaviour-preserving change; the
  probe tests are the guard).

## Notes

- The `.replace("\\", "/")` form is the build.py/render.py/revise.py
  convention for this exact class (project-relative diagnostic text);
  keys.py/history.py use `.replace(os.sep, "/")` in the same
  messages. On Windows the two are identical; I chose the
  build/render/revise form for the three message sites and left
  scaffold's `os.sep` form alone.
- py311: a backslash literal inside an f-string expression is a
  SyntaxError before 3.12 (PEP 701) -- caught by ruff, my venv is
  3.13. All three REAL sites assign the normalised path before the
  f-string (the build.py pattern).
- Baseline: regenerated with
  tests/crossplatform_lint_baseline_update.py after each commit; R2
  6 hits / 3 files -> 0 hits (rule key gone). The lint docstring's
  "the scaffold.py pattern is a baseline hit" sentence updated to say
  all six were normalised into the expression.
- Not verifiable without Windows CI: the native-ntpath end-to-end
  runs of the three new tests (the monkeypatch is a no-op there, so
  they assert real `os.path.relpath` output -- the windows job proves
  the actual separator behaviour).
- Full-suite triage: two `test_no_write.py` argparse-help parsing
  tests (`...lists_calc_rewrite_among_the_reporting_commands`,
  `...lists_every_command_the_docs_table_lists_as_reporting`) failed
  (IndexError) in both full-suite runs here. Reproduced identically
  at the base commit d9719a9 under the same full-suite command in
  this environment, and they fail at `COLUMNS<=75` serially on base --
  pre-existing terminal-width sensitivity of the phrase split, not
  this diff. Both pass in isolation on this branch (serial and -n 4).

Status: complete. Commits: citations fix + test, lifecycle fix + test,
scaffold normalisation (behaviour-neutral) + baseline, py311
compat follow-up for the citation sites, this log + changelog
fragment.
