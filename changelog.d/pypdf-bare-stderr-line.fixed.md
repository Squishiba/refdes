- A PDF that pypdf cannot open no longer prints a line of its own to stderr.
  pypdf reports a damaged document partly by *logging* it — `EOF marker not
  found` on the `pypdf._reader` logger — and an application that configures no
  logging receives that text anyway, printed bare by Python's last-resort
  handler: no file, no path, no context, immediately above the `refdes fetch`
  warning that explains the same failure, so it read as the tool crashing and
  then recovering (run-5 gate finding F2). refdes now owns the report of a read
  refdes is performing: pypdf's words are collected while it reads and folded
  into refdes's own message, which names the file and — as `refdes check`
  already did — says what to do:

  ```
  WARNING  http://127.0.0.1:8899/bad.pdf: the pages could not be counted to
  check the page numbers cited here -- counting a document's pages failed:
  pypdf could not read the PDF: Stream has ended unexpectedly (EOF marker not
  found). The page numbers cited for http://127.0.0.1:8899/bad.pdf are not
  checked: confirm that http://127.0.0.1:8899/bad.pdf really is a complete PDF
  -- a download that ended early is the usual cause -- then run 'refdes fetch
  --update --path http://127.0.0.1:8899/bad.pdf' to count its pages
  ```

  Nothing that was printed before is lost, only attributed: the exception
  pypdf finally raises says only "Stream has ended unexpectedly", and the
  logged "EOF marker not found" is the fact that names the damage, so both
  appear. The missing-extra case is unchanged — `counting a document's pages
  needs the optional PDF extra: pip install refdes[pdf]` already carries its
  own remedy, and telling an author their file is broken because they did not
  install a library would be a false lead.
