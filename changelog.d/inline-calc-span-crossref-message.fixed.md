- A cross-item reference used *only* in an inline calc span no longer gets
  its target blamed for a value it defines. The build's cross-item evaluation
  order reads dependency edges from calc fence lines only, so such a span can
  run before its target is evaluated — a known gap — and the error said
  `DEC-001 does not define 'V_in' (it defines no calc values)` about an item
  whose fence defines `V_in = 2 V`, sending the author to edit the wrong file.
  The message now names the ordering gap at the span's line and points at the
  fix: keep the reference in a calc fence.
