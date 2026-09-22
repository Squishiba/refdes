- A `{{compare}}` block renders a candidate-comparison table on a page:
  `{{compare type="component" against="BND-PWR-011, BND-PWR-012"
  columns="part_number, status, calc:I_out, calc:I_q"}}` lists this
  project's own items of that type — ID-ascending, always — with one
  column per bound showing the item's recorded check outcome (`pass +88%`,
  `fail −33%`, or an em dash when nothing was recorded). The block only
  reads checks the build already evaluated; it never evaluates a bound
  against an item itself, so a value with no `checks:` entry shows the em
  dash rather than a computed verdict. Optional filters: `board=`,
  `status=`, `subtypes=`, `tag=`. A bound no row in the selection checks
  against warns, naming the bound and the page, and an empty selection
  renders a paragraph instead of a table. The block is display-only: it
  is never hashed, never sealed, and `build --no-write` produces
  byte-identical output. (docs/design/candidate-parts.md §3)
