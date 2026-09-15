- A hand-deleted `key:` line is now reported as `key deleted` instead of
  being silently re-minted during load and reported as the misleading
  `key changed`. Loading warns about the item, the build errors, and both
  messages name the old key, the record it came from (the latest baseline,
  a key-keyed seal file, or the membership manifest), and the two remedies:
  add `key: <old key>` back, or give the item a new display id if it really
  is a different item — after which a fresh key is minted for it. Nothing is
  written into the item in the meantime, so the evidence survives.
  `refdes keys adopt` refuses the same item rather than minting over it.
  The record holding the old key survives the build that reports the loss: a
  key-keyed membership entry for the item is never pruned or rewritten, and the
  seal verifier no longer adds its own `key changed since it was sealed`
  for the same item — the deleted-key report owns it — and the sealed entry is
  still never re-sealed over. Items with no key and no record anywhere are
  still minted silently.
