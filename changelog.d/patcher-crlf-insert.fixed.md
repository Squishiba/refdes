- Inserting a field into an item in a CRLF file no longer splits a line break.
  Adding a field an item does not yet have (including a first `body:`) chose its
  insertion point by walking back to the end of the item's previous value, which
  on a CRLF file stopped between the CR and the LF: the saved file came back with
  `\r\r\n` at the insertion and a bare `\n` after the added block. The insertion
  point now lands on a line boundary, the added text uses the file's own line
  ending, and a file with no final newline still has none. The patcher's own
  verification now refuses any plan whose span edge falls inside a line break, so
  a broken splice cannot reach a file even from a hand-built plan.
