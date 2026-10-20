- `release_gate:` gained `inline_calc_results` (default
  `{release: true, revision: false}`): a stale inline-calc stored result in
  an editable item — the build's `inline calc Vout: stored result says X,
  now computes Y` warning — now fails `refdes release`, naming the item's
  display id (for an id-less continuation, its surrogate key when one has been
  minted, otherwise the warning's file and line), the span, and
  the warning's reported source line (the span's line in Markdown, falling
  back to the item's entry line for a list-file `body:` key). A build seal,
  or an unedited capture whose
  live content still matches its snapshot, is exempt and keeps its warning:
  the gate guards editable prose, never frozen text. The capture exemption
  follows the captured text, not upstream values that move later. Editing an
  item after capture restores editable text, so a stale span there is not
  exempt. With an editable, unsealed stale span in play, an unreadable history
  store fails the release gate closed and names the store.
  Missing results and calc errors
  already failed the ordinary build floor, and `refdes revision` is
  unaffected. Turn it off per project with
  `release_gate: { inline_calc_results: { release: false } }`.
