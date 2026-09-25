- A `{{calcblock}}` block renders one named calc block's rows on a narrative
  page: `{{calcblock item="DEC-PWR-001" block="losses"}}` prints the same
  table the owner's own page prints — expression, result, bounds, unit
  assertion, comment, anchor and caption — under a caption line naming the
  owning item (linked) and the block. It reads the rows the build already
  computed (`item.calcs`, tagged by `CalcLine.block`) and never evaluates
  anything: a row whose expression would fail today still renders exactly as
  the owner's page renders it, error row included, because the failure is the
  owner's and the build already reported it at the owner's line. One directive
  renders one block — there is no `all=`, no `board=`/`tag=` narrowing, and no
  render-everything mode, so two blocks on one page is two directives. Local
  items only: an imported item is refused with an error pointing at the
  upstream project's own page. Errors are named, never silent — an unknown
  block name lists the names the item does have, an item that computes nothing
  says so, and the parameter set is closed (`block`, `item`). The block is
  display-only: it is never hashed, never sealed, and `build --no-write`
  produces byte-identical output. (docs/design/named-calc-blocks.md Phase 3)
