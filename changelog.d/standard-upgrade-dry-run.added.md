- `refdes standard upgrade` accepts `--dry-run`: it prints the whole plan
  per version step — the item files that would be rewritten, the
  `standard.version:` bump, and the baselines and seals whose hashes would
  be carried forward — and writes nothing, so a multi-file rewrite on a
  stamped tree no longer has to be previewed by copying the tree by hand.
  A refusal the real run would raise refuses the same way under
  `--dry-run`.
