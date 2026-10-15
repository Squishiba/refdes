- The browser editor's New Item form completes the docs' promise
  (`docs/design/browser-editor.md`, "Creating items": type, then
  board/workspace where configured): when the project registers `workspaces:`,
  the form renders a Workspace select next to Board, the chosen key rides
  `GET /api/create/preview` as `?workspace=`, and `POST /api/items/create`
  carries it in `fields.workspace` -- which the create service has accepted
  all along (`serve/edit.py`'s `_creation_fields` and the emitted
  `workspace:` line). `suggest_destination` narrows by workspace the way it
  already narrowed by board (both given: the intersection, with the same
  fallback when nothing sits in it), so the preview and the save agree on the
  destination, and an undeclared value is refused by the overlay gate
  (422), not written. `#/new?workspace=` pre-selects it, mirroring `?board=`.
