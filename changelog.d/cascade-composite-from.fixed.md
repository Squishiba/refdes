- `{{cascade}}`'s `from=` now accepts a `DISPLAY-ID@key` composite and
  resolves it by its key half, the way `{{calcblock}}`'s `item=` already
  did. A composite whose label had gone stale reported "does not exist"
  and failed the build; it now walks from the item the key names.
