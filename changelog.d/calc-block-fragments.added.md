- A named calc block can be linked from prose: `[[DEC-PWR-001#calc:losses]]`
  links to that block's table on its owner's page, at the anchor naming gives
  it. `[[DEC-PWR-001#calc:losses|DEC-001's losses calculation]]` sets the link
  text. Like a `#field` fragment it links and never inlines, so it cannot go
  stale when the numbers move (docs/design/named-calc-blocks.md §5.3).
  The `calc:` prefix is required: field names are schema-declared and block
  names are author-chosen, and a bare `#losses` would have to be resolved by a
  precedence rule nobody reading the page can see. A miss is a warning, never
  an error — a broken prose link must not fail a build — and it names what the
  target does have: `[[DEC-PWR-001#calc:loess]]: DEC-PWR-001 has no calc block
  named 'loess' (it names: losses, supply).`, or, when the target's blocks are
  unnamed, `add id="..." to its fence to make this link work`. Renaming a
  block breaks links pointing at the old name loudly at the referring line; it
  breaks no arithmetic, because no arithmetic refers to blocks. A `#calc:`
  fragment on a `[[fig:...]]` or `[[cite:...]]` reference is the warning those
  forms already produce for any fragment — neither is addressed by fragment.
