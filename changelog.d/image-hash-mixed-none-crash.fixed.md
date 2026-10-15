- `refdes build` no longer dies with `TypeError: '<' not supported between
  instances of 'NoneType' and 'str'` when one item's body both leaves an
  image with a separator unresolved and resolves a second src to the same
  project-relative path -- e.g. `![a](assets/sub/img.png)` beside
  `![b](../assets/sub/img.png)` in an `items/` document, where the raw src's
  text is exactly the other src's resolved path. The hash pass's entry set
  then held `[path, None]` next to `[path, digest]`, and sorting the raw
  pairs compared the sentinel with a str digest. The crash fired in
  `compute_hashes`, before the render pass could report the missing image at
  its line, so the build died with a traceback instead of the ordinary
  diagnostic; the sort key now orders the entries without ever comparing
  `None` with a string, and the missing-image error stands. A set of
  all-resolved digests -- every ordinary project -- sorts exactly as the
  plain pair did before, so no existing content hash moves.
