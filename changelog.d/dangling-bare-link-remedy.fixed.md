- A structured reference that resolves to nothing now names a remedy when the
  reason is a hand rename. `satisfies points at 'REQ-PWR-009', which does not
  exist` was a dead end in that case: the reference is still bare, so it
  carries no key to follow the rename, and none of the recovery commands
  apply — `keys restore` has no lost key to restore, and `former_ids:`
  resolves prose references only, never a structured link (verified: recording
  `former_ids: [REQ-PWR-001]` onto the renamed item leaves the error exactly
  as it was). The message now leads with the three ordinary explanations — a
  typo, a deleted item, or a hand rename — and spends one clause on the
  remedy: write the item's new id into the reference. It stays one or two
  sentences, because it fires for every typo; the long form (which commands
  do *not* apply, and why a hand rename is safe once a writable load has run)
  is in Troubleshooting's `## Links` section, which the message links by its
  published URL rather than a repo-relative path. That section also corrects a
  self-contradiction: hand-editing an item's `id:` is not what breaks
  references. What breaks them is hand-editing an `id:` while a reference to
  it is still bare, so run any `refdes check` *without* `--no-write` before
  renaming and the references follow on their own.
