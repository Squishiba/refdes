- `refdes serve` now sends each response as a single write with TCP_NODELAY
  set on the accepted connection, so a refusal's reply can no longer sit in
  the server's stack while its linger window expires and the close turns
  into a connection reset -- the windows-latest flake that replaced a
  refusal's 4xx with WinError 10053/10054 (run 42606063274).
