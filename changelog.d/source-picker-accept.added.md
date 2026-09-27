- Accepting a picked source value now writes it, as the second slice of the
  source-value picker (`docs/design/editor-source-picker.md`, §11 Slice B).
  `POST /api/item/<ref>/edit` with `op: "set_body"` gains a `pin` field — one
  `{path, key, unit, name}` or a list of them — and that one request writes
  both the item and `.refdes/citations.yaml`, inside the existing per-project
  write lock. There is no new op name and no second write endpoint: a body
  naming an unpinned key is an item that does not build, and a pinned key no
  body names is dead state in a tracked file, so the two halves commit
  together or neither does. The request carries paths and keys and **never a
  value** — a `value` in the request is ignored, because the number comes from
  the Python reader reading the live file, and a second parser in the browser
  would be a second authority on what a CSV says.
  Everything the picker validated when it offered the key is validated again
  under the lock, against the server's copy of the item: the path is still one
  this item cites, the key is still there and still selectable (a row that
  became a duplicate between the proposal and the accept is refused by the
  row), the name is still free, the unit still checks out. The lockfile is
  then written — atomically, whole-file, in byte-for-byte the format
  `refdes fetch` writes, so the next fetch looks at a file accept produced and
  finds nothing to do — and only then is the candidate project loaded and put
  through the diagnostic gate. A gate refusal, a failed body write, or any
  failure in between restores the previous lockfile bytes; a project that had
  no lockfile at all is left with no lockfile.
  Accepting follows `refdes fetch`'s non-`--update` policy, which means a file
  whose bytes no longer match its pin is **refused**, with the exact
  `refdes fetch --update --path …` that accepts the change. Re-accepting a
  changed source value stays a deliberate act in a terminal where the
  `old -> new` diff is printed. A file with no record yet is different and is
  allowed: the hash and the value are pinned in one write, as fetch does. A
  key already pinned for the same file keeps its value — accepting one key
  never rewrites the others — and an accept that pins nothing new leaves the
  lockfile's bytes and mtime alone. A body that does not actually contain a
  `source()` call for the pair it asks to pin is refused, so no pin can be
  made for a line that does not exist; the check is the evaluator's own parse
  of the body, not a text match. Sealed, imported and `--no-write` refusals
  are the ones the edit route already gave, unchanged and with their existing
  wording. A successful accept answers with what it pinned
  (`{path, key, reader, value}`), so the panel can repeat the number back. The
  editor panel itself is the next slice.
