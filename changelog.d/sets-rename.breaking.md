- **Breaking:** `field_sets:` is renamed to `sets:`. The rename lands with
  the composition widening (docs/design/composition.md): a set now carries
  `links:` and `body:` as well as fields, so the old name described less
  than the thing is. Rename the key in `refdes-schema.yaml` — the entries
  themselves are unchanged; a project still writing `field_sets:` gets an
  error naming the rename, not a bare unknown-key. Bundled standards
  already released (`hardware@1`, `hardware@2`) keep their frozen bytes and
  the loader reads either key from a bundle file; everything written from
  here speaks `sets:`.
