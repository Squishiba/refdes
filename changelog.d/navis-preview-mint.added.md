- On pages served by `refdes serve`, a Navis panel with N keyless rows now
  grows a **`Mint keys (N)`** button above the list: one click posts `{}`
  to `POST /api/navis/mint`, the server mints every keyless live marker it
  can (item files change only by the key splices), rebuilds, and the page
  reloads onto the keyed list; the reloaded page opens with a status line
  (`Minted K key(s).`, the refusal sentence for markers in bodies refdes
  will not mint into, or `Nothing to mint.`). Keyless rows keep no Archive
  button and carry the hint "No key yet -- use Mint keys"; a failed mint
  shows the server's message and re-arms the button; a `--no-write`
  refusal locks every panel action, Mint included. The published site's
  read-only panel is unchanged (slice M2 of the mint offer, following the
  M1 route, `changelog.d/serve-navis-mint.added.md`).
