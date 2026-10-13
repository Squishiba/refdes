- Checks: a `checks:` `against:` written as a bare surrogate key now gets the
  same diagnostic a structured link target gets, instead of the display-id
  one. `build.run_checks` gated its key checks on the composite separator
  alone, so `against: k7f3m2q9x4a` -- a key the author wrote (or kept) without
  its display half -- reported "which does not exist -- a typo, ... write the
  item's new id here", the remedy for a misspelled id, while the very same key
  a few lines away in `constrained_by:` reported "which no item declares ...
  `refdes keys restore`", the remedy for a lost key; a key corrupted by one
  upper-case character read as a typo there too. `against:` names a target
  exactly as a link does, and `docs/design/keys.md`'s Layer 3 promises one
  diagnostic for all three shapes, so the gate now recognises a key-shaped
  token the way `resolve_links` and the calc resolver already did. A bare
  display id that resolves to nothing keeps the old message: it never had a
  key, so `keys restore` has nothing to restore.
