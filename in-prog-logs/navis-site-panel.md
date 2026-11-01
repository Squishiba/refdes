# Navis slice 4a: read-only site panel

Task: emit a read-only Navis panel from `refdes build` when the project
has at least one Navi (active marker or archive record), slice 4a of
`in-prog-logs/navis-design-20261025.md` (§13 item 4). Branch
`feat/navis-site-panel`, base `d9719a9`.

## What landed

- `src/refdes/navis_panel.py` (87 lines): `panel_model(project, rows)`
  presents one render's `navis.projection` rows — `key6`, text
  (archived rows show the snapshot, §9), the §10 source-item link,
  `archived`/`changed`/`orphan` flags. None = no panel, no asset, no
  link.
- `render.py` (+52): the projection is hoisted in `render_site`
  (gated on `project.items`, the C6 reason) and handed to `items_json`
  as `navis=`, one projection per render (PR #197 P4 rule);
  `navis_assets` global gates the asset; `NAVIS_ASSET_NAMES` joins the
  reserved set in `_copy_project_assets` exactly when the panel emits;
  `_write_navis_assets` mirrors `_write_taskpane_assets`.
- `base.html.j2` (+43): `<details>` panel, top-right, Show-all
  disclosure, restore `<button disabled>` with the CLI hint. CSS only
  in `templates/navis/navis.css` (+115, z-index 65 per §11), no JS.
  `pyproject.toml`: `templates/navis/*` package-data glob (the
  test_package_data guard caught the omission).
- `tests/test_navis_site_panel.py` (15 tests, red-first: 9 failed
  pre-implementation): panel on index+item pages, snapshot-not-live
  text, changed note, orphan label, active→archived order, restore
  disabled, asset emit/link/manifest, reserved asset name, no-JS,
  no-Navi gate, one-projection counter, and the `origin/main`
  differential (byte-identical `_site`, cold and warm `.refdes/`).

## Findings on the way

- The link resolution had to be display-id-first for scanned rows
  (the row carries the current id, §9 "panel link with no record
  write") with the key lookup as the fallback for orphan rows: an
  in-process render of an *edited* item has no minted key, and
  key-only lookup loses the archived row's link on every changed-text
  row.
- Chromium (static build, keys minted by the writable build) caught a
  real template bug the pytest fixture had smoothed over: an orphan
  whose record key resolves showed the link and lost the §9 "marker
  not found" label (`{% if %}...{% elif %}` trade). The fixture now
  hand-deletes only the marker line (a real author edit preserves
  front-matter), and a regression test pins label+link coexisting.
- Escape-to-close (§11) needs JS (`<details>` has no native Escape
  handling); slice 4a ships the no-JS panel — Enter/Space toggle per
  the slice's "prefer `<details>`" constraint. Flagged for slice 5
  where the panel refresh machinery ships JS.

## Verification

- Red-first run: 9 failed / 5 gate-guards passed; green: 15 passed.
- Neighbour suites (navis*, render_assets, task_pane,
  threads_render, package_data): 552 passed.
- Full suite: 5641 passed, 2 skipped, 1 failed — the failure is
  `test_package_data`'s glob guard on the new template dir, fixed by
  the pyproject glob; re-run of the guard: passed.
- Browser, Chromium + Firefox (real, headless), served over
  `http://127.0.0.1:8760` from a scratch project (1 active, 1 archived
  with edited marker text, 1 archived with hand-deleted marker, a
  `follows:` pair so the task pane exists): 18/18 per browser — panel
  visible on index + item page, active-first order, snapshot shown
  (live text absent), changed note, orphan label, restore disabled,
  panel/task-pane rects do not intersect, `<details>` opens/closes
  with the keyboard.
- ruff: clean on the touched files (the render.py SIM103 finding is
  pre-existing, in untouched code).

Finished: yes.
