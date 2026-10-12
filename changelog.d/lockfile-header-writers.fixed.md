- The citation lockfile's header no longer claims `refdes fetch` is the only
  thing that writes the file. `.refdes/citations.yaml` carries a comment
  header in every project's committed copy, and it read "Written only by
  `refdes fetch`." — untrue since the editor became the file's second writer:
  an accept of a source value writes the file whole
  (`docs/design/editor-source-picker.md` §4, served by `refdes serve`). The
  header now names both writers. The header is a comment to the YAML reader,
  so existing lockfiles keep loading untouched; the next `refdes fetch` or
  editor accept rewrites it with the true sentence.
