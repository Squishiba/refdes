- The editor's source picker can now browse a cited XLSX. A cited `.xlsx`
  appears in the item's source list with `reader: "xlsx"`, and
  `GET /api/item/<ref>/sources/entries?path=` lists the workbook's defined
  names — workbook-scope names bare, sheet-scoped names qualified
  (`Sheet1!case_rise`, spelled exactly as `refdes fetch` must spell them),
  in scope order. The keys the listing offers are exactly the keys
  `extract()` accepts, through the same destination resolver and the same
  numeric grammar, so the picker cannot offer a value `fetch` would refuse;
  a name `fetch` would refuse (a range, an external reference, a blank,
  text, a formula with no cached value) is listed and marked with the
  reader's own words, never hidden. Hidden sheets are included and marked —
  `fetch` reads them. Merged ranges show what `fetch` sees: the top-left
  cell is the value, the cells inside the range are blank. Reads are
  bounded by the CSV listing's shared caps (5000 names, 1 MiB, the byte cap
  enforced before the workbook is opened) and never write the workbook; a
  corrupt, encrypted (password-protected) or oversized workbook is refused
  with a clear reason and no traceback. No absolute server path leaves the
  process. Uses the existing optional `refdes[xlsx]` extra — no new
  dependency; with it missing, the picker names the install command.
  `refdes fetch --update` accepts a picked key's composed line end to end
  (`docs/design/calc-sources.md` §11 Q2).
