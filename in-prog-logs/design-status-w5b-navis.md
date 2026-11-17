# design-status-w5b-navis

## Task

Docs pass 2 of 2: stale `Status:` lines for two shipped features — W5b
(thread workbench tick → draft continuation) and Navis in the VS Code
extension. Update only status/implementation-status wording in the two plans
plus `thread-workbench.md`; do not rewrite plan bodies.

## What I verified, and how

- Base is `e6927ed6` (main, post-#487) after `merge --ff-only origin/main`;
  no local commits existed first.
- `git log --oneline origin/main | grep -i -E 'W5b|tick|save|navis|vscode'`,
  then `gh pr view` on every cited PR (all `MERGED`):
  W5b.1 #448, W5b.2 #453, W5b.3 #456, W5b.4 #460/#461/#462/#463, save seam
  #468/#474, W5b.5 #470; fixes #473 (id-less tip), #477, #481, #485.
  Navis: plan #455, S6.1 #457, S6.2 `post()` #458 / decisions #459 / commands
  #464, S6.3 #469, lock-tooltip fix #482, S6.4 + 0.2.0 #472.
- Tree, not memory: `src/refdes/serve/api.py` has the `/continue` route and
  `serve/edit.py:continue_thread`; `src/refdes/serve/static/` has
  `tick-drafts.js`, `tick-pane.js`, `tick-save.js`, `taskpane-save.js`,
  `taskpane-ticks.js` (Discard, beforeunload, conflict panel); tests
  `test_continue_capture.py`, `test_task_pane_save_discard.py`,
  `test_task_pane_save_ui.py` pin the seam and the predecessor capture.
- CLI claim checked by running `refdes --help` (absolute `PYTHONPATH`): no
  `continue` command, so Q10's ratified (a) still holds — the pane is the
  only continuation write route.
- Extension: `editors/vscode/package.json` is `0.2.0`; commands
  `navisArchive`/`navisRestore`/`navisMint`/`refreshNavis`/
  `navisOpenInEditor`; `navisTree.js` has the `Mint keys (N)` row and
  read-only tooltip. Read-only tooltip surviving repaints is #482.

## Edits

- `docs/design/thread-workbench-w5b-plan.md`: Status -> Implemented, phase by
  phase with the PRs above; records the id-less-tip refusal and that no
  `refdes continue` exists. Also reworded the drafting-time §2 sentence that
  cited W5b as "Not started" (status wording only; design content untouched).
- `docs/design/navis-vscode-panel-plan.md`: Status -> Implemented in
  extension 0.2.0, slice by slice with PRs; notes Mint row + Refresh Navis;
  says publishing stays Jared's (Q6).
- `docs/design/thread-workbench.md`: Status paragraph and §8 W5b bullet move
  "not started" -> landed, pointing at the W5b plan.
- `changelog.d/design-status-w5b-navis.fixed.md`: repo convention for stale
  design Status corrections is `.fixed.md` (`design-doc-statuses.fixed.md`,
  `backlog-stale-status-lines.fixed.md`), so I used that rather than the
  suggested `.changed.md`.

## Other design docs

No other `docs/design/` file mentions W5b or the Navis VS Code panel in its
status, so nothing else was stale for these features. Other `Status:` lines
using proposed/plan wording that are unrelated and left alone:
`form-ingestion.md` (proposed, no code), `seal-marker-identity.md`
(proposed), `item-search-hover.md` (proposed search half; adapter half
shipped, already says so). `editor-vscode-adapter.md` already says its
webview/V1/V2 remain design only. `living-notes-plan.md` claims H1–H9;
AGENTS.md notes optional H9 is not landed — out of scope here.

## Checks

- `tests/test_docs_anchors.py` + `tests/test_crossplatform_lint.py`: 28 passed.
- `docs-site/gen_examples.py --check`: both generated docs up to date.
- Full suite run once before pushing.

## Not verified

- No real VS Code window / real browser was used: the task scoped this to
  docs, and every shipped claim is pinned by an existing node/HTTP test or is
  readable in `package.json`/source.
- CI on ubuntu + windows is the remaining check.

## Status

Complete locally; PR opened after the full suite, then awaited CI.
