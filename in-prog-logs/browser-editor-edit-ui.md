# Browser editor: the edit UI (part 3b-ii)

What the author can change in the browser, and how a save reaches the file.

## What landed

- `POST /api/item/<ref>/edit` in `serve/api.py` — the HTTP face of
  `serve.edit.apply_edit`, which already owned the transaction. Status mapping:
  Applied 200, Conflict 409, Refused 422, Invalid 422, malformed request 400.
  `--no-write` is a 403 before any of that.
- `GET /api/item/<ref>` gained an `edit` block: `file_revision`, `editable`,
  `reason`, `fields.<name>.{editable,reason,control,choices,required,value_type}`
  and `body.{editable,reason}`. The form draws what the server says; the client
  re-implements no schema rule.
- `static/drafts.js` — the draft: memory plus a sessionStorage mirror keyed by
  item handle, a `beforeunload` guard while dirty, and the revision the draft
  was opened on. A rebuild-triggered re-render re-seeds the controls from the
  draft, so an autosave of the model cannot eat an in-progress edit.
- `static/editor.js` — the controls, the save loop, the blocked-save panel and
  the conflict screen. `static/item.js` asks the editor for a control per field
  and per body and falls back to the old read-only rendering with a badge that
  states the reason.
- After an Applied, `app.state.refresh()` runs — the same path the file watcher
  uses — so the next `GET`, the list, and the rendered preview all come from the
  saved bytes.

## Decisions taken here

- **`expected_revision` is the per-file sha256**, not the project serial. Two
  edits to two items in one file are serialised by the file, which is the unit
  the patcher writes; the project serial would make unrelated edits collide.
- **The conflict diff is "disk now" vs "disk now with the requested op
  applied"**, which is what the patcher can compute without keeping the
  author's base copy. The browser shows that diff plus the author's draft in a
  separate box, so nothing is silently combined: keep-mine re-posts against
  `current_revision`, keep-theirs drops the draft, copy-by-hand selects the
  draft text. No merge, per the design's "draft, refuse, diff — never merge".
- **A save is one POST per dirty part**, in field order, each carrying the
  revision returned by the previous one. A conflict mid-way leaves the earlier
  parts applied and the rest in the draft; the panel then offers to re-post the
  remainder. This is the simplest thing that keeps a partial failure recoverable
  without inventing a multi-op transaction. (If we later want all-or-nothing,
  the transaction belongs in `serve/edit.py`, not in the browser.)
- **Sealed is not the same as append-only.** An append-only item with no seal is
  editable; a sealed item is read-only with `sealed` as the reason, on every
  field and the body, and the server still refuses it independently.
- **Read-only reasons come from the server**: identity (`id`, `key`, `type`),
  non-scalar field types (`list`, `checks`, `citations`, `options`), sealed
  items, and `--no-write`. Links stay out of this slice entirely.
- **`who` is `local`.** The service keeps the parameter; there is no second
  author today.
- **Numeric and boolean fields are coerced client-side** from the input string
  using `value_type`, because the patcher writes the value it is given and a
  quoted number would change the YAML's type.

## Found on the way

`static/app.js` declared `const gitBadge` twice — a SyntaxError that made the
whole module fail to parse, i.e. the editor page was blank-on-arrival on main.
Fixed here (one declaration); worth knowing that nothing tested the served JS
until `tests/test_serve_static.py`.

## Unverified / open

- The browser smoke pass is recorded separately; the checks here are HTTP-level
  plus static analysis of the served shell.
- Focus is lost in a control if a rebuild re-renders the view mid-typing. The
  draft survives; the caret does not. Left alone deliberately — fixing it means
  diffing the view instead of replacing it, which is a bigger change than this
  slice.
- A conflict that arrives *after* some parts of a multi-part save applied shows
  the remaining draft; whether the earlier parts should roll back is a service
  question, deferred with the multi-op transaction above.
