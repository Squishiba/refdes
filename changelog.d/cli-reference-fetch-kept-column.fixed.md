- Docs: `docs/cli-reference.md` scoped the fetch `no copy` word to `skipped`
  rows. `cmd_fetch` decides it per row from the bytes on disk for every row
  it prints, `skipped` or freshly `fetched` (`src/refdes/cli.py:910-916` --
  the comment above the check: "the word has to be true of the bytes on disk
  now, not only of what the lockfile claims"). The paragraph now says the
  same: any row whose record keeps a copy reads `no copy` instead of `kept`
  when those bytes are not on disk, and a `skipped` row is the usual way to
  see it -- a skip downloads nothing and puts nothing back, while a real
  fetch rewrites the copy it lands.
