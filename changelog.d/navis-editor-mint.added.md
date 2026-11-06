- The browser editor's Navis panel gained a **Mint keys (N)** button.
  When the panel has any unkeyed rows, the pill sits at the top; it
  writes a key into every unkeyed marker in your item files
  (`POST /api/navis/mint`), refreshes the panel in place (no reload), and
  reports what it minted and any marker it refused to key. The mint edits
  item files, so an open unsaved draft meets the conflict screen at Save
  rather than being overwritten. A keyless row names the reason in its
  key slot, and a `--no-write` server disables the mint along with the
  other actions. (slice M3)
