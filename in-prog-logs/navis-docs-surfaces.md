# navis-docs-surfaces (N5f)

Docs-only slice: bring `docs/navis.md` up to date with the two browser
surfaces that merged after it (#420 preview actions, #421/#422 editor
panel). No src changes.

## Read

`docs/navis.md`, `docs/browser-editor.md` (Navis panel section, added by
#421/#422), `docs/output.md` (site-panel interactive mention), and the code:
`navis-preview.js`, `navis-panel.js`, `serve/navis_write.py`, `navis_ops.py`.
Confirmed serve's `read_only` flag: `cli.cmd_serve` passes
`read_only=args.no_write`, so `refdes --no-write serve` gates POST to 403.

## Added (only what was verified by running)

- `## The served preview panel`: keyed active row -> Archive; keyed archived
  row in Show-all -> enabled Restore (ships disabled on the published page);
  click posts the full key, server rebuilds, page reloads. Keyless row ->
  no button (served load mints no key). Orphan -> Restore disabled with the
  hand-restore hint. `--no-write` -> panel lists (GET 200), click refused
  (POST 403) with the exact `refused` message; all actions disable.
- `## In the editor`: top-right toggle, Show all, Archive/Restore, inline
  error, 403 session lockout; the one difference (editor refreshes in place,
  so an unsaved draft outlives the action) stated as observed in
  Chromium/Firefox 2026-11-05, not a guarantee. Links to
  browser-editor.md#navis-panel rather than duplicating.
- Bridge sentence at the end of the published-site panel section.

## False-sentence check

Grepped for `read-only`, `only the CLI`/`CLI only`, `cannot archive`. The
`read-only` hits (lines 220/225/229) all describe the **published** page,
which output.md:322 confirms stays read-only — not false, left in place. No
CLI-only wording to fix.

## Verification

Built a throwaway Navis project under `.scratch/n5f/proj` (config split into
refdes-project.yaml + refdes-schema.yaml; 1 active keyed, 1 archived+changed,
1 orphan), matching test_navis_site_panel._navi_project. Started
`refdes serve` on 8805 (writable) and `refdes --no-write serve` on 8806.
Quoted real responses: GET /api/navis (200), POST archive (200 ok, counts
active drops 1->0), POST restore (200 ok), --no-write POST (403 refused,
exact message), --no-write GET (200). Servers stopped by PID (cwd checked).

Tests: `test_docs_anchors.py` + `test_config_unknown_keys.py` (loads
docs-site) pass. CI docs build (`refdes build` in docs-site) clean (0 errors,
0 warnings); generated navis.html carries id="the-served-preview-panel" /
id="in-the-editor" and the in-page link resolves.

## Evidence not produced by this worker

The draft-survival claim ("an open item draft with unsaved edits outlives
the action, observed in Chromium and Firefox on 2026-11-05") was **not run by
this worker**. The orchestrator ran it against the merged-PR head (probe
`.scratch/pptr422/probe.mjs` + `extra.mjs`): with the item editor open and
text typed unsaved, Archive then Restore were clicked in the panel; the
app's `refdes:rebuilt` event fired once per action; the textarea kept the
typed text in both Chromium and Firefox, and a later Save still wrote it.
The navis.md sentence stays as-is (relaying that observation, not a
guarantee); this log records the provenance. I did not drive a browser.

## Status

Complete. Added ~64 doc lines.
