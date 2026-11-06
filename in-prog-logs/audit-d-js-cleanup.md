# SLICE AUDIT-D — serve JS cleanup (5.1 dead exports, 5.2 shared el helper)

Branch `chore/audit-js-cleanup`, base `3e2ebefa` (post-#402, fetched +
ff-merged first; tree was clean).

## 5.1 — dead exports

The audit claimed 5 dead exports in `src/refdes/serve/static/`. Re-check
per export (grep `serve/static/*.js` + `tests/*.py` +
`src/refdes/serve/server.py` js_export harness imports):

- `corruptDraft` (drafts.js), `FIGURE_SKELETON`/`VALUE_SKELETON`
  (formatbar.js): NOT dead — the harness imports them
  (`tests/test_serve_drafts_corruption.py`,
  `tests/test_editor_skeletons.py`, `tests/test_editor_refdes_buttons.py`).
  KEPT.
- `currentRevision`, `setOpenRevision` (app.js): genuinely dead
  (`openRevision` var stays, used at app.js:100). REMOVED.
- `itemsHref` (filters.js): genuinely dead (`filterQuery` has real
  importers). REMOVED.

## 5.2 — shared el() helper

All 12 copies of `el(tag, cls, text)` in serve/static were byte-identical
(md5 `ee870ac5987c823779383d10b41e897f`), textContent-only. Created
`dom.js` exporting one `el`, replaced each local copy with
`import { el } from './dom.js';` in the 12 consumers. No behavior change;
`dom.js` is comment-clean of `innerHTML` (test asserts on code, comments
stripped).

Registries all glob-based, no allowlist to update: serve `_static`
serves by extension (server.py), pyproject ships `serve/static/*`,
VSIX does not bundle static, built-site assets come from
`templates/taskpane/` + `templates/navis/` (no `el()` there),
`collect_static_assets` is project `site.assets:`, not serve static.

## Red-first tests (appended to tests/test_serve_static.py)

- `test_the_el_builder_is_shared_not_duplicated`: exactly one
  `el(` definition in serve/static, all 12 consumers import it.
- `test_the_shared_el_never_touches_innerHTML`: `el` source is
  textContent-only.

Red shown before the change (2 failed), green after (68 passed in file).

## Byte-identical proof

Normalized tree hashes (path prefixes stripped) before == after:
repo built site (45 files) `0beace99...5f`, generated-site fixture
(15 files) `79b6831f...26`. `refdes ls` / `refdes index` outputs
identical. (Repo build carries a pre-existing 1-error:
DEC-PWR-001 boundary — present on base too.)

## Real-browser pass (Puppeteer-core Chromium + playwright-core Firefox)

Fixture: 2 log items via `refdes keys adopt` (link targets must be keyed
— a keyless target gets a 422 by design), one literal navi marker, one
in a folded YAML scalar (mint refuses it → 'Minted 1...'). Driven
against worktree-src server (:8920) and main-checkout-src server
(:8921), fresh project copy per run. 15 steps: list rows, sidebar
facets, open item, title edit+save, body edit+save, navis open, mint,
archive, restore, format-bar bold, fence, save, links picker, save,
final structure.

- chromium: worktree 15/15, main 15/15, masked step-detail diff: none.
- firefox: worktree 15/15, main 15/15, masked step-detail diff: none.
- Final `items/logs.yaml` byte-identical between the two servers' runs;
  `.refdes/navis/` back to empty in both (archive→restore round-trip).

Drive gotchas (browser-side, not product): playwright's
`waitForFunction(fn, arg, options)` takes arg 2nd vs puppeteer 3rd — a
3-arg call fed firefox `{}` as the bound arg; fixed by node-side
polling. Panel rows rebuild on poller ticks, so puppeteer clicks on
captured nodes race detach — direct DOM `.click()` via evaluate.
Save settles = `.edit-status` 'saved' without `warn`; navis mint
bumps the file revision, so format-bar save hits the 409 conflict box —
the drive clicks 'Keep mine' and the save lands. All product behavior,
identical on both servers.

## Pre-existing quirk (NOT touched)

`list.js` `row()` builds `el('a', 'item-link', ...)` and never appends
it — list rows have no anchor. Present on main; out of scope here.

## Suite

Full: 5955 passed, 2 skipped (`pytest -q -n 4 --dist worksteal`,
absolute PYTHONPATH). Ruff on touched files only.

Status: COMPLETE.
