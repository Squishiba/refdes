- Inline-calc stale-result warnings: a computed value whose rounded
  display already reads as stale (stored `4.3 W`, computed `4.4 W`) now
  shows the rounded display, not the raw binary float the value carries
  (`4.3999999999999995 W`). The previous rule widened to the raw value on
  a mere edge touch between the displayed value's reading window and the
  stored literal's; it now fires only when a reader who reads the
  displayed value at the stored place would accept it as matching (the
  run-12 F12-4 case), and that raw value is normalised to a readable
  number of figures (`3.4495`, not `3.4495000000000005`).
