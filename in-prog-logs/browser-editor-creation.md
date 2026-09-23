# Browser editor Slice 3 — item creation

Authority: docs/design/browser-editor.md "Slice 3 — creation", "Identity
handled for the author" (item 3), Decisions "Creation destination: suggest
plus override". Display-ID rename stays out of scope.

## Plan

1. **ids.py**: split pure planning out of `allocate()`.
   - `prefix_for_type(project, type_name)` (with `prefix_for` delegating),
     `format_id(project, prefix, number)`.
   - `plan_new_id(project, type_name, *, explicit_id=None, marks=None)` —
     pure: next free number for the type's prefix, or the explicit override
     validated against the high-water (live ids, former_ids, burned,
     allocated). Returns `(new_id, reason)`; never touches the ledger file.
   - `reserve_id(project, new_id)` — the ledger mutation, called only inside
     the create transaction.
2. **dates.py**: `format_date(value, date_format)` — there was no formatter,
   only a parser; adding it here keeps the project-format output rule in one
   place instead of hand-formatting in the service.
3. **serve/edit.py**: `create_item(project_root, CreateRequest)` under the
   same per-project write lock; `Created` result alongside
   Applied/Conflict/Refused/Invalid. Destination suggest+override; three
   shapes (append YAML list file, append multi-item Markdown, new
   single-item Markdown). Key minted with `keys.mint()`, link composites via
   `links.composite_for`, field skeleton from the schema (scaffold's field
   set). Delta gate: exactly one new item, no new errors, PyYAML-authoritative
   post-check that the new id resolves with the minted key. Atomic file write
   (`_atomic_replace` / exclusive create), then `reserve_id`; a failed
   reservation rolls the file back — a failed creation burns nothing.
4. **API**: `GET /api/create/schema`, `GET /api/create/preview` (id preview +
   destination suggestion, no reservation), `POST /api/items/create`.
5. **UI**: shared field-control factory extracted from editor.js
   (`controls.js`), `create.js` New Item form with id preview and
   destination suggest+override, "Amend this sealed log" affordance on sealed
   log views. Plain ES modules, CSP `script-src 'self'`.

## Open calls (logged, unambiguous part done anyway)

- **No `expected_revision` on create.** Creation is pure append/new-file: the
  existing bytes outside the appended span never change, so the conflict
  machinery (which protects an *edited* span) has nothing to guard. A
  destination that vanished or appeared between preview and create is caught
  by destination validation under the lock.
- **New YAML list files are not a v1 destination.** The doc names exactly
  three shapes; creating a fresh list file would mean inventing the
  `defaults:` block's board/workspace policy. Refused with a reason; `refdes
  new --list` remains the way to start a list file.
- **No body text in the create request.** Fields only; the body is edited
  after creation through Slice 1's SetBody. body_required types get the
  existing warning, not an error, so this does not block creation.
- **Ledger reserved after the file write.** If the reservation fails the file
  is rolled back (nothing half-created). A crash strictly between the two is
  still safe: `high_water` counts live items, so an on-disk id is never
  re-handed even if the ledger line is missing.
- **Date default**: a declared `date` field not given by the author is
  filled with today in the project's `date_format` (the log-creation
  requirement); an explicit value is validated by the delta gate like any
  other field.
