- An item with a `source()` calc line now hashes the locked `(path, key,
  value)` it used (part of `hash_format` 4, no new format): an accepted
  `refdes fetch --update` that moves a value marks the item changed, while
  drift alone, timestamps, or other keys in the same file do not. Items with
  no `source()` line hash exactly as before.
