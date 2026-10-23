- An imported item's diagnostics now point at the upstream definition
  instead of a fabricated location. `refdes check` used to report every
  diagnostic on an imported item at `<import:platform>:1` -- a pseudo-path
  that is not a file, on a line that was never parsed from anything --
  because `imports.py` stamped every imported item with
  `source_file=f"<import:{origin}>"`, `source_line=1` and threw away the
  record's own `source`. The built artifact records each item's real
  `file:line` (`docs/output.md`: "enough for go-to-definition"), so the
  import now carries it through, prefixed with the import name to mark it
  as upstream: `ERROR platform:items/interfaces/req.md:2 [REQ-IF001] - ...`
  for an import named `platform`. A record whose `source` is missing or
  malformed keeps the old `<import:NAME>` line 1, so artifacts built by
  older versions load unchanged. Nothing else moves: imported items stay
  `external`, read-only, and keep their ids, keys, and hashes; the
  editor's and patcher's write refusals read the `external` flag, not the
  path spelling. The VS Code extension keeps ignoring imported-item
  diagnostics: its Problems-panel filter skips both the old `<import:NAME>`
  pseudo-path and the new import-qualified spelling, so neither publishes
  a phantom diagnostic against a file that does not exist locally.
