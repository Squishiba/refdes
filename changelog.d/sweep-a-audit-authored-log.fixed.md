- Fix: `refdes audit` on a project pinned to a pre-v3 standard printed an
  item's `on_change:` override as `timeline` in the overrides section while
  the schema section of the same report printed the standard's own `log` —
  one report, two spellings of the same mode, read as two modes. The
  override section now prints the spelling the file carries (`log` on a
  pre-v3 pin, the authored spelling of a canonicalised v3 override); the
  canonical `timeline` stays on the parsed override, so behaviour is
  unchanged. (#196 review c1)
