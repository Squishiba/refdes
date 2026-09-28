# `refdes stub-tests` reported "nothing missing a test" while its own load rewrote files

Follow-up to F5 (`in-prog-logs/id-silent-writes-f5.md`, landed as #95), which
fixed exactly this for `refdes id` and named this command as the one remaining
gap: same `_load`, and the other command `--no-write` forces onto `--dry-run`.

## Status: finished — full suite green, PR against `main`

## Confirmed the shape first

- `cmd_stub_tests` is at `src/refdes/cli.py:1183` on the branch point
  (`273161f fix(cli): refdes id names the writes its own load made (F5)`), as
  the F5 log's "Not done, deliberately" section said.
- `_load_write_notice` is `cli.py:95`; `cmd_id` calls it at `cli.py:492`,
  straight after `_load` and before its own verdict/errors.
- `cmd_stub_tests` calls `_load(args, require_ids=False)` the same way, so
  `project.load_writes` is already filled in for it by `loader.load_tree` —
  nothing in `loader.py`/`model.py` needed touching.

## Reproduced first (before touching anything)

Scratch project `.scratch/stub-proj/` — three items that already carry display
ids, no `key:` lines anywhere, one bare `satisfies: [REQ-002]`, two coverable
requirements with no verifying test. Driven through `.scratch/run_refdes.py`
(the 7-line shim that puts `src/` on `sys.path`, since the `refdes` on PATH is
not this worktree).

With the notice call removed again (to prove the test is a real regression
test), `pytest tests/test_stub_tests.py -k cli_stub_tests` shows the pre-patch
output verbatim:

```
>       assert "minted 3 key(s) and rewrote 1 reference(s) while loading" in out
E       assert ... in "wrote 2 stub(s) to items/power/stub-tests.md: REQ-001, REQ-002\n
E         wrote 2 stub test(s) across 1 file(s)\nRun 'refdes id' to allocate ids for the new items.\n"
```

i.e. two `key:` lines minted and one link target rewritten, reported as a clean
run. Same defect as F5, messaging only.

## The change

`src/refdes/cli.py`, `cmd_stub_tests` only — the same three lines the F5 log
predicted, placed identically (right after `_load`, before anything the command
prints), reusing the existing helper:

```python
notice = _load_write_notice(project)
if notice:
    print(notice)
```

`cmd_id`, `_load_write_notice`, `LoadWrites` and `loader.py` untouched. No
other change to `stub-tests`' own output.

## Tests

Added to `tests/test_stub_tests.py` (the file that owns this command's CLI
tests), mirroring the `cmd_id` cases in `tests/test_load_time_writes.py` §"the
load's own writes get reported (F5)". The existing `stub_project` fixture is
already the F5 shape, so no new fixture:

- `test_cli_stub_tests_reports_the_keys_and_link_target_its_load_wrote` — the
  repro: `(minted 3 key(s) and rewrote 1 reference(s) while loading)` above
  `wrote 2 stub test(s)`.
- `test_cli_stub_tests_quiet_case_prints_only_its_own_verdict` — steady state.
  Three runs, not two: run 1 mints keys for the three fixture items, run 2 for
  the two stub items run 1 just wrote (pending items get keys too, keys are
  independent of ids), so run 3 is the first genuinely quiet one. Its stdout is
  asserted byte-exact: `"no coverable item is missing a verifying test\n"`.
- `test_cli_stub_tests_no_write_says_nothing_about_writes_it_did_not_make` and
  `..._dry_run_...` — no `while loading` line, the command's own `would write`
  verdict still there, and every `items/**/*.md` byte-identical afterwards.

Existing `stub-tests` tests that could have caught the new line
(`test_cli_stub_tests_end_to_end`, `test_cli_stub_tests_reports_nothing_to_do`,
and `test_stub_tests_under_no_write_reports_stubs_without_writing` /
`test_stub_tests_dry_run_leaves_the_whole_tree_byte_identical` in
`tests/test_no_write.py`) all assert with `in`, and the two read-only ones run
on a keyless project where `load_writes` stays empty — none needed changing.

## Verification

```
$ pytest tests/ -q            # branch point 273161f
2727 passed, 2 skipped in 189.82s (0:03:09)

$ pytest tests/ -q            # after rebasing onto origin/main 7220d5d (#96)
2736 passed, 2 skipped in 192.01s (0:03:12)

$ ruff check src/refdes/cli.py --select I,F
All checks passed!
```

#96 (`parse.py`, docs, one new test file) touches none of the files this change
does, so the rebase was clean and the re-run is the one that matters.

(`tests/test_stub_tests.py` run through the same `--select I,F` is clean too.
The repo's ~99 unrelated `ruff check .` findings were left alone, per
AGENTS.md.)

### Manual, `.scratch/stub-proj/` (fresh keyless project)

Run 1 — three keys to mint and one bare `satisfies:` to expand, plus real stub work:

```
$ python .scratch/run_refdes.py -c .scratch/stub-proj/refdes-project.yaml stub-tests
(minted 3 key(s) and rewrote 1 reference(s) while loading)
wrote 2 stub(s) to items/power/stub-tests.md: REQ-001, REQ-002
wrote 2 stub test(s) across 1 file(s)
Run 'refdes id' to allocate ids for the new items.
[exit=0]
```

Run 2 — the two stub items run 1 wrote are still keyless, so this run mints
those and says so:

```
$ python .scratch/run_refdes.py -c .scratch/stub-proj/refdes-project.yaml stub-tests
(minted 2 key(s) while loading)
no coverable item is missing a verifying test
[exit=0]
```

Runs 3 and 4 — steady state, nothing new:

```
$ python .scratch/run_refdes.py -c .scratch/stub-proj/refdes-project.yaml stub-tests
no coverable item is missing a verifying test
[exit=0]
$ python .scratch/run_refdes.py -c .scratch/stub-proj/refdes-project.yaml stub-tests
no coverable item is missing a verifying test
[exit=0]
```

Read-only paths, on a pristine copy (`.scratch/stub-proj-readonly/`, same
keyless project, nothing minted yet) — neither says anything about writes:

```
$ python .scratch/run_refdes.py --no-write -c .scratch/stub-proj-readonly/refdes-project.yaml stub-tests
would write 2 stub(s) to items/power/stub-tests.md: REQ-001, REQ-002
would write 2 stub test(s) across 1 file(s)
[exit=0]
$ python .scratch/run_refdes.py -c .scratch/stub-proj-readonly/refdes-project.yaml stub-tests --dry-run
would write 2 stub(s) to items/power/stub-tests.md: REQ-001, REQ-002
would write 2 stub test(s) across 1 file(s)
[exit=0]
```

and the tree was byte-identical after both — sha256 (first 12) of every file
before and after: `items/d.yaml 52b02d7e94c1`, `items/r.yaml c48263ed0f85`,
`refdes-project.yaml 7434ab48d5ef`, `refdes-schema.yaml 8a8cd461f48f`; total
`key:` occurrences across the tree: 0.

### CI

PR #97 (https://github.com/Squishiba/refdes/pull/97) — all three checks pass:
`ubuntu-latest` 4m20s, `ubuntu-latest / py3.13` 4m34s, `windows-latest` 5m10s.

Task finished.
