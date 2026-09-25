- **`HASH_FORMAT` is 5: referenced image bytes are content.** Every local
  image an item's body references now contributes its resolved
  project-relative path and content digest to that item's content hash — the
  same digest already spliced into the published asset filename. Replacing an
  image's bytes therefore marks every item that references it changed, breaks
  the seal of a sealed entry that references it (`modified since it was
  sealed`), and shows up in `refdes audit`, instead of silently changing what
  a sealed or baselined record displays while its hash still verified. Items
  that reference no image have byte-identical hash payloads and are untouched
  by the bump, and baselines/seals recorded under earlier hash formats
  migrate by the usual carry-forward rule (an entry moves only when its
  content is provably unchanged under its own recorded definition); an image
  swap that predates an entry's first format-5 stamp or seal is undetectable
  and grandfathered, because the old record never stored an image digest.
  History snapshots are unchanged and still do not cover image bytes. URL
  images contribute nothing. Decides `docs/design/editor-image-upload.md`
  §15.6; details in `docs/change-tracking.md` and `docs/markdown.md`.
