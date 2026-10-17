Task: verify every factual claim in README.md against actual behavior of the
tool (running the CLI where possible), fix the README where it is wrong, and
note (not fix) any other docs page that contradicts a verified claim.
Branch: docs-readme-verify, forked from main at fd8dcee. Docs-only change.

Method
------
Built throwaway projects under .scratch/rv1..rv6 (gitignored, left in place)
with `refdes init` (hardware@3) and ran the real CLI + full build for each
README section: authoring, math/checks, change tracking, design log, sealing,
coverage, boards, imports, lifecycle, output, editor support, known
limitations. Verified release.py by reading its code (no PyPI publish — the
script itself refuses to run against real PyPI state we must not pollute).
CLI commands/flags verified by running them and by `--help` output.

Claim audit (result per claim)
------------------------------
VERIFIED (matched observed behavior):
- Commands block: init/build/check/index/id/audit and their descriptions;
  `--help` lists new, schema, fetch, revision, release, stub-tests, rename,
  standard, former-ids. check exits non-zero on errors.
- Install: `pip install -e .` works (in rv1 venv).
- YAML/MD authoring formats, `defaults:` prefix block, `refdes id` writes ids
  back, IDs position-independent (insert at top: new item got REQ-X-003,
  existing unchanged).
- Math: P=V*I|R works, unit mismatch is a build error, {{P_diss}} substitution
  in body (0.2981 W), worst-case bound check "worst case 4.24 W vs <= 4.2 W",
  `0.2366 W/in^2` pinned by `| W/in^2` assertion, `12 V (11.4 V ... 12.6 V)`
  tolerance band, `9.81 m/s^2`, N*m reads N-m, [N*m] bracket units, unit
  collision is a warning with `1.2 [A]` silencing it, W/h not flagged,
  `x - x` reports non-zero interval width, `V + A` error names V and A,
  DSL whitelist (sqrt/log10/ln/exp/min/max/abs; no trig, no sympy), no
  loops/conditionals/imports/attribute-access.
- Change tracking: invalidate fields only in content hash (owner change did
  not invalidate a linking item; value change did); project `on_change:`
  default applies; item override suppresses baseline diff; audit lists
  suppressions with reason.
- Design log: captured-history edit warning matches README's quoted warning
  nearly verbatim (ids, uuid, amends advice, troubleshooting link);
  `refdes history capture` works; sealing: build on v3 opt-in project seals
  on first build, edit after seal is an error, `--reseal` works, audit
  reports resealed; capture+seal can't coexist (warning, sealing wins).
- Coverage: open/addressed/satisfied/verified semantics; satisfied-without-
  verified; coverage.html least-covered-first; items.json coverage field.
- Boards: opt-in inert without registry; board = first path segment under
  items/; unregistered board = build error; token lint is a warning naming
  the id; move between board dirs = warning naming both, silenced by
  --accept-board-move (which records into .refdes/boards.yaml); per-board
  pages; repo's own refdes-project.yaml registers board-a/board-b.
- Imports: read-only; version mismatch = hard error; ID collision = hard
  error; DISPLAY-ID@key for renamed imports; imported content-hash preserved
  (hash-missing warning identical); imported items excluded from coverage;
  ref page lists dependent local items (refined_by).
- Lifecycle: draft/revision/release states; revision/release write
  .refdes/baselines/<name>.yaml; release gate FAILs listing uncovered
  requirements; re-stamp same content = no-op; same name + changed content =
  error; audit reports changes since last revision and last release;
  release command help notes there is no --dry-run.
- Output: _site/index.html, document.html, tree.html, coverage.html,
  summary.html (+ per-board pages), items.json; summary.html sections
  Margins (worst-case slack, tightest first) / Computed values / Not linked
  to anything (checked-against counts as traced — verified BND excluded,
  REQ-PWR shown); hover previews keyboard+Escape+touch in static/app.js;
  site works JS-off; downstream reads items.json (margins + computed values
  present there).
- Editor support: F5 launches Extension Development Host (editors/vscode
  README line 171); inline calc results, live diagnostics, id completion,
  hover previews, go-to-definition all present; no build step (plain JS, no
  deps); tasks.json problem matchers.
- Not built yet: git-history layer (timeline column is design intent —
  verified `timeline` and `ignore` behave identically), federated view,
  solving for unknowns (forward evaluation only), Monte Carlo, KiCad/xlsx
  import.
- Known limitations: torque displays as J; interval width over-approximated;
  no `--dry-run` on release (help text confirms).
- Releasing (verified by code read of release.py, not executed against PyPI):
  bumps pyproject, folds changelog.d fragments into CHANGELOG [Unreleased]
  and deletes them, cleans build output (dist/ + build/), rebuilds, twine
  check validates; refuses on dirty tree, version <= current, version
  already published; --dry-run runs checks and changes nothing; component
  releases bump only the named component's file.

FIXED (README was wrong; each reproduction kept in .scratch/rv*):
1. `cd docs-site && refdes build # -> _docs/index.html` — build writes
   `_docs/index.html` at the repo root (out: ../_docs in
   docs-site/refdes-project.yaml); comment now says so.
2. Install/tests commands used Windows venv paths (`./.venv/Scripts/
   python.exe`) inside a bash block; now POSIX `./.venv/bin/python` with a
   Windows (PowerShell) comment. Reproduced in rv1.
3. YAML authoring example used `- text:` — hardware@3 renamed
   requirement.text to requirement.body; `text:` is a build error ("...is
   now 'requirement.body'"). Example now uses `body:`. Verified end-to-end
   in rv6 (see sabotage below).
4. `refdes audit` comment said "board moves, and imports" — it also lists
   workspace moves and baseline diffs (matches `refdes audit --help`).
5. Authoring note: `refdes id` also mints the item's surrogate `key:` line
   (README omitted it; docs/ids.md documents keys as the stable anchor).
6. on_change table: mode `log` renamed to `timeline` in hardware@3 (the
   v3 schema calls it `timeline`); the sentence "so `log` and `ignore`
   behave identically today" updated to `timeline`/`ignore`. Verified:
   timeline and ignore produce identical baseline/hash behavior.
7. on_change paragraph: "(with a required `reason:`)" — a required reason
   exists only for whole-item mapping overrides; for a field-list override
   an omitted `reason:` is a warning, not an error (observed warning text).
   Reworded to match.
8. Design-log paragraph claimed `board:` on a log entry is "the log type's
   own hand-typed field, not the boards: registry's reserved key" — flatly
   wrong: the v3 log type declares no board field; `board:` on a log entry
   IS the reserved registry key (unregistered name = build error; scoped in
   board pages). Rewrote.
9. Coverage "Three separate questions" table — code has FIVE stages
   (model.py Coverage.stage: open/addressed/claimed/satisfied/verified,
   used by render.py sort and index.html grouping); added the `claimed` row
   and said "Five". `satisfied` row reworded to match docs/coverage.md
   ("settled verdict entry or component").
10. Boards section per-board page list omitted `tree-<board>.html` (written
    by render for every board). Added.
11. Torque limitation said "Pin it with an assertion (`tq = … | N*m`) if it
    matters" — verified FALSE: `tq5 = 5 N·m | N*m` displays "5 J" (assertion
    does not pin the display). docs/math.md:500 says the same. Reworded to
    match math.md.
12. Verified the captured-history warning link renders the live URL
    https://squishiba.github.io/refdes/troubleshooting.html#the-design-log
    — matches docs/troubleshooting.md heading anchor. No fix needed.

Possible bugs (reported, NOT fixed — docs-only task):
- None found in the tool. All tool behavior matched docs; every defect was
  in README.md. (Wording nit, not fixed: README's audit comment now lists
  five audit sections matching `--help`.)

Sabotage check (COMMON.txt: revert a fix, watch its test fail, restore):
- Reverted fix #3 in a fresh rv6 project by writing the example with
  `text:`: `refdes check` -> 2 ERRORs "'requirement.text' is now
  'requirement.body'", exit 1. Restored `body:` -> `refdes id` allocated
  REQ-PWR-001/002, `refdes check` -> "2 items, 0 errors", exit 0.

Other docs pages contradicting verified claims:
- None found. Checked docs/math.md (torque assertion wording — README now
  matches it), docs/change-tracking.md, docs/coverage.md, docs/ids.md,
  docs/getting-started.md, docs/multi-board.md, docs/lifecycle.md,
  docs/importing.md, docs/sealing.md, docs/troubleshooting.md.

Gates (run last, before commit):
- `ruff check --select E9,F src tests`: clean.
- `python docs-site/gen_examples.py --check`: OK.
- Full suite: PYTHONPATH=$PWD/src python -m pytest -q -p no:cacheprovider
  -> 3969 passed, 2 skipped, exit 0 (352.8s). ruff (E9,F, src tests) clean.
  gen_examples.py --check: schema-reference.md and vocabulary.md up to date.
- No changelog fragment: repo rule (changelog.d/README.md) — fragments
  describe changes a *release* ships; this is a docs-only README fix with no
  behavior change.

Status: COMPLETE. Committed with README.md + this log, branch pushed, PR
opened against main (URL in final summary).
