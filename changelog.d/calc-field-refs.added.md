- A calc reference can name one of the target's declared fields: `Rds =
  DEC-001.$rds_on | mohm` reads the field's saved value (a quantity) in a
  fence line or an inline span. The read is the saved item, so it creates no
  dependency edge — `X.$field` inside `X` is legal, and field values never
  enter any hash, so editing the field moves the computed result, not the
  referring item's content hash. Bare `ITEM.name` keeps resolving to the
  calc value, and warns when a field of that name also exists. Undeclared,
  empty, list-valued, and non-quantity field values are loud errors naming
  the field, as is a field spliced into larger arithmetic.
