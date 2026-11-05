- On pages served by `refdes serve`, the Navis panel is now interactive:
  each active row gains an **Archive** button and each archived row's
  **Restore** button is enabled, acting through the editor API and
  reloading the page on success (slice N5c of the editor design,
  `docs/design/editor-vscode-adapter.md` §11). The published site's
  read-only panel is unchanged; the new `navis-preview.js` module loads
  only in the served preview, beside the existing reload probe. A
  `--no-write` server shows its refusal in the panel, an archived Navi
  whose marker was hand-deleted keeps its restore disabled with the
  hand-restore hint, and rows are mapped to the API positionally, so a
  stale page aborts silently and lets the existing poll reload it.
