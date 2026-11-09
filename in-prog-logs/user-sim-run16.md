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

Findings: 3 Medium (id-less-item navis blindness — pre-existing, base
confirmed via `git archive` of `d9719a9`; id-less-tip continuation
refusal + empty-label message with the pane's key-only save-context
gate; Firefox double-stepping a tick click through the wrapping label),
1 Low docs (upgrading.md misses the `history:`→`on_change:` step that
its own probe class hits, and under-describes the debate-overlay
remedy), 2 Cosmetic.

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
