# n6-ratify — record Jared's ratification of the N6 plan questions

Docs-only task. Jared accepted the recommended default for all seven
questions of `docs/design/navis-vscode-panel-plan.md` §12 on 2026-11-08:
Q1 (a) GET /api/navis; Q2 (a) native TreeView; Q3 (a) Explorer section,
no activity-bar icon; Q4 (a) Mint as an explicit command; Q5 (a) lazy
server boot on expand; Q6 (b) bump at S6.4, one publish, publishing stays
Jared's call; Q7 (a) visible empty "no Navis" state.

Convention copied from `docs/design/thread-workbench-w5b-plan.md` as
ratified in #436: Status line re-stated with the ratification date, each
question gets a `**Ratified 2026-11-08: (x)**` line under it, and a
sentence under the section heading.

Edits (only these, no option wording touched):
- Status line: `**plan, proposed** (2026-11-05)` ->
  `**plan, questions ratified** (2026-11-08)`.
- §12 heading: one sentence that all seven defaults were ratified as
  written on 2026-11-08.
- Q1–Q7: one Ratified line each, naming the accepted letter.

Checks run:
- `.github/workflows/docs.yml` read: `gen_examples.py --check` and the
  docs-site build (pages: ../docs, which includes docs/design) run on
  pushes to main only — not a PR gate. Ran `--check` locally anyway:
  pass.
- `tests/test_docs_anchors.py`: pass.
- No changelog.d fragment (design doc, no user-visible change).

Finished. No difficulties; task was bounded to two sections of one file.
