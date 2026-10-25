# Progress — adversarial release-gate audit re-run at main 78c8954

Task: re-run the 18-row PR #345 release-gate audit matrix against current
main (which includes merged #345, F13-1/#368 and HASH_FORMAT 6/#347),
re-test the F1/F1b P1 findings and F2/F3 P2 notes, add >=10 fresh gate
attacks, deliver the report + this log, PR report-only.

## What I did

- Read AGENTS.md and the original report from
  `origin/report/inline-calc-release-gate-adversarial-20261020` (fetched,
  read via `git show FETCH_HEAD:...`).
- Pinned everything: worktree HEAD 78c8954; CLI runs as
  `env PYTHONPATH=src .../venv-refdes/bin/python -m refdes.cli` (plain
  `-m refdes` has no `__main__` on this tree — used `-m refdes.cli`, as the
  original lane did); asserted `refdes.__file__` resolves inside this
  worktree (the documented venv trap).
- Built isolated projects under `.scratch/rerun/` (m1 matrix with the
  append-only `dsn` overlay type + captured LOG-001 + rail CMP-002 +
  cross-ref CMP-003; m3/m4 id-less continuations; mup/cons2 imports; cons
  no-calc; atk attack surface). States via shipped CLI + item-file text
  edits only.
- Re-ran all 18 rows. All reproduce: 18 PASS (no regressed rows; only
  line-number offsets from scaffold shape, exactness verified).
- Focus findings: F1 FIXED (corrupt YAML + chmod-000 store now fail closed
  naming the store, F13-1 shape; round-trips on restore). F1b FIXED both
  variants (list-file `16cr8bt0b74: ... log.yaml:7`; Markdown
  off-first-body-line `cvqykwzdaey: ... notes.md:13`). F2 FIXED as a docs
  correction (span-line/entry-line sentence in lifecycle.md + math.md). F3
  behavior STILL PRESENT (by design) with the requested docs note landed.
- Fresh attacks A1..A16 (15 rows, >=10 required): fenced/escaped/commented
  spans inert, unclosed-comment documented decline, duplicate-name floor,
  rename/composite-handle refresh under hash-6, unit-window spans, CRLF,
  pages inert, capture-exempt + corrupt store, --no-write parity, unicode
  name (error floor), duplicate id (floor), no-stale-span + corrupt store
  (gate silent, by design).
- New finding F-R1 (P3 cosmetic): id-less continuation with no minted key
  (read-only load) yields the offender `: inline calc Vfb (file:line)` —
  empty label with leading colon; fails closed, file:line present.
- Corroboration: `tests/test_inline_calc_gate_unreadable_history.py` +
  `tests/test_lifecycle.py` → 58 passed. Full suite not run (report-only);
  ruff baseline not a gate per AGENTS.md.

## Difficulties

- First row-1 run had LOG-001 uncaptured (two offenders) — the original m1
  had it captured; re-ran in that state.
- Self-inflicted, disclosed in the report: (1) an A1 restore copied event
  file A over event file B → store validator's id/filename mismatch made
  the gate fail closed on my bug; deleted the file, re-captured via CLI,
  re-ran F3 clean. (2) Row 16: I hand-wrote a bogus `key:` line; key-check
  + baseline-key floor errors fired; restored CMP-001's real key (named by
  the baseline) as the error message says; cited the clean run.
- `cd` + relative `../../` backups hit the harness path rule; switched to
  running the CLI from the worktree root with the global `-c <project>` and
  keeping all temp files under `.scratch/` (gitignored).
- Original report's projects no longer exist; the matrix scaffold was
  rebuilt from its descriptions (span formulas, item roles), so cited line
  numbers are this scaffold's, with exactness (not the number) as the
  claim.

## Status

Finished: all 18 rows re-run, all focus findings adjudicated with
reproducers, 15 fresh adversarial rows recorded, deliverable report at
`in-prog-logs/inline-calc-release-gate-adversarial-rerun-20261025.md`.
Committed and pushed as a report-only PR; no merge on own review.
