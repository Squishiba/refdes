- Entry summaries read as the heading of their entry. `.tl-summary` was 15px —
  the base body size — sitting 1px above the 14px entry body, so an entry opened
  as a wall of near-identical text. It is now 17.5px semibold with 1.3 leading,
  which puts it under the 18px `h2` it lives beneath and clearly above the body
  and the 12.5px date/id/author line. Body text is unchanged at 14px. The rule
  sets no colour, so it keeps inheriting `--fg` and needs no dark-mode
  counterpart, and no `@media print` or narrow-width rule touches it — the same
  hierarchy on paper, on a phone and in the dark palette. Applies to the design
  log, an item page's own timeline and a thread panel alike.
