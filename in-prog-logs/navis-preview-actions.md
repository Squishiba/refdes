# N5c: Archive/Restore buttons on the preview Navis panel

Goal: make the served preview page's Navis panel interactive through
`GET /api/navis` + `POST /api/navis/archive|restore`, without touching
published output. Slice N5c of the panel design
(in-prog-logs/navis-design-20261025.md §11).

## What landed

- `src/refdes/serve/static/navis-preview.js` — new module exporting
  `wireNavisPanel(doc, apiFn)`. Fetches `/api/navis` once; adds an
  Archive button to each active top-list row; enables Show-all Restore
  buttons; maps rows to the API positionally (counts must agree, else
  abort silently); POSTs the full key; reloads on 200; on failure shows
  one inline `role=alert` paragraph (textContent only) and re-enables
  the clicked button; on 403 disables every action.
- `preview.js` — imports the module and calls `wireNavisPanel()` next to
  `wireValueToggles()`.
- `bar.css` — Archive pill styled from the published restore pill's
  metrics; restore-enabled cursor; inline error color; print-hidden.
- `tests/test_navis_preview_actions.py` — Node harness running the real
  module against a fake DOM (10 scenarios) + one real-EditorApp delivery
  test. Red-first confirmed (module-not-found), then green.
- `docs/output.md` — served-interactivity paragraph in The Navis panel.
- `changelog.d/navis-preview-actions.added.md`.

## Difficulties

- The harness fake DOM hid a real-DOM bug: `querySelectorAll` returns a
  NodeList with no `.find`, so the module threw in Chromium (pageerror)
  while the harness passed. Caught only by the real-browser run; fixed
  with `Array.from`. Lesson: the harness needs the real interface, not a
  convenience.
- The browser fixture needed `refdes keys adopt` before `navis archive`
  (hand-minted keys are refused until registered) and `types:` must live
  in `refdes-schema.yaml` under hardware@3.
- Playwright's `waitForSelector` defaults to *visible*; the panel is
  closed, so the button is attached-but-hidden — Chromium driver took
  the default, Firefox needed `state: 'attached'`.

## Evidence

- Touched files green: test_navis_preview_actions (2), test_serve_static
  (64), test_navis_site_panel (15, differential: published output
  unchanged), test_serve_preview_values (12), test_serve_preview_reload
  + navis_read + navis_write (78). ruff clean on the touched test.
- Real browsers (`.scratch/pptr/`, port 8778, Chromium + Playwright
  Firefox), fixture with active/archived/changed/orphan rows plus one
  hostile marker (`<img src=x onerror=alert(1)>HOSTILE-TEXT`):
  - Archive click: serial moves (1→2 / 3→4), row leaves the active list
    and appears under Show all as [archived].
  - Restore click: serial moves (2→3 / 4→5), row is back in the active
    list.
  - `.refdes/navis` listing before the run and after the round-trips is
    unchanged (two records), i.e. the writes are the real store.
  - Orphan row: restore stays disabled, title names hand-restore.
  - `--no-write`: click shows the refusal as a role=alert, all actions
    disable, serial unchanged, project tree hash identical before/after
    (840f8ccc..., excluding url.txt/.refdes-write.lock).
  - Panel/bar: intersection area 0 (panel top-right, bar bottom-right).
  - Hostile text literal in the panel, 0 img elements, 0 dialogs fired.

## Status

Code, tests, docs complete; browser evidence complete. NOT yet done:
full suite (paused for profiler run), push, PR.

## Review round 1 (PR #420)

Chunk 2 approved; chunk 1 asked for three fixes, all in one follow-up:
F1 restored the `wireValueToggles();` call my diff had replaced in
preview.js (regression: the W3 toggle was dead on served pages) with a
new red-first entry-point test that runs the real preview.js top level,
plus a real-browser check (Chromium + Firefox, proj7 page with a calc
table AND the Navis panel: toggle hides/shows the badge, panel wiring
alive); F2 corrected the false `editor-vscode-adapter.md §11` citation
to `in-prog-logs/navis-design-20261025.md` §11 in all four places
(changelog, module header, bar.css, this log); F3 removed the dead
`@media print` rule (navis.css already prints-hides the whole panel).
