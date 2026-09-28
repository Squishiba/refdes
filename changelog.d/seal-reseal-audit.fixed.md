- **Accepted reseals now leave durable audit evidence.** `refdes build
  --reseal` appends an event to the existing seal file with the item, UTC
  timestamp and old/new hashes, and `refdes audit` displays it after later
  builds. Repeated edits and accepted removals preserve earlier events;
  key adoption and hash carry-forward preserve the history too. Preview
  reseals (`--dry-run`/`--no-write`) record nothing and say so. Prior reseals
  cannot be recovered from a seal file that already lost their old hashes.
