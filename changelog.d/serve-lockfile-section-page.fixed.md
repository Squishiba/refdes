- `serve`: a lockfile `sections:` value that is not a page number is now
  reported on the PDF citation panel, not a dead handler. The page the
  lockfile resolved for a citation's `section:` used to be read with a bare
  `int()`, so a record like `sections: {Intro: nope}` — which loads, because
  the lockfile validator types the `sections:` mapping but not its values —
  crashed the handler with `ValueError: invalid literal for int()`, leaving
  the browser with no response on the page route and taking the picker's
  file listing down with it. The value is now read by the shared page
  grammar (the same one a `page:` is checked against, so an oversized digit
  run is refused there too): the picker opens page 1 and the citation names
  the bad value and the fix, `refdes fetch --update --path <path>` to
  re-resolve it — the same posture the panel already keeps for a `page:`
  that is not a page, a page past the document's count, and a section
  resolved against other bytes. Valid numbers, YAML integer or string, open
  the resolved page as before.
