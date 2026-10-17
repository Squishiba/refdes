- The generated vocabulary page (`vocabulary.html`, `docs/vocabulary.md`)
  no longer claims an inverse link name like `verified_by:` can be authored
  on the far end -- builds reject it; it is a computed backlink. It also
  tells the truth about the rest: a required `body:` is enforced as a
  warning, `former_ids:` is written by `refdes former-ids propose
  --confirm` or by hand (never automatically on a re-mint), the `board:`
  path segment resolves only against the `boards:` registry, and a
  `section:` marker asserts the type of the items after it.
