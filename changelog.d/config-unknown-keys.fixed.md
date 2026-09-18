- **Every nested block of `refdes-project.yaml` and `refdes-schema.yaml` is
  validated.** A key the block does not recognise is now a configuration error
  naming the file, the block path, the key, the keys that block does take, and
  a did-you-mean when one is close — the shape the top-level settings and
  `release_gate:` already used:

  ```
  configuration error: refdes-project.yaml: site.titel is not valid -- site: takes assets, nav, out, pages, title, version. Did you mean 'title'?
  ```

  Validated: `site:`, `id:`, `history:`, `units:`, `standard:`, `boards.<name>`,
  `workspaces.<name>`, `imports:` entries, `equations.<name>`, `types.<name>`,
  `types.<name>.fields.<name>`, `types.<name>.body`, `types.<name>.links`,
  `link_types.<name>`, `field_sets.<name>`, and `include:`. Wrong types are
  reported the same way instead of crashing or quietly coercing: `site:`,
  `boards.<name>`, `types.<name>` and friends must be mappings, `imports:` and
  `site.nav:` must be lists, `id.width:` must be a whole number,
  `workspaces.<name>.shared:` and `link_types.<name>.trace:` must be true or
  false. A bare string where a list belongs is no longer split per character
  (`nav: index` used to mean `i, n, d, e, x`), a quoted `"no"` is no longer
  true, and `id.width: 4.5` is no longer 4.

  **A project carrying a typo that used to be ignored will now fail to load.**
  That is the point — the typo was a setting that silently was not applying —
  but it does mean `refdes check` can start failing on a config nobody touched.
  The message names the key to fix and, in most cases, what to fix it to.
  Projects whose config was already correct are unaffected, including
  `types.<name>: null` deletions, empty `boards:`/`workspaces:` entries, and
  projects with no `refdes-schema.yaml` at all. The bundled standard and its
  presets are not checked, so a standard shipped by a newer refdes still loads
  on an older one.
