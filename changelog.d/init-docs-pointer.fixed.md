- `refdes init`'s candidate-parts pointer now names the published docs site
  instead of a repo-relative path. It read
  `docs/parts.md#candidate-parts-the-recommended-layout`, but `init` creates
  no `docs/` directory and the wheel ships no `.md` files at all
  (`[tool.setuptools.packages.find]` is scoped to `src/`, and the
  package-data list carries only templates, standards and serve static
  assets) -- so the one place the tool pointed a newcomer at the docs named a
  file that does not exist for them, in the project it had just created for
  them. It now prints
  `https://squishiba.github.io/refdes/parts.html#candidate-parts-the-recommended-layout`,
  which resolves for anyone, checkout or install. The `Documentation` URL in
  the package metadata moved to the same site.
