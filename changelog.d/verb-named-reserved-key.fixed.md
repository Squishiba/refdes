- A link verb named like one of the engine's reserved front-matter keys
  (`id`, `type`, `body`, `former_ids`, `key`, `prefix`, `board`,
  `workspace`, `on_change`) is now a load-time configuration error naming
  the verb and the key it collides with. Before this, front matter spelled
  that key for the engine and never for the link, so the verb could never
  be written on an item: `on_change: MEMO-002` came back as a bogus
  "must be one of invalidate, log, ignore" error, and the list spelling
  `on_change: [MEMO-002]` — or any collision on `prefix:`/`board:`/
  `workspace:`/the `RESERVED` keys — silently dropped every such link with
  a clean exit. The check reads `parse.RESERVED` and `parse.OVERRIDABLE`
  rather than restating them, so the whole class is guarded, including
  reserved keys added later, and both ends of a verb are checked (a
  declared `inverse:` too). No bundled standard verb collides; only a
  project that declared such a verb sees the new error — which is the
  point: it previously had links it could not write.
