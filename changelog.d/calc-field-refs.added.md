- A calc reference can name one of the target's declared fields: `Rds =
  DEC-001.$rds_on | mohm` reads the field's saved value (a plain quantity)
  in a fence line or an inline span. The read is the saved item, so it
  creates no dependency edge — `X.$field` inside `X` is legal, and the
  field's value is not part of the referring item's hash, so editing the
  field moves the computed result, not the referring item's content hash.
  Bare `ITEM.name` keeps resolving to the calc value, and warns when the
  target has a field of that name (empty, null, and list-valued fields
  included). Undeclared, empty, list-valued, and non-quantity field values
  are loud errors naming the field, as is a field spliced into larger
  arithmetic.
