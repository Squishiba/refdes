- The inline-calc release gate now says why it fails closed on an unreadable
  history store. Docs promised it (`docs/math.md`, `docs/lifecycle.md`: the
  gate "fails closed and names the unreadable store"), but the gate printed a
  generic "history store unreadable" line *instead of* the offenders: a
  previously capture-exempt stale span disappeared from the list, and the
  author reading the row had no way to tell "the gate could not read the
  store" from "my capture expired" — the opposite of the truth. Now, when
  (and only when) the store cannot be read and at least one stale inline-calc
  span is in play, the rule's output opens with one line naming the cause —
  `stale inline-calc gate: cannot read the history store .refdes/history
  (<error text>) -- failing closed` — and the offenders follow, exactly as
  they read when the store is readable. The offenders themselves, which items
  fail, and the exit codes are unchanged; with a readable store, or with no
  stale spans, nothing new is printed.
