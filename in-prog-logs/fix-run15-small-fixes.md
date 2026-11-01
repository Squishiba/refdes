# fix: run-15 small findings (F15-2..F15-4) and the lint timing flake

Branch `fix/run15-small-fixes`, base `845501d` (fast-forward confirmed;
PR size gate #402 present). Source: PR #408's
`in-prog-logs/user-sim-release-gate-run15.md`. Four items, one commit
each, one PR. All src lines changed: 1 (`navis_archive.py`) + fragment
edits -- far under the 350-line gate.

## F15-2 -- changelog overclaim about the skeleton snippets (docs)

`changelog.d/editor-refdes-buttons.added.md` claimed all four §H-4
skeleton snippets "intentionally fail the gate until completed". The
design (in-prog-logs/editor-format-toolbar-design-20261029.md, §C
table): Jared's "fails the build" decision covers only the calc fence
and the inline span; figure `[[fig:]]` is "Cheap skeleton" and value
`{{}}` is explicitly safe (unresolved names stay as written with a
warning). Verified by running, not recalling: scratch project
(`refdes init`, hardware@3, `item_layout: flat`) --

- span `` `name := 0 | V` `` -> ERROR `inline calc name := 0 | V:
  stored result missing; write '= <quantity>'`, check exit 1;
- calc fence -> ERROR `calc 'fence': unknown name 'expr'`, exit 1;
- `[[fig:]]` + `{{}}` only -> 0 errors, check exit 0, build exit 0
  (fig adds a warning, not a gate failure).

CHANGELOG.md had not folded the fragment (grep: no skeleton entry in
`[Unreleased]`), so the fragment is the only fix. `docs/` carries no
copy of the overclaim (grep for "fail the gate" / "skeleton" over
docs/*.md: only unrelated list-file-skeleton hits). Rewrote the bullet:
calc skeletons fail the gate and block saves; fig/value insert literal
text that saves cleanly. Docs claims above are all from that scratch
run.

## F15-3 -- corrupt archive record warning carries no code

`_corrupt()` in src/refdes/navis_archive.py built the message without
`NAVI_ARCHIVE_CORRUPT_CODE`, while docs/cli-reference.md:750 documents
the warning *as* `navis.archive_corrupt` and the sibling
`navis.archived_orphan` warning prints its code as a message prefix
(navis.py:1530, cli.py:3054). Red-first: new test
`test_corrupt_record_warning_prints_its_code` (asserts the rendered
diagnostic and the CLI stderr contain `navis.archive_corrupt: navis
archive record is unreadable` and keep "skipped, not deleted") failed
on the base text, passes after the prefix. No existing test pinned the
old text positively: the file's corrupt pins match on code / needle /
filename; line ~695's pin is a negative assertion ("not in stderr"),
which still bites since the new text contains the old substring.
Added `changelog.d/navis-archive-corrupt-warning-code.changed.md`.
All 36 tests in tests/test_navis_archive.py green.

## F15-4 -- width-dependent --no-write help pins

Reproduced on the base: `COLUMNS=60 pytest tests/test_no_write.py -q`
-> 2 failed (IndexError from `out.split("explicit write commands
either")[1]`). First attempt (collapse whitespace runs only) fixed the
narrow widths but exposed a second failure mode at COLUMNS=95/200:
argparse breaks inside hyphenated words, so `calc-rewrite` renders as
`calc-\n<indent>rewrite` and collapsing yields `calc- rewrite`,
breaking the exact set pin. Final fix in `_no_write_help`: rejoin
hyphen line breaks (regex dash, optional whitespace, newline,
optional whitespace), then collapse whitespace, then split as before. The
assertions are unchanged -- same phrase, same exact command set.

Swept every test file that drives `--help` (grep
`format_help\|--help\|COLUMNS` over tests/): the other 14 files pass
at COLUMNS=50 and 200 as-is (reported, not touched). One reproducible
failure in the sweep: test_index_help.py::test_index_help_says_who_the
_command_is_for at COLUMNS=50 -- its helper already collapsed
whitespace but not hyphen breaks, so "machine-readable" split; same
treatment applied. Green across COLUMNS 20..300.

## Lint timing flake -- test_rules_scan_the_tree_fast

Wall-clock `elapsed < 10.0` reproduced red at ~24-load (40 CPU hogs):
failed at 17.4s wall for a scan that takes 3.4s of CPU here. Replaced
with: floor on scanned-file count (>= 250, measured 273 -- pins "fast
by scanning nothing"), and `time.process_time() < 60.0` (~17x the
measured 3.4s CPU; preemption inflates wall, not CPU, so xdist load
cannot flake it). Docstring records the measurements and the argument.
Green under the same 40-hog load (12.4s wall, CPU bound untouched).
Pathological-slowdown check kept honest by probe
(.scratch/f15-4/probe_slow.py): rule checks burning 0.25s CPU per file
over the same 273 files reach 69.4s process_time and trip the 60s
bound; the real scan is ~12,700 files/s, so a 1000x slowdown is
caught. Not simply "30".

## Verification

- Red/green evidence per item above, each shown failing before the
  change and passing after.
- Full suite once: `pytest -q -n 4 --dist worksteal` -> 5632 passed,
  2 skipped (166.92s).
- `ruff check` on the four touched files: clean except one
  pre-existing I001 in test_no_write.py (line 596's
  `from test_calc_rewrite import YAML_ITEM, SCHEMA`) -- verified
  present at HEAD before my change, left alone per AGENTS.md.

Status: all four items completed; nothing needed the STOP clause.
