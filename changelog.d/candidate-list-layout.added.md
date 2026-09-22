- **A dead `status:` default now warns instead of passing silently.**
  A list or Markdown item file whose `defaults:` declares a `status` value
  no item in the file actually carries — every entry's own value won, or no
  entry has been written yet — is dead configuration, and gets a
  project-suppressible warning naming the fix (set an item's status, or
  drop the `status:` key from `defaults:`). The warning is entirely
  content-derived: nothing about the file's name or location is read, so
  renaming or reorganizing a file changes nothing that fires.
- **`refdes new <type> --list` prints a list-file skeleton.** One
  `defaults:` block carrying the type and the status field's declared
  default (omitted when the type declares no status field), then one empty
  entry — the layout recommended in `docs/parts.md` for a board's
  candidate shortlist. It prints the mapping form every list file must
  have, writes nothing (so redirecting it into place and backing it with
  `--no-write` are both safe), and `refdes init`'s closing message now
  points at that layout section.