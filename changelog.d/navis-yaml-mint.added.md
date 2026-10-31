- `navis` key minting (#390, slice 2b): a keyless `<!--navi: …-->` marker
  in a YAML list file's `body:` scalar now gets its key minted, where the
  marker's bytes are exact file bytes — literal block scalars (`body: |`,
  any chomping/indent indicator) and single-line quoted scalars
  (`body: "..."` / `body: '...'`, escapes preserved). The mint splices the
  key into the raw file at the marker's position, re-parses the result,
  and refuses the whole file if the re-parse moves anything. Shapes where
  a marker's bytes are not file bytes — folded (`>`), plain, multi-line
  quoted, flow style, a `body:` supplied by a merge key (`<<:`) or
  `defaults:`, an alias-shared body — keep the previous posture: warning,
  bytes untouched, marker lists keyless. A legacy body field a standard
  renamed into `body:` (`text:` on a requirement/bound, `method:` on a
  test) is the item's body and mints the same. The re-parse gate compares
  only entries carrying their own `body:` key, so a `defaults:`-bodied
  sibling never blocks a mint elsewhere in the file.
