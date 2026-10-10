- **A new link verb, `follows` (inverse `followed_by`)**, declared on the
  merged `log` type and restricted to `[log]` targets: an entry names the
  earlier entry it continues, and a thread is the connected chain walked
  from those edges — no container, and no head marker, because an entry
  with no `follows:` is a head. `trace: false`, like the `records:` verb
  it replaces: a thread is narrative continuity, not a traceability edge.
  A bare `follows:` target is chain-aware — a writable load freezes it to
  the current tip of the referenced entry's thread and captures that
  predecessor's snapshot into `.refdes/history/` (living-notes phase H2)
  — and a frozen edge then gets the ordinary `DISPLAY-ID@key` composite
  and stale-label refresh every structured link gets. The standard now
  declares the link; the thread conclusion and timeline pages remain
  later phases of the threads plan.
