- `[[ID#field]]` is now a reference: it links to that field's row on the
  target item's page, the way `[[fig:id]]` links to a figure. `[[ID#field|label]]`
  sets the link text; without a label the link reads `ID#field`. It is a link,
  not a substitution — the field's value is never copied into your prose. The
  field must be declared on the target's type: an undeclared one warns, naming
  the item, the field, and the type, and renders in red like any other
  unresolved reference. A field declared but empty on that item links fine: it
  lands on a collapsed empty row in the fields table. A field whose content is
  shown in its own section — `options`, `checks`, a citations field — lands on
  that section.
  Citations are not addressable this way — a fragment reaches the whole
  `datasheets:` list, not one entry — and `revise.py` does not yet treat
  fragments as stale-able prose. See [cross-references](links.md).
