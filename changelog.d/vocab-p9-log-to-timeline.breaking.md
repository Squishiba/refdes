- **Breaking:** the `on_change` mode `log` is renamed to `timeline`
  (vocabulary-review.md P9). The mode's whole meaning is "this change
  belongs in the field-level timeline the history layer has not built
  yet", and `timeline` says that without borrowing the name of the `log`
  item type. The rename covers the mode in every spelling: the project
  `on_change.default`, type/field/body annotations in `refdes-schema.yaml`
  and the bundled standard (all of `hardware@3`'s annotations now read
  `timeline`), the `refdes audit` report and `refdes schema --json`, item
  front-matter overrides (scalar, `mode:`, and `fields:` entries), and the
  docs tables. The old spelling's posture is P2's hard-error posture, gated
  by the standard pin: a v3 pin or no pin gets a load-time error naming
  `timeline` — for the settings default and schema annotations it is a
  configuration error (exit 2); on an item the error is reported and the
  override is still applied as `timeline` for that build, so nothing
  cascades off its absence. A project pinned to `hardware@1` or `@2` keeps
  reading `log` and keeps seeing it: the released standards spell the mode
  that way in their own yaml, so an ungated hard error would make the
  released standard itself fail to load — the pinned vocabulary is what
  the pin promises. `refdes rename` cannot rewrite mode values (its
  mapping sections rename keys), so a v2→v3 upgrade surfaces these errors
  and the author renames by hand; each error names the new spelling.
  `timeline` and `log` behave identically today — the difference is only
  the name, and the name is what P9 fixed.
