- `refdes history redact` no longer poisons the history store it just wrote.
  A redaction event's removal-set fingerprint -- 12 hex characters -- was stored
  in the event's `successor_key`, and that field holds surrogate keys:
  `keys.require_storage_key` refuses a value whose plain YAML spelling would
  resolve to something other than a string. About one fingerprint in 300 is all
  decimal digits (or all octal digits behind a leading zero), and for those the
  next `history` command in the project exited 1 with `key '213312678452' is
  malformed: expected exactly 11 characters` -- even though the file's bytes were
  correct, since `yaml.safe_dump` quotes the value and nothing had been lost. It
  looked like a Windows-only test flake (windows-latest, run 37099112528 attempt
  1, green on rerun) only because the fingerprint depends on the keys a run
  mints. A redaction event now carries its `fingerprint:` in a field of its own,
  which the event-id derivation and the duplicate-edge check read when there is
  no `successor_key`; every event id, including those already written to existing
  stores, is unchanged. `successor_key` is now written only by a `follows:`
  capture, and only ever with a key.
