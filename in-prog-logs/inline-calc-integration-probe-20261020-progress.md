# Progress log — inline-calc integration probe, 2026-10-20

Goal: independently verify inline-calc slice-1/2 + release-gate work as an
end-to-end user, read-only, on origin/main + PR #345/#347 heads. Report-only
deliverable; no production edits. Authorized by Jared during Sol cover.

## What I did

- Fetched origin; recorded heads: main `d620ab5`, #345 `4e89eab`,
  #347 `c5c3b8d`. Built detached probe trees `.scratch/wt-345`,
  `.scratch/wt-347`. Runner `.scratch/rd.sh` pins `PYTHONPATH=<tree>/src`
  and asserts `refdes.__file__` per invocation (venv python 3.13.5).
- Read `docs/design/inline-calc.md`, the #345 lifecycle/model/build diff, and
  the #347 build/inline_calc/links/citations/serve diff before probing.
- Probe projects under `.scratch/`: p1 (literal stale span), p345, p345t
  (custom build-sealed type), p347a–h (hash/probe/deps), p347s/pfence
  (source() spans), pdep1/2 (scheduler gap), pm1/2 (main-side migration).
- Ran real commands: init, id, check, build, release, revision, audit, fetch,
  fetch --update, history capture, --no-write release.
- Findings and all verified interactions are in
  `inline-calc-integration-probe-20261020.md`. Headline: gate semantics
  (default offender block, release/revision switches, seal/history
  exemptions, captured-then-edited re-offense, exit codes) and the
  format-5/6 migration story behave as designed; one new cross-version hazard
  (F1: plain `fetch` from main/#345 prunes #347-pinned span source values
  from the lockfile, breaking #347 builds until re-fetch).

## Difficulties

- My first probe file used a `title:` field on `log` (hardware@3 has no
  title; summary only) — warnings, not tool bugs.
- A `cp -a src dst` onto an existing `dst` nested the copy (p345s) and fed
  the wrong project to a fetch probe; redone as p345u. No damage.
- A stray `refdes init` run from the shell's cwd (not the project dir)
  dropped a config at `.scratch/` root; removed.
- Parallel bash calls intermittently drop trailing output; re-ran affected
  commands individually.
- Exit codes read through `| tail` are the pager's; re-measured the blocked
  release/revision paths directly (both exit 1).
- The `audit` hash_format rewrite looked like a #347 regression; main
  reproduces it with a hand-set `hash_format: 4` (pre-existing, documented
  migration) — reported as such, not as a finding.

## Status

Task finished. Report at
`in-prog-logs/inline-calc-integration-probe-20261020.md` (no self-commit
SHA). PR heads moved mid-probe (recorded in the report); all evidence is
tied to the old SHAs and no current-head coverage is claimed.
