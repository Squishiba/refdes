- `refdes serve` now lets a refused request's body drain briefly before
  closing the connection, so clients see the 4xx (405/403/411/413/415)
  instead of a connection reset. Every refusal is decided on the request
  headers, before the body is read, and the old close landed while the
  client was still writing: the socket sent RST instead of FIN, and a
  Windows client discards its buffered response on the abort — the
  recurring `WinError 10053/10054` in the serve tests, reachable in
  principle by any client (curl, a browser) uploading to a refused route.
  The drain is bounded (2 MiB, 0.25 s per connection), so a client still
  cannot make a refused request buffer an oversized body.
