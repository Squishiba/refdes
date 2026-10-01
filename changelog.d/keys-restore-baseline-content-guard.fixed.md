- `refdes keys restore` now refuses to move a recorded key onto an item
  the recorded history does not describe. Delete REQ-PWR-001, create an
  unrelated item under the same display id, and run the command the
  unknown-key diagnostic itself recommends: it was accepted, silently
  re-pointed every reference that named the old key at the new item, and
  left `0 errors`, exit 0 — with `refdes audit`'s `changed 1` line as the
  only trace, erased by the next release stamp. Where the most recent
  baseline recording the key shows a different title or a different
  content hash than the item the key is being moved onto, the restore is
  refused and names both sides, the baseline, and the way through:
  `refusing to move key 'k7f3m2q9x4a' onto REQ-PWR-001: baseline 'rev-a'
  records that key under 'REQ-PWR-001' with different content -- title:
  baseline 'Rail current', now 'Enclosure drop'; content hash: baseline
  'c7926b17234d6180', now 'edaa81a32f696859'. ... -- the same item,
  edited since that baseline was stamped -- pass --force.` The comparison
  uses the same hashing the baseline was stamped with, and an item's own
  key and display id are not part of its content hash, so restoring the
  *same* item's key — the ordinary recovery — is unaffected, as is every
  project whose baselines never recorded that key: no record means no
  comparison, not a refusal.
- `refdes keys restore --force` overrides that one refusal, for the case
  where the record and the item are the same item whose content legitimately
  moved since the stamp. It overrides nothing else the command refuses:
  a malformed key, a key owned by another item, a replacement key recorded
  in history, or a proposed project that would not build is still refused.
