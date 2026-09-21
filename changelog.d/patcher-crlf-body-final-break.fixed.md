- Editing the body of a Markdown item in a CRLF file no longer writes a stray CR
  at the end. When the body ran to the end of the file, its closing break was
  converted to the file's line ending twice, so the saved file ended that body
  with `\r\r\n` — the LF was intact and the CR beside it was orphaned, which a
  check for bare line feeds cannot see. The body's final break is now converted
  once and the file keeps exactly one. The patcher's verification now rejects any
  replacement containing a CR that is not part of a line break (or, in a CRLF
  file, an LF that is not), anywhere in the text it writes and not only where the
  span meets the file, so a doubled conversion cannot reach a file from a
  hand-built or stale plan either.
