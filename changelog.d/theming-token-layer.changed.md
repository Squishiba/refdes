- No visible change. The generated site's stylesheet gained a design-token
  layer: the repeated literals finding 34 counted — font stacks, font sizes,
  font weights, spacing values and border radii — are now `var()` references
  to a single `:root` token block (`--sans`, `--text-*`, `--leading-body`,
  `--weight-*`, `--space-N` (exactly N px), `--radius-*`). Every existing
  colour token is untouched. This is the token-layer step of the theming
  plan, shipped as a provable no-op: `tests/test_style_tokens.py` resolves
  every `var()` back to its literal and asserts the resolved declarations
  match the pre-refactor stylesheet byte-for-value, so every page renders
  exactly as before. No themes, no `site:` keys, no new files in the output.
