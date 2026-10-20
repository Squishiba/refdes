- `release_gate:` gained `inline_calc_results` (default
  `{release: true, revision: false}`): a stale inline-calc stored result in
  an editable item — the build's `inline calc Vout: stored result says X,
  now computes Y` warning — now fails `refdes release`, naming the item's
  display id (or surrogate key for an id-less continuation), the span, and
  the span's line. A build seal, or an unedited capture whose
  live content still matches its snapshot, is exempt and keeps its warning:
  the gate guards editable prose, never frozen text. Editing an item after
  capture restores editable text, so a stale span there is not exempt.
  Missing results and calc errors
  already failed the ordinary build floor, and `refdes revision` is
  unaffected. Turn it off per project with
  `release_gate: { inline_calc_results: { release: false } }`.
