- **The browser editor can edit an existing item.** `GET /api/item/<ref>` now
  carries an `edit` block — the file revision the view was loaded against, and
  per field whether it is editable, what control to draw (a text input, or a
  select carrying the enum's own choices), and, when it is not editable, the
  reason (`sealed`, `id/key/type are identity`, `not a scalar field`).
  `POST /api/item/<ref>/edit` is the HTTP face of the write service that
  already existed: same token, Host and Origin gating as the other mutating
  routes, same body-size and content-type limits, `who: local`. Applied is 200
  with the file's new revision, so the next save can name it; a stale revision
  is 409 with the current span text and a diff; a refusal is 422 with a reason;
  an edit that would break the build is 422 with the blocking diagnostics. In
  the view, editable scalars get a control and the body a textarea; the draft
  lives in the browser (mirrored to sessionStorage, with a leave-page guard),
  the save button says *unsaved* until it is not, and a conflict offers
  keep-mine, keep-theirs or copy-by-hand — never a merge. Read-only fields say
  why where they sit. Link editing, item creation and id/key editing are still
  later slices. (docs/design/browser-editor.md, part 3b-ii.)
