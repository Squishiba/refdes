- A citation's `vendor:` field is now `keep_copy:` — the old name read as
  "the company that makes the part" next to `part_number:`, when it meant
  "keep a local copy of the fetched bytes" (vocabulary-review.md S1; owner
  approved 2026-09-20). The lockfile key `vendored:` is now `kept_copy:`
  (past tense: a resolved fact beside `fetched`, not the authored intent
  flag), the on-disk directory `.refdes/vendor/` is now `.refdes/copies/`,
  and the release-gate rule `missing_vendored_copies` is now
  `missing_kept_copies`. No old spelling passes silently: `vendor:` in a
  citation entry fails validation with a message naming `keep_copy:`, a
  `vendored:` lockfile record and a stranded `.refdes/vendor/` directory
  each produce a loud diagnostic instead of quietly downgrading copied
  citations to hash-only. `refdes standard upgrade --to 3` rewrites
  `vendor:` inside citation entries alongside `url:` → `path:` — the field
  shipped under hardware@2 (v0.3.0–v0.5.0), so released projects need the
  rewrite. Projects that configure the renamed rule must update the key in
  `refdes-project.yaml`; the old key errors with the rename spelled out.
