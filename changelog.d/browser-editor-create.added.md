Item creation in the browser editor (Slice 3). `ids.py` splits the pure
planner `plan_new_id()` (what id WOULD be minted, nothing reserved) from
`reserve_id()` (the ledger mutation, called only inside the same transaction
as the file write). `serve/edit.py` gains `create_item`, running under the
same per-project write lock as `apply_edit`: it plans the id, mints a key,
validates fields against the resolved schema (a declared `date` field
defaults to today in the project's own `date_format` via the new
`dates.format_date`), composes the item text from the scaffold's initial
field set and the patcher's round-trip-checked scalar emitter, gates the
whole thing through an overlay load (exactly one more item, no new errors,
the new id resolving with the minted key), writes atomically, and only then
reserves the id -- a failed creation burns nothing. Three destination
shapes: append an entry to an existing YAML list file, append a fenced
document to a multi-item Markdown file, or create a new single-item
Markdown file; the destination arrives as a suggestion from the type's most
common source file and stays a plain overridable path. An explicit id
override is honoured verbatim or refused against the prefix's high-water
mark, never renumbered. Amending a sealed log is pure creation: a new
entry carrying an `amends:` composite from `links.composite_for`, with the
sealed entry's bytes never touched. API: `GET /api/create/schema`,
`GET /api/create/preview` (pure id preview and destination suggestion),
`POST /api/items/create`. The UI gains a New Item form (`#/new`) reusing
the editor's field controls, now factored into `controls.js`, with a live
id preview that reserves nothing, and sealed append-only items offer
"Amend this sealed log" linking to the pre-filled form.
