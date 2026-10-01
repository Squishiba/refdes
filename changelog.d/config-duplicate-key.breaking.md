- **A key written twice in a config file is now a configuration error.**
  `refdes-project.yaml` and `refdes-schema.yaml` had the same silent loss as
  item files did, and the same cause: YAML resolves a repeated mapping key by
  keeping the last value, and says nothing about it. A second `site:` block
  replaced the first outright — `refdes check` reported `0 errors`, exit 0, and
  the project rendered under the title nobody remembered deleting, with no
  diagnostic anywhere that a `site:` had gone missing. In `refdes-schema.yaml`
  the loss is larger still: a `types:` block declared twice takes every field
  the first block declared out of the merged schema, so each item using one of
  them reports a missing field rather than a broken config. Nested repeats count
  too — two `title:` lines inside one `site:` block, two `presets:` lines inside
  `standard:` — as does a `revise` mapping file, where a repeat drops one of the
  two renames the file asked for and applies the other. The message is the
  item-file one verbatim, through the same detector, so a repeat reads the same
  way whichever file it is in:
  `configuration error: refdes-project.yaml: duplicate key 'site' in one mapping
  (lines 1 and 14) -- YAML keeps the last, so the value on line 1 is lost.` It
  carries the line of *each* occurrence, which is more than any other
  configuration error gives you: a repeat is the one config problem whose whole
  diagnosis is two line numbers. Every repeat in the file is named in the one
  error, and the check runs before any setting is read — the settings checks
  were judging a mapping the file does not contain. The commands that write the
  config (`refdes standard add-preset`, `remove-preset`) refuse a repeated key
  as well, since they append to the text of a `presets:` the loader is not
  reading. Refdes's own state under `.refdes/` is deliberately not covered: a
  repeat there is a refdes bug rather than an authoring slip, and seal hashes,
  baseline diffs and `audit` all read those files and would each need their own
  decision.
- **What you have to do:** a project whose config spells a key twice now stops
  loading, on every command, with `configuration error: ... duplicate key ...`
  and exit 2. Before this change the same file loaded and the earlier value was
  gone; if you have hand-merged a config, or appended a block to one, look for
  the setting you meant to keep and check what the one that lost was saying —
  `git log -p` on the config file is the fastest way to see which block arrived
  when. Delete one of the two, or merge what both were setting into the one you
  keep. A project with no repeated key anywhere sees no change at all.