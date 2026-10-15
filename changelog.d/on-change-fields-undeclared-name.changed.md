- A `fields:` entry in an item's `on_change:` mapping that names a field
  the item's type does not declare used to load clean and do nothing. It
  is now an error naming the field and the type's declared fields, and
  the entry is dropped — the same posture as the existing
  `on_change: unknown key` diagnostic.
