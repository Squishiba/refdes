- **Breaking:** a link verb named like one of the engine's reserved
  front-matter keys (`id`, `type`, `body`, `former_ids`, `key`, `prefix`,
  `board`, `workspace`, `on_change`) is now a load-time configuration error
  (exit 2) naming the verb and the key it collides with -- a project that
  declared one must rename the verb to load again. Before this, front matter
  spelled that key for the engine and never for the link, so the verb could
  never be written on an item. The loss was silent -- a clean exit and no
  link -- for the list spelling `on_change: [MEMO-002]`, for a `body:`
  collision (the target was absorbed into the item's body), for a
  `prefix:`/`board:`/`workspace:` collision (absorbed as the item's own
  prefix/board/workspace hint), and for the list spelling `id:` (it silently
  became the item's id). The rest errored, but about the wrong thing: a
  scalar `on_change: MEMO-002` came back as a bogus "must be one of
  invalidate, log, ignore" error; `type:` errored as an unknown type in
  either spelling; a scalar `id:` naming a live item failed as a duplicate
  id (naming nothing live, it silently renamed the item); `key:` was read as
  the item's own surrogate key and rejected as malformed; and `former_ids:`
  was read as the item's own former ids and rejected for naming a live id.
  The check reads `parse.RESERVED` and `parse.OVERRIDABLE`
  rather than restating them, so the whole class is guarded, including
  reserved keys added later, and both ends of a verb are checked (a
  declared `inverse:` too). No bundled standard verb collides; only a
  project that declared such a verb sees the new error — which is the
  point: it previously had links it could not write.
