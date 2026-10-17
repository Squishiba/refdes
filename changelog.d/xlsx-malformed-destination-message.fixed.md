- A malformed XLSX defined-name destination (one openpyxl's own `destinations`
  parser crashes on, like a bare `A1:B2` with no sheet) reported
  `invalid defined-name destination: 'NoneType' object has no attribute
  'group'` — a Python-internal with no mention of the offending destination.
  The message now quotes the destination text and says what a defined name
  must be: a cell reference to exactly one cell, like `Sheet1!$B$2`.
