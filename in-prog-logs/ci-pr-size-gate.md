# ci: PR size gate (src additions budget)

Task: mechanical PR-size gate — CI fails PRs adding >350 lines under
`src/`, waivable via the `size-exempt` label, grandfathering PRs < 400.
Approved by Jared 2026-10-31; spec decided in the handoff.

## What landed

- `tools/pr_size.py` (new): stdlib-only. `count_src_additions(numstat_text)`
  sums added lines for paths starting `src/`; `-` (binary) counts 0;
  rename forms resolved to the NEW path — full form `old => new` and brace
  form `src/{a.py => b.py}`. The brace regex uses `[^{}]*` segments so a
  line-wide match can't turn the "a" of a full-form `a.py => b.py` into a
  bogus `new` directory; brace form is tried first, full form is the
  fallback. `over_budget()` = the single verdict rule:
  grandfather (PR < 400) → pass; `size-exempt` → pass; `total > 350` →
  fail; exactly 350 passes. Missing PR number fails closed over budget.
  `main()` runs `git diff --numstat base...head` (three-dot), prints
  count/budget/top-files/remedy, exit 1 over budget, exit 2 if shas
  missing.
- `.github/workflows/pr-size.yml` (new): on pull_request (opened,
  synchronize, reopened, labeled, unlabeled), permissions contents: read,
  concurrency group, checkout@v4 with fetch-depth: 0, setup-python@v5,
  PR number/labels/base-sha/head-sha all read from the event payload
  (`join(github.event.pull_request.labels.*.name, ',')`) — no API call,
  no token. No dependency on the test matrix. First CI run FAILED at Set
  up job: the brief's claim that tests.yml pins action SHAs is false at
  current main (it and docs.yml use tags), and the SHA I had written from
  memory doesn't exist; fixed to the tag style the repo actually uses.
  Review round 1 found one real bug in my first payload approach (a gh
  labels step appending raw jq to $GITHUB_OUTPUT without a `labels=` key
  — invalid format whenever any label exists, waiver could never work;
  label-less CI run couldn't catch it), fixed by the event-payload read
  above and proven on real CI with a throwaway draft probe PR (#404,
  400 src lines: fail with OVER BUDGET; +size-exempt: labeled-event
  re-run pass with the loud notice; closed and branch deleted after
  capture).
- `tests/test_pr_size.py` (new): 15 pure-function tests (no git, no
  network): src-only counting, renames both forms into/out of src, the
  dots-in-basename brace edge, binary dash, empty diff, non-src dirs,
  `srcish/` and bare `src` not counted, exactly-350 pass / 351 fail,
  grandfather, waiver label matching, fail-closed.
- `changelog.d/pr-size-gate.added.md`: fragment added — repo convention
  includes dev-process changes in changelog.d (precedent:
  parallel-tests.changed.md for xdist).

## Decisions

- Docs paragraph SKIPPED: spec said add one "if a contributing/dev docs
  page exists". At current main (post #400) `docs/` has no such page —
  dev-process.md/contributing.md seen early in the session turned out to
  be untracked files in the main checkout (not in `git log --all`),
  removed by a concurrent session mid-task. Not creating a new page per
  spec.
- Grandfathering is by PR number < FIRST_ENFORCED_PR (spec) with the
  constant at the top of the script and a comment why.
- PR number missing → over-budget fails (enforcing gate fails closed; CI
  always supplies the number).
- Exempt + over budget prints a loud waiver notice, not split advice
  (it would advise adding the label that is already set).

## Verification

- Red-first: rename tests fail on the pre-fix script (into-src rename
  counted 0 not 9, out-of-src counted 9 not 0, no new_path_of); pass
  after.
- Real history, `git diff --numstat <merge>^1...<merge>` vs GitHub files
  API additions, exact match on all six: #382 1446 OVER, #393 640 OVER,
  #395 333 under, #388 544 OVER, #372 593 OVER, #397 0 under.
- Synthetic end-to-end via main() on a scratch worktree (360-line
  src file): PR 500 → exit 1 with remedy text; +size-exempt → exit 0
  loud notice; PR 399 → exit 0 grandfathered.
- Full suite (xdist -n 4): 5616 passed, 2 skipped.
- `ruff check` on the two touched python files: clean.
- Workflow yaml parses (safe_load). GitHub Actions itself cannot be run
  locally; observed on the open PR: round 1 pr-size FAILED at Set up job
  (unresolvable setup-python SHA — invented per the brief's false
  "tests.yml pins SHAs" claim; repo uses tags), fixed to tag style;
  round 2 on PR #402 (>= 400, so the enforced path): pr-size PASS with
  the expected 0/350 verdict in the job log, and the full tests matrix
  (ubuntu, ubuntu/py3.13, windows) passed on the final head. Probe PR
  #404 (throwaway, closed): oversized PR fails with OVER BUDGET, and
  adding size-exempt passes the re-run with the LOUD NOTICE — waiver
  proven on real CI, event-payload label read confirmed.

Status: finished — merged-ready, PR #402.
