- The VS Code extension's HTTP client can now send authenticated JSON POSTs
  to `refdes serve` (`ServeClient.post()` plus the Archive/Restore/Mint
  route wrappers), with the headers the server enforces. No user-visible UI
  uses them yet — the commands come in the next slice.
