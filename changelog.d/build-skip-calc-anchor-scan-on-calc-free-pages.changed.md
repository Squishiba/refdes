- `refdes build` and the `refdes serve` preview now skip the calc-anchor
  uniqueness pass on pages that contain no calc tables, which is the common
  case: the pass's whole-page id-inventory scan is the dominant render cost on
  a calc-free site, and the skip is guarded by the literal the rename regex
  itself must match. Measured on a 200-item generated site (load ~8, median of
  5): render 450 ms → 230 ms; the full CLI build 1310 ms → 850 ms. Output is
  byte-identical (repo site, docs-site, and the generated site, diffed tree
  against the pre-change build).
