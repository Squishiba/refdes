- **`site: theme:` and `site: tokens:` — theming step 2a (finding 34).** A
  project can select a built-in theme and layer its own design-token overrides
  over it (`site: {tokens: {--accent: "#b3541e", --sans: Georgia, serif}}`). A
  theme is a flat list of `--token: value` pairs and nothing else: unknown token
  names are build errors with a *Did you mean* hint (CSS's own answer to a
  mistyped custom property is silence and a half-themed site), a value must be
  one plain CSS value — `;`, `{`, `}`, `<`, `@import`, `url(`, a comment opener
  or an escape is refused — and the verdict colours `--good`/`--bad`/`--warn`/
  `--claim` cannot be reassigned yet. Overrides are merged **over** the default
  theme, so an omitted token keeps its default rather than going unset, and are
  emitted as a generated `assets/theme.css` linked after `assets/style.css` and
  tracked in `.refdes-manifest.json` (remove the theme, the file goes away).
  With no theme configured no file is written and no `<link>` is emitted: an
  un-themed build is byte-for-byte what it was before theming existed, pinned by
  hashes captured from `origin/main`. Contrast checking, extra built-in themes,
  the docs-site gallery and editor theming are step 2b.
