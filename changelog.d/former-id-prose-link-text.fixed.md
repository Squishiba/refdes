- A prose mention of a retired id rendered as `REQ-PWR-001 (formerly
  REQ-PWR-001)` — the link text repeated the marker, which reads as a
  self-contradiction and left the destination named nowhere in the sentence.
  The link text is now the item's *current* id and the marker keeps naming
  the former one, so the sentence reads `NEED-PWR-001 (formerly
  REQ-PWR-001)` and says where the old id landed, as the `former_ids:`
  section of `docs/ids.md` describes. An explicit `[[old-id|label]]` is
  unchanged: the author's label is still the link text, with the marker
  after it. Structured link fields (`refines:` and friends) never fell back
  to former ids and still don't.