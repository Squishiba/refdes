# user-sim-run16 progress log

Task: user-simulation release gate, run 16 — report-only. Delivered the
gate report as `user-sim-release-gate-run16.md` with evidence in
`user-sim-run16-evidence/`.

Done: ff-merged base to `9f15af87` (includes #463) and confirmed the
scope `d9719a9..origin/main`. Built a scratch multi-board project with a
forked design-log thread (two tips, keyless and id-less markers), calc
fences, checks, and a CSV citation with `source()` spans. Ran all seven
surfaces: Navis panels (Chromium + Firefox via puppeteer-core /
playwright-core against writable and `--no-write` serves), the serve API
matrices by curl, #450/#429/#410/#418 in the editor, the task-pane
tick/draft flows in both browsers, the continue endpoint, #449 fetch
pruning, the VS Code docs (recorded as untestable — no VS Code), the
0.5.0→current upgrade (real 0.5.0 wheel from PyPI, `docs/upgrading.md`
followed step by step, quotes diffed verbatim), and the README test
command (6250 passed, 2 skipped). Adversarial round: CRLF, non-ASCII
path, subdirectory, read-only tree, concurrent `refdes id`, typos,
hand-edged lockfile and duplicate keys.

Findings, final (matching the report's counts line and table): 1
Medium (F16-2, keyed id-less thread tip offered a save context the
continue endpoint refuses — fixed in #473), 3 Low (F16-1, the
`check`-loud/`navis`-silent asymmetry in the docs' pre-`refdes id`
window — fixed in #476 by a scan note plus #475's docs sentence;
F16-3, unconfirmed — a Firefox tick double-step that did not
reproduce on a clean re-run; F16-4, docs/upgrading.md gaps — fixed in
#475), 2 Cosmetic (F16-5; F16-6 stale task-pane docs — fixed in #475).

Difficulties: the repo dogfoods itself (`refdes-project.yaml` at the
worktree root), so probe projects under `.scratch/` were swallowed by
marker walk-up — added a stopper `refdes-project.yaml` in `.scratch/`
(and left it there, it is gitignored). One early "Restore enabled on an
orphan row" sighting was a rebuild race, re-verified clean. My first
task-pane and fetch probes failed on fixture bugs (missing `follows:`
edges → no pane at all; `.txt` has no source reader → used `.csv`;
record-level junk is not the #449 target → `values:` keys). A `cd`
slip made a `refdes build -q` run from `.scratch/pptr` with stderr
silenced, which read as a missing-pages bug; reran from the project
root. Two sed probes damaged `items/board-a/requirements/power.yaml`
(defaults block) and the citation ids collided; both repaired and
`refdes check` is green on the probe (18 items, 0 errors).

Four pre-merge review rounds reconciled the findings to the final
state above (F16-3 re-run clean and re-filed Unconfirmed, its
base-vs-main record anchored to a recorded command output in the last
round; F16-1
re-filed Low docs/UX with the `check`-loud/`navis`-silent asymmetry
and corrected citations; machine paths and captured tokens stripped
from the evidence, the uncited Firefox timeout run dropped, and
reproduction scripts added, all run against a `git archive` extraction
of current main; repro fixtures moved under `.scratch/` per project
rule and the truncated pane capture labelled as such in the report,
and the final round marking the statuses of the merged fixes
(#473/#475/#476) in the table and counts), with no product fixes made
by me (dispatched to other workers).
