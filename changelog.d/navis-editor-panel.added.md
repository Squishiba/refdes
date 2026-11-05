- **The Navis panel in the browser editor.** The editor at `/edit/`
  gained a read-only Navis panel: a fixed `Navis (n)` toggle at the
  top-right opens the active Navis (6-character key, the source item's
  id as a link that navigates the editor to that item, the marker text)
  and a Show-all disclosure listing the archived ones, tagged
  `[archived]` by their snapshot text with the `marker text has changed
  since archived` note and the `marker not found` label, shaped like the
  published site's panel. It reads the served `GET /api/navis` rows —
  no client-side project facts — refetches when the editor's own
  rebuild signal fires and on every open, keeps the last good rows
  through a failed fetch, and Escape closes it. The panel offers no
  archive/restore actions; those stay `refdes navis` CLI commands.
  See `docs/browser-editor.md`.
