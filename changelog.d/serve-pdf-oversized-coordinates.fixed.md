- `serve`: an oversized page/row/token on the Editor's PDF citation
  routes is now a refusal, not a dead handler. A `page`, `row` or
  `token` query longer than 64 digits — e.g. the 5000-digit value a
  stray paste can produce — used to crash the handler inside `int()`
  (`ValueError: Exceeds the limit (4300 digits) for integer string
  conversion`), so the browser got no response at all
  (`RemoteDisconnected`) while the equivalent short garbage (`page=abc`)
  answered 422/400. The page route now answers its documented 400
  ("page must be a positive integer"), the proposal route its
  documented 422 ("must be an integer >= N for a PDF pick"), the accept
  path refuses the same way, and a 5000-digit `page:` in a citation
  loads as a named check error instead of a traceback. The 64-digit
  bound is the grammar's own, not the interpreter's conversion limit
  (default 4300, disable-able, smallest non-zero limit 640 on CPython
  3.13): a 65-digit page is refused under every setting, and accepted
  values are unchanged below the bound.
