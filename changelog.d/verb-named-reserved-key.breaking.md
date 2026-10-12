- **Breaking:** a link verb named like one of the engine's reserved
  front-matter keys (`id`, `type`, `body`, `former_ids`, `key`, `prefix`,
  `board`, `workspace`, `on_change`) is now a load-time configuration error
  (exit 2) naming the verb and the key it collides with -- a project that
  declared one must rename the verb to load again. Before this, front matter spelled
  that key for the engine and never for the link, so the verb could never
  be written on an item: `on_change: MEMO-002` came back as a bogus
  "must be one of invalidate, log, ignore" error; the list spelling
  `on_change: [MEMO-002]` and a `body:` collision silently dropped the
  link with a clean exit; a `prefix:`/`board:`/`workspace:` collision
  dropped it too, absorbing the value as the item's own prefix/board/
  workspace hint; and `key:`, `former_ids:`, `id:` and `type:` collided as
  the item's own surrogate key, former ids and identity -- read as engine
  values, not as links. The check reads `parse.RESERVED` and `parse.OVERRIDABLE`
  rather than restating them, so the whole class is guarded, including
  reserved keys added later, and both ends of a verb are checked (a
  declared `inverse:` too). No bundled standard verb collides; only a
  project that declared such a verb sees the new error — which is the
  point: it previously had links it could not write.
