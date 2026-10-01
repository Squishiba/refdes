- A structured reference that resolves to nothing now names a remedy when the
  reason is a hand rename. `satisfies points at 'REQ-PWR-009', which does not
  exist` was a dead end in that case: the reference is still bare, so it
  carries no key to follow the rename, and none of the recovery commands
  apply — `keys restore` has no lost key to restore, and `former_ids:`
  resolves prose references only, never a structured link (verified: recording
  `former_ids: [REQ-PWR-001]` onto the renamed item leaves the error exactly
  as it was). The message now says to write the item's new display id into the
  reference, notes that a prefix-wide rename is what `refdes revise` is for
  because it expands bare references before it renames, and points at the
  Troubleshooting page's `## Links` section via the published docs URL rather
  than a repo-relative path. That section's entry for the diagnostic gained the
  same remedy, with the three commands that do not apply and why.
