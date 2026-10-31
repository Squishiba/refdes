- Math docs: the offset-unit rule is now stated where the units are.
  `degC` is an offset unit, so a per-watt temperature written `42 K/W`
  cannot be multiplied by a power inside a `degC` expression (the
  message is the units library's own `Ambiguous operation with offset
  unit`); write the temperature rise in a `delta_` unit
  (`42 delta_degC/W`). Verified against `refdes check`.
