- Fixed all 16 broken in-page/cross-page anchor links in the published
  docs (e.g. `links.md#blocked_by-and-the-cascade-report`, whose real id
  slugifies the code-span heading to `blocked-by-and-the-cascade-report` —
  the site's slug rules drop underscores, GitHub's do not). The
  documentation site build never checked anchors, so these shipped
  silently; a new test (`tests/test_docs_anchors.py`) now walks every
  `[text](target)` link in `docs/*.md` and `README.md` against the heading
  ids produced by the very same code the site build uses
  (`pages.add_heading_anchors`), so a drifted anchor fails CI instead of
  404-ing for readers.
