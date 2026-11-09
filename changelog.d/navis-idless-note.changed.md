- `refdes navis ls` and `refdes navis all` now note on stderr when items
  with no `id:` yet were skipped by the scan
  (`note: N item(s) have no id yet and were not scanned -- run 'refdes
  id' to allocate them`), so a project whose only markers sit in
  not-yet-allocated items no longer reads as having no Navis at all.
  The listing on stdout and the exit codes are unchanged.
