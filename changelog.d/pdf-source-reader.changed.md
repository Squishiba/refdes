- A cited `.pdf` is no longer reported as "no source reader for '.pdf'
  files": it has a reader now, registered only when the optional `refdes[pdf]`
  extra is installed, and without it the refusal names the install
  (`pip install refdes[pdf]`) in the same words a `section:` citation already
  got. A `source()` line naming a PDF therefore fails with a different, more
  specific error — the pdf reader does not extract values, because a PDF value
  is picked by a human from a page's candidates and re-extracted from the quoted
  row — instead of the registry's "no reader for this file type". Nothing is
  pinned either way, and no number is invented.
- The optional `refdes[pdf]` extra now asks for `pypdf>=6.19` rather than
  `pypdf>=4.0`. Before 6.19, pypdf reported a zeroed text position for most of
  a page's text runs, so a datasheet table could not be laid out at all. An
  existing install is unaffected — `section:` resolution works on every version —
  and a page read on an older pypdf is refused with the version and the fix
  rather than drawn with its rows in the wrong place.
