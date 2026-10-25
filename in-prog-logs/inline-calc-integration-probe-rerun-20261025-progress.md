# Progress log — inline-calc integration probe re-run, 2026-10-25

Goal: re-run all ten interactions of the 2026-10-20 inline-calc
integration probe against current main (78c8954, merged #345 gate + #347
HASH_FORMAT 6), verdict F1/F2, note new gate/hash6/fetch/source()
interactions. Report-only; no production edits. Deliverable:
`in-prog-logs/inline-calc-integration-probe-rerun-20261025.md`.

## What I did

- Read the old report + progress log via `git show FETCH_HEAD:...` after
  `git fetch origin report/inline-calc-integration-probe-20261020`.
- Runner `.scratch/rr-20261025/rd.sh`: `PYTHONPATH=<worktree>/src` +
  import-time `refdes.__file__` assertion, venv python; twin `rd-old.sh`
  pins a detached `wt-old` worktree at the original probe's main
  `d620ab5` (HASH_FORMAT 5, no gate) for the cross-version legs. Verified
  both trees' identities via the assertion + `grep HASH_FORMAT`.
- Probe projects under `.scratch/rr-20261025/`: p1 (stale span, gate
  switches, `--no-write`, history capture exemption, captured-edit
  re-offense), p345t (custom append-only `sealprobe` type, build seal
  exemption), pdep/pdep-old (scheduler gap, both trees), p56 (f5 stamp via
  wt-old → main's audit migration; hand-crafted f5 crossref entry;
  reverse `uncomparable` on wt-old; fence-change audit), p6 (calc_hash
  fixed under result edit, verdict-move stale-arithmetic signal),
  p7/p7u/p7-pristine (fetch pins span source key, guard note,
  `--update`, gate block→fix→stamp, F1 prune leg on wt-old, unrecognized
  key prune on main), p9 (deleted key × composite span, keys restore).
- Commands run: init, id, check, build, release, revision, audit, fetch,
  fetch --update, history capture, keys restore, --no-write release, plus
  `--help` for fetch/release/audit/keys/rename. Exit codes measured
  directly (no pipes) on every blocked path.

## Difficulties

- hardware@3 `log` requires `summary:` (first p1 item warned, fixed) —
  same trap as the original probe.
- A span cross-ref with no stored result is now an error (`#351`), so
  the original's `v := LOG-009.V_in` form had to become
  `= 12 V` — recorded as N9, it shaped the leg-4 repro.
- The original's "crossref item stamped at f5" is not reproducible as a
  live stamp (old main errors on the crossref span, check exit 1 blocks
  stamping); reconstructed by hand-crafting the f5 entry with its true
  f5 hash computed via `build.hash_for_format`, marked as such in the
  report (N4).
- `schema.load_project()` alone does not scan items; the hash helper
  needed `loader.load_tree(...)[0]`.
- Sandbox rules reject commands containing `..` paths and /tmp; reran
  affected legs with workdir-relative commands.
- Pipe-to-grep exit codes are the pipe's; re-measured blocked
  release/revision runs directly (exit 1 both).

## Status

Task finished (report-only). All ten interactions re-run with verdicts
(9 PASS/CHANGED-by-design, leg 4 FIXED, one sub-leg NOT REPRODUCIBLE as
stated); F1 STILL PRESENT cross-version / fixed on main's own cycle
(mitigation unimplemented — main also prunes unknown `values:` keys
silently); F2 and F3 FIXED; nine new rows N1–N9.
