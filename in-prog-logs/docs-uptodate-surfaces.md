# Docs up-to-date pass — group "surfaces"

Base: `git fetch origin main && git merge --ff-only origin/main` was already
up to date at `e6e3eb82` (#490). Every refdes run used an absolute
`PYTHONPATH=<worktree>/src`.

Method: one page at a time, read fully, then check every runnable/claimable
fact (commands via `--help`/scratch runs, messages via `src/`, anchors via the
docs tests). Scratch projects live in `.scratch/ws`, `.scratch/ws3`.

## docs/index.md — checked-clean

- Compared `ls docs/*.md` (28 non-index pages) with the index rows: every page
  listed once and no dead link (shell loop over `docs/*.md` + `grep` on the
  index). All 28 one-line descriptions checked against each page's opening
  (`sed -n '1,6p'`) and the deeper pages read in full; kept as-is.
- `pytest tests/test_docs_anchors.py tests/test_docs_examples.py` green.

## docs/navis.md — checked-clean

- Read fully. Verified against `refdes navis --help`, `src/refdes/cli.py`
  (mint notice, selector/exit messages at 3003-3222), `navis.py:1350`,
  `serve/navis_write.py`, `serve/navis_mint.py` (refusal text, `still_keyless`,
  `mint is disabled`), `navis-panel.js`/`navis-preview.js`, and the VS Code
  README section. Grammar link target exists. No edit.

## docs/browser-editor.md — checked-clean

- Read fully. Checked the 12+8 buttons against `formatbar.js`
  (`BUTTONS`/`REFDES_BUTTONS`), `PICKER_LIMIT = 5000` (`pickers.js`), font
  defaults/ranges (`fontsetting.js`), the 400 ms debounce (`live-calc.js`),
  skeleton-gate text (`inline_calc.py`, `tests/test_editor_skeletons.py`), and
  the task pane against the `thread-*`/`tick-*` changelog fragments. "CI has no
  browser job" still true (`.github/workflows/` has no browser job). No edit.

## docs/multi-board.md — changed

- Verified board/workspace config keys and every quoted message against
  `src/refdes/schema.py:1039`, `boards.py:189/553`, `build.py:1174-1229`,
  `configcheck.py:478`, `imports.py:45/87`, `build.py:905-965`, and
  `refdes build --help` (`--accept-board-move`, `--reseal [BOARD]`). All match.
- Changed one line: "once the history layer lands" → "once the git-history
  layer lands". The shipped `sealing: history` store made the old wording
  ambiguous; `README.md:380-386` and `docs/change-tracking.md` confirm the
  git-history layer and suspect links are still unbuilt.
- "Not built yet: federated view" still true (`README.md:387-391`).

## docs/workspaces.md — changed

- Built `.scratch/ws` (`item_layout: workspace`, boards + workspaces) and ran
  `refdes --no-write ls` / `check`: the workspace column, the blank board cell
  for an unboarded workspace item, and the row shape match the page.
- Built `.scratch/ws3` to reproduce the name collision: got the exact
  `configuration error: 'power' is declared as both a board and a workspace …`
  at exit 2.
- Verified `item_layout`/`cross_workspace_severity` (`model.py:1173-1196`),
  `--workspace` on `check`/`ls` (`--help`), the cross-workspace warning
  (`workspaces.py:129`), and the drift/audit sections (`boards.py:553`,
  `cli.py:2001`).
- Changed one clause: "any future aggregate view (a parts index spanning
  workspaces, say)" → "a derived aggregate view (the project-wide `parts.html`
  index spanning workspaces, say)". `render.py:1615` writes the global page
  today and `parts.md:42` documents it, so it is not future.

## docs/performance.md — changed

- The full measurement (1500-item build ~20 s × 3 plus serve rebuilds and
  corpus generation) is not < 2 min, so it was not re-run.
- Ran the cheap part: `refdes --no-write check` on this repo → 20 items, exit
  1, one failing check, matching the page's "real" project description.
- Changed: "fresh numbers" → "measured numbers"; added a paragraph saying the
  numbers were measured on 2026-10-19 and are a historical baseline (not
  re-measured, method still recorded); "overstates today's cost" →
  "overstated the cost … when these numbers were taken".
- Could not verify the absolute timings/RSS against today's code.

## docs/design-log.md — checked-clean

- Read fully. Verified hardware@3's `log` is `sealing: history` and its
  `tasks:` is `on_change: timeline` (`standards/hardware/v3/base.yaml:280-305`),
  `refdes history --help` (`capture`/`redact`/`migrate-seals`), the `audit`
  wording (`cli.py:1874-1925`), the release-nudge ids, and that
  `.refdes/history/events` still holds six records (the line 347 claim). No
  edit.
- `follows:` is authorable again: hardware@3 declares it (`base.yaml:166`),
  so the older `follows-docs-honesty` fragment no longer applies.

## Tests

- `pytest tests/test_docs_anchors.py tests/test_docs_examples.py
  tests/test_crossplatform_lint.py`: 34 passed.
- docs-context refs/ask/focus/cache: 141 passed.
- `python docs-site/gen_examples.py --check`: both generated pages up to date.
- Full suite once before pushing: `6456 passed, 2 skipped in 129.17s`.
