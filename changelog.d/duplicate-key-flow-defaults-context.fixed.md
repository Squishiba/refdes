- A repeated top-level key in an item list file is no longer blamed on the
  file's `defaults:` when that block is written in flow style. With
  `defaults: { type: requirement }` on a file's first line, the defaults
  mapping and the document's own top-level mapping both *start* on that
  line, and the duplicate-key diagnostic decided which mapping a repeat
  belonged to by comparing start lines -- so a second `items:` printed
  `(in this file's defaults:, so every item here inherited it)`, pointing
  the author at a line with no such repeat. The attribution is now
  structural: each duplicate record carries which mapping it was collected
  from (the document's root, the mapping a top-level `defaults:` names),
  so a repeat inside an inline-flow `defaults:` keeps the clause it has
  always had, and a repeat of a top-level key never gains it. Block-style
  `defaults:` files, item-local repeats, line numbers, and the
  survivor-chaining for lost `id:`s are unchanged.
