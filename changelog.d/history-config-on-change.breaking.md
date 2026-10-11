- **Breaking:** the project setting `history:` is renamed to `on_change:`, and
  the item front-matter override `history:` is renamed to `on_change:`. The old
  name collided with the history store and `refdes history` command family,
  while the key always set the default `on_change` mode (vocabulary-review.md
  P2; the owner lifted the hold on 2026-10-10). The value shape and precedence
  are unchanged: item field override, then whole-item mode, then schema field,
  then project default. An old spelling is a hard error naming `on_change:`;
  `refdes revise` cannot express either rename, so rename the setting in
  `refdes-project.yaml` and the override in each item file. The history store,
  `sealing: history`, and the per-field `on_change:` schema attribute are not
  renamed.
