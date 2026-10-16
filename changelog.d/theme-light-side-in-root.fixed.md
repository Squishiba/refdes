- A theme colour token set in both `site: tokens:` palettes with different
  values now keeps its light value: it is emitted in the generated
  stylesheet's `:root` block, so light mode shows the theme's light colour
  instead of the shipped stylesheet's default. Dark mode is unchanged (the
  dark value still wins in the `prefers-color-scheme: dark` block and under
  `[data-theme="dark"]`). Built-in themes were the visible case: every
  built-in sets every colour token this way, so selecting e.g.
  `theme: paper` used to render the default palette in light mode.
