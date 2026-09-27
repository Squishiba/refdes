# editor-image-upload Phase 1 — Bytes

Branch `editor/image-upload-phase1`, based on origin/main (includes Phase 0
picker, #50). Scope is exactly §17 row "1. Bytes": `POST /api/assets`, the
`_api` content-type branch and asset cap, sniff-based type allowlist,
single-segment name validation, `_atomic_create` for new files, the §5
collision table, forced preview rebuild. Explicitly NOT in scope: §9 checks
(Phase 2), `expected_hash`/replace (Phase 2), §10 seals (Phase 3), client UI
(Phase 4). The known hole — an upload can break another document — stays
open by design.

## Design decisions taken while reading

- Route: `POST /api/assets?dest=<dir>&name=<file>` (or `item=<handle>` to
  default `dest` to the item's source directory, §4), raw bytes as the body,
  `Content-Type: application/octet-stream` (§11). Metadata in query
  parameters only.
- Cap: `MAX_ASSET_BYTES = 8 MiB` in `serve/server.py` next to
  `MAX_BODY_BYTES`; checked against `Content-Length` before any read (413)
  and again against bytes actually read, per §6.
- Name: refused unless it is a single segment — no `/`, no `\` — then
  `security.safe_relative_parts` on that one segment. The design's §5 text
  says "take its basename", but §14's test list and the task scope say a
  name containing `..` or a separator is a *refusal*, single-segment only;
  the refusal reading is the stricter one and is what I implemented.
- Type: signature sniff (PNG 8-byte, JPEG `FF D8 FF`, GIF87a/89a,
  RIFF/WEBP), extension must agree; `.svg` refused with the CSP reason in
  the message (§6); `Content-Type` ignored for the type decision entirely.
- Collision table (§5): absent → `_atomic_create` (reused from
  `serve/edit.py`); identical sha256 → no write, return existing
  path+hash (200, `created: false`); different bytes → refusal naming path,
  size, hash (409). Case-only collision via `citations.case_mismatch` —
  note it only fires on case-insensitive filesystems, so the test emulates
  one by patching `os.path.isfile` for the request.
- Status mapping in `api.py`: 400 shape/validation (name, dest, missing
  params), 409 destination-collision conflicts, 422 type-policy refusals,
  403 `--no-write`, mirroring the existing edit/create routes' posture.
- Rebuild: `app.state.refresh()` after a successful write — the same
  mechanism `_apply_edit` uses. An upload into a declared `site.assets:`
  directory changes the watched signature (Phase 0's `project_inputs`), so
  refresh rebuilds the preview there; an upload to the default item
  directory is not a semantic input until a body references it (§7's
  "orphans are invisible to the build"), so refresh is a correct no-op.
- New service module `src/refdes/serve/upload.py`, mirroring `edit.py`'s
  "a refusal is a value" style; `api.py` stays the HTTP face.

## Progress

- [x] Read the design (§2–§7, §11–§14, §17), browser-editor.md Security,
  `serve/api.py`, `serve/edit.py`, `serve/security.py`, `serve/server.py`,
  `citations.case_mismatch`, `serve/state.py`, Phase 0's `_images`/
  `_image_row`, the serve test harness (`serve_support.py`).
- [x] Chunk 1: `_api` branch + cap in server.py; route in `api.handle`;
  `upload.py` with sniffing, validation, single-segment name.
- [x] Chunk 2: §5 collision table (identical / differing / case-only).
- [x] Chunk 3: atomicity via `_atomic_create` under the write lock; forced
  rebuild.
- [x] Chunk 4: `tests/test_serve_upload.py`, changelog fragment, full
  suite + ruff, commit, PR, CI green.

## Finished

Task complete: 62 tests in `tests/test_serve_upload.py` (1 skipped off
Windows, the native case-insensitive collision), full suite `pytest -q -x`
green at 2382 passed / 2 skipped, and
`ruff check --select E9,F src tests` clean.

What landed:

- `src/refdes/serve/upload.py` — `store_asset(root, dest=, name=, data=)`
  returning `Uploaded` / `Conflict` / `Refused`; `MAX_ASSET_BYTES` (8 MiB)
  defined here as the single source of truth; `sniff_image` for the
  PNG/JPEG/GIF/WebP signatures; `SVG_REFUSAL` carrying the CSP reason.
- `src/refdes/serve/server.py` — imports the cap instead of redefining it;
  the POST gate admits exactly one extra content-type literal
  (`application/octet-stream`) on `/api/assets` only, refuses a missing
  `Content-Length` with 411, and compares the header against the cap before
  `rfile.read`.
- `src/refdes/serve/api.py` — routes `POST /api/assets` (other methods 405),
  resolves `item=` through the existing `_find_item`, defaults `dest` to the
  item's source directory, maps the service result onto 200/400/404/409/413/422,
  and calls `app.state.refresh()` after a write.
- `changelog.d/editor-image-upload.added.md`.

Difficulties and decisions worth keeping:

- The case-only collision row cannot be observed on a case-sensitive
  filesystem: `citations.case_mismatch` asks `os.path.isfile` about the
  differently-spelled name and Linux answers no. One test emulates a
  case-insensitive filesystem for the duration of a single `store_asset` call
  (monkeypatched `os.path.isfile` matching case-folded siblings) so the real
  `case_mismatch` runs, and a second test asserts natively on Windows.
- Two tests initially failed for fixture reasons, not product reasons: the
  `figures/` directory the fixture declares under `site.assets:` did not exist
  (the endpoint creates no directories, correctly), and the symlink-escape test
  pointed its symlink at a directory that was inside the project after all.
  Both fixed in the test, not the implementation.
- Type refusals run before collision refusals, so a test that wants a 409 has
  to send bytes whose signature matches the extension. Worth remembering for
  the Phase 2 `expected_hash` tests.
- Deliberately not done, per §17: `expected_hash` and the replace path, the
  §9.1 ambiguity and §9.2 capture checks (Phase 2), the §10 sealed-target and
  sealed-referenced refusals (Phase 3), and any client UI. Phase 1 therefore
  ships with the known hole that an upload into a shared `site.assets:`
  directory can break another document; Phase 2 closes it.
- The over-cap `Content-Length` refusal does not drain the request body. That
  is safe because `BaseHTTPRequestHandler` defaults to `HTTP/1.0`, so the
  socket closes after the response and the unread bytes die with it — the same
  posture the pre-existing `MAX_BODY_BYTES` gate has always had.
