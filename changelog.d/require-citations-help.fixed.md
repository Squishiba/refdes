- `refdes build --require-citations --help` now lists every diagnostic the
  flag promotes (unpinned citation, missing cache blob, a local citation
  changed since pinned, a `SOURCE FILE CHANGED` source pin, and an
  unresolvable `section:`/`page:`) and notes which are unaffected; the help
  named only the first two. No behavior changed.
