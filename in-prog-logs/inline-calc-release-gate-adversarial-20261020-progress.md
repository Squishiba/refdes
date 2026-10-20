# inline-calc-release-gate-adversarial-20261020 — task progress

Task: Claude-lane independent verification of PR #345
(`release_gate.inline_calc_results`) at its head SHA, adversarial matrix for
policy bypasses and false refusals, report-only (no product edits, no merge,
no touching the PR branch). Authorized by Jared during Sol cover.

## What was done

- Pinned the audit tree: fetched `refs/pull/345/head` twice (start/end),
  head = `4e89eabfc8cdfd799670cac4850d98519a7709c2` both times; export via
  `git archive` to `.scratch/pr345src` (exact head tree).
- Environment hazard found early: the machine venv's `refdes` console script
  imports `/home/jorb/work/refdes/src` (a different checkout). All runs use
  `env PYTHONPATH=<worktree>/.scratch/pr345src/src <venv>/bin/python3 -m
  refdes.cli`, with `refdes.__file__` (and lifecycle/inline_calc/build)
  asserted to resolve under `.scratch/pr345src` before running.
- Read the PR diff (lifecycle/model/build + docs + tests) to fix the policy
  expectation in writing before probing.
- Built real CLI projects under this worktree's `.scratch/` (`m1` main,
  `mup`/`cons` import pair, `probe1` fence-reference probe). Reached every
  matrix state through shipped CLI (`init`, `build`, `check`, `release`,
  `revision`, `history capture`, `build --reseal`) plus plain text edits to
  item files; corrupt-store states produced by hand-corruption/`chmod`
  (recorded as not CLI-reachable, honestly).
- Ran the matrix: editable-stale, fresh, build-sealed, captured,
  capture-then-edit (and revert-to-captured), inert/foreign capture record,
  cross-item dependency change (editable, captured, sealed variants),
  no-inline-calc, ordinary check/build, revision half, both overlay halves,
  `--no-write`, multi-span item, imported artifact. Recorded exact outputs
  and exit codes.
- Difficulties: two early probes ran on an accidentally clean project state
  and one on a seal-floor-contaminated state; both re-run with an explicitly
  stale item, only the clean re-runs are cited (hygiene section in the
  report). Bash tool output truncation in this harness — switched to
  per-step greps. Inline span with a dotted cross-item reference (`CMP-002.
  V_in` directly in a span) errors as `unknown name 'CMP'` — matches the
  docs' documented known gap (span-only cross-item references); dependency
  probes used the fence-reference + span-uses-fence-name form, which works.

## Outcome

- Finished. Deliverable report: `in-prog-logs/inline-calc-release-gate-adversarial-20261020.md`.
- Head moved mid-audit: `4e89eab` (all probing) → `c1c6afb` (finish check).
  The head-to-head `src/` diff is confined to the rule's offender lookup.
- One P1: the rule fails open on an unreadable history store
  (`HistoryError`/`OSError`), so a release stamps with a stale, editable,
  non-exempt span; the emitted warning names only edited-after-captured,
  and the user-visible docs promise the default-on rule fails a release
  (no corruption exemption documented). Repro in the report; re-verified at
  `c1c6afb`.
- One P1 fixed under this audit: at `4e89eab` a stale span in a permanently
  id-less `follows:` continuation (empty diagnostic id) escaped the gate
  entirely (release stamped, baseline written — verified on both heads:
  stamps at `4e89eab`, blocks naming the key at `c1c6afb` via `1f0a7c3`).
  Recorded honestly as found-live-at-old-head / fixed-at-current-head; this
  lane's `4e89eab` probes missed the id-less path (a `require_ids` reading
  that continuations disprove).
- Two P2s: "the span's line" is the item line for YAML-sourced items; the
  capture exemption (per its written wording) also exempts staleness induced
  by an upstream editable dependency move, asymmetrically vs the seal floor
  which catches the same move as an error.
- No false refusals found in the matrix; revision half, overlay halves,
  `--no-write`, imports, and check/build floor behavior all match the docs.
- Report-only: nothing in `src/`, `docs/`, `tests/` touched; PR #345 branch
  untouched; scratch left under `.scratch/` per AGENTS.md; no stash used.
