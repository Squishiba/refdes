- **Breaking:** under `hardware@3` the per-type prose fields fold into the
  reserved `body:` key: `requirement.text:` and `bound.text:` become
  `body:`, and `test.method:` becomes `body:` (with `component.datasheets:`
  renamed to the shared `citations:` in the same migration — all four in
  `v3/migration.yaml`, all four applied by `refdes standard upgrade --to 3`
  in its refuse-and-roll-back transaction). Under a v3 pin a requirement
  that still spells `text:` fails the build: `text:` is no longer a
  declared field, and the fold is why — the merged `log` and every prose
  type now read one key, and v1/@2 keep the old names. `refdes standard
  upgrade` refuses (before writing anything) any item that already has
  body content of its own — a list-file `body:` or markdown prose after
  the closing fence — because the rename into the reserved `body:` key
  would silently orphan one of the two texts
  (`revise.check_body_merge_conflicts`); the refusal names the item, the
  fix is to merge the two texts by hand, then re-run the upgrade. On the
  v3 side there is no command to undo the fold — `refdes rename` cannot
  map two fields onto one key — so a hand-renamed `body:` back to `text:`
  only makes sense by dropping the pin to 2.
