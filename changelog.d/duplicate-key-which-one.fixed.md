- The duplicate-key diagnostic now says which of the two items is the
  original. `key 'k7f3m2q9x4a' on REQ-PWR-004 ... is already used by
  REQ-PWR-007 ...` used to end "Delete the key from one of them and rebuild —
  it will be re-minted", which is a coin flip: the two items are
  indistinguishable to the loader, and taking it on the original is not a build
  failure. A composite reference resolves on the key, which the last item in
  load order owns, so deleting the original's key moves every inbound reference
  to the copy and leaves `0 errors`, exit 0 — verified, along with a release
  then stamping a baseline over the mis-pointed references. The message now
  names the original's definition (the item that was there first, which is what
  existing references and recorded history mean) and two ways to find it:
  `git log -S'key: <KEY>' --oneline --reverse`, and whichever of the two
  display ids a baseline, seal file or membership manifest records the key
  under (`refdes audit` shows the stamp). `docs/troubleshooting.md`'s remedy
  for the same diagnostic was changed the same way, and `docs/design/keys.md`
  §6 Layer 2 now quotes the shipped message and explains why the message
  cannot pick a side. Message and docs only: no detection logic added, and the
  check, its severity, its file/line and its exit code are unchanged.
