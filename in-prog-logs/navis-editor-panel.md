# navis-editor-panel (slice N5d-1)

Goal: read-only Navis panel in the browser editor (list + Show-all,
no archive/restore actions), data from GET /api/navis, no second
poller, createElement/textContent only.

## What was built

- `src/refdes/serve/static/navis-panel.js` (new): `mountNavisPanel(root,
  apiFn = api)` — fixed `Navis (N)` toggle (aria-expanded), panel of the
  active rows (key6 mono span, item id linked `#/items/<ID>` via the
  display id the API row carries, text), `Show all (N)` `<details>` with
  every row like the site panel: `[archived]` tag, snapshot text the API
  returns for archived rows, `marker not found (<file>)` orphan label,
  `marker text has changed since archived` note. Empty: `No active
  Navis.` Refresh: the shell's one project-change signal — app.js's
  poller dispatches `refdes:rebuilt` on a serial move (a save lands
  there on the next poll), the panel re-renders/re-fetches on it and
  re-fetches on each open. A failed fetch keeps the last good rows;
  with none, the open panel says `Navis unavailable`.
- `app.js`: imports the module, mounts it once (`mountNavisPanel(
  document.body, api)`), before the boot poll. No second poller.
- `style.css`: editor's own tokens; toggle fixed top 52/right 12 (clear
  of the topbar's git badge, which shares the topbar row), panel under
  it with max-height min(60vh, 32rem) + overflow, z-index 10/11 (the
  editor's own popovers are z 3–5; the panel is the topmost surface,
  and the save bar check below is the real constraint).
- No Python change: the static surface serves by extension
  (`_STATIC_TYPES`, server.py:53) — `.js` needs no allow-list entry.

## Tests (red-first)

`tests/test_editor_navis_panel.py` (new): node harness (FakeNode DOM,
window as EventTarget — same posture as test_editor_link_undo.py /
test_editor_live_calc.py) drives the REAL served module: toggle count,
open/close aria, active vs archived/orphan/changed rows, link target
for item vs null, hostile text literal (no SCRIPT node), empty project,
refresh on `refdes:rebuilt`, re-fetch on open, fetch failure keeps rows
/ `Navis unavailable` with none; Escape focus-return is pinned. Plus
real-EditorApp test that `/edit/static/navis-panel.js` serves 200 with
text/javascript and contains the mount, and app.js wiring/static pins.
All 4 red first (module missing), green after. test_serve_static.py
(import graph, CSP scans, ES-parse) passes unchanged (129 passed with
navis_read/security).

One harness fix during red-first: href is a property on a real `<a>`,
read it as one (list.js sets link.href as a property).

## Real browsers (port 8779, own fixture)

`.scratch/pptr/` (recipe copied from pptr388): fixture = active marker
(NOTE-001), hostile active marker, archived-and-edited (changed),
archived-then-deleted (orphan). Chromium (puppeteer-core, /usr/bin/
chromium) and Firefox (playwright-core) scripts share
`navis_cases.mjs`. Per browser, per case, all PASS: openClose (label
`Navis (2)`, aria, hidden), rows (2 active, Show all (4), snapshot text
shown and live edited text not, tag/notes, key6, href `#/items/
NOTE-001`), hostile (literal, no script element), escape (closes,
focus to toggle), linkNav (hash + item view NOTE-001 Alpha),
saveBar1200 (elementFromPoint on the Save button hits the button, not
the panel, panel open, bar scrolled into view), fits375 (panel rect
inside 375×640), archiveMovesRow (CLI `navis archive` of the active
key → re-open: `Navis (1)`, alpha out of the active list, `[archived]`
in Show-all, count 4). First run's archive is persistent project state:
`navis restore` the key between runs (the drivers archive on each run).

## Status

Implemented, browser-verified in both browsers, docs + changelog
fragments written. Full-suite run deferred by the profiler pause.
