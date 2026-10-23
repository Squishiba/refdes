- The docs site's vocabulary page showed the `citations` field's
  `[[cite:]]` syntax as a broken citation link (the docs renderer parsed it
  as a live reference to an empty citation id and warned). It is now emitted
  as a code span, so the page shows the syntax literally and `refdes build`
  on `docs-site/` is warning-free.
- `docs-site/refdes-project.yaml` no longer declares a `site.assets:`
  `images` directory that does not exist. It was added for a checked-in
  vocabulary diagram that a later change replaced with inline SVG, leaving
  the setting (and a build warning) behind.
