- **The CLI reference now says which exit code a name that does not resolve
  gets, per command.** `docs/cli-reference.md` states the convention once -- `0`
  success, `1` errors found, `2` configuration error -- and that split does not
  cover "the id, baseline, preset, type, or file you named is not there", which
  the commands have been deciding individually ever since `history` landed. A
  reader who took the one line as a rule got it wrong half the time: `refdes
  history capture NOPE-001` exits `2`, exactly as its section documents, while
  `refdes fetch --item NOPE-1` exits `1` and the `fetch` section said nothing at
  all about the case. Both codes are kept -- `history`'s `2` is a documented
  contract, and `fetch`'s `1` sits with the other documented `1`s for a name
  that does not resolve (`new` and `schema --graph` on an undeclared type,
  `former-ids propose --baseline` on a baseline never stamped, a refused `keys
  restore`) -- so what changed is that the reference now records the split
  instead of leaving it to be guessed: a table at the exit-codes line listing
  every such command with its code, and a paragraph in the `fetch` section
  stating its three refusals (`--item` naming no item, `--item` naming an item
  with no `citations:` field, `--path` nothing cites) and the code they return.
  `refdes ls --board nosuchboard` exiting `0` with `no items match` is called
  out in the same table as the one command that reports an undeclared name as an
  empty result. **No exit code changed**, and `tests/test_exit_codes.py` pins
  every code in that table, so a future change to any of them fails a test
  rather than silently invalidating the table.
