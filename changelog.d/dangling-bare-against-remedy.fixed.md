- A `checks: against:` target that resolves to nothing now names the same remedy
  a structured link does. `against:` is the `checks:` counterpart of a
  structured link target — the same `DISPLAY-ID@key` expansion on a writable
  load, the same refresh-on-rename rule, the same `resolve_link_target` — so
  the same dead end existed one branch away: with the bound renamed by hand
  while this `against:` was still bare, the entry carries no key to follow the
  rename, and none of `keys restore` (no key was lost), `former-ids` (prose
  references only) or `revise` (no single-item rename) reach it. `check against
  'BND-PWR-404', which does not exist` now leads with the three ordinary
  explanations and spends one clause on the remedy — write the item's new id
  here — then points at Troubleshooting's `## Links` by its published URL. The
  two texts now come from one helper, worded about whatever carries the bare
  text, so they cannot drift. The structured-link message is unchanged
  character for character; this one stays one or two sentences, because it fires
  on every typo. Message and docs only: same error, same severity, same
  file/line, same counts, same exit code.