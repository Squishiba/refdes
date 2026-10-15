- The New Item form's "would be" id can no longer show a superseded answer
  (EDITOR-API-011): `refreshPreview` fires one preview request per id/
  destination keystroke and per type/board/workspace change, and network
  completions arrive in any order, so a late response for input the user has
  already replaced used to land last and write the id badge, the suggested
  destination, and (on failure) a "preview failed" banner over the newest
  request's answer. Each refresh now takes a sequence number and its
  continuation -- success and failure alike -- writes only while it is still
  the newest, so a stale response mutates nothing. Nothing is reserved by a
  preview, so the visible id is the form's only promise before Create; it is
  now always the newest plan. Pinned by a node harness that drives the real
  `create.js` over deferred fetch stubs and lands responses out of order.
