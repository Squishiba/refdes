# editor-image-upload Phase 4 — Client

Branch `image-upload-phase4-client`, based on origin/main (which already
carries Phase 0 picker #50, Phase 1 "Bytes" #52, Phase 2 "Conflicts" #53 and
Phase 3 "Seals" #60). Scope is exactly §17's row "4. Client": drag-and-drop
and file input, a `data:` preview before upload, insertion into the draft
with default alt text, and the conflict dialog's binary variant. Purely
browser JS plus the static checks that stand in for a JS test runtime; no
Python behaviour changed.

## What I read first, and what it settled

- `docs/design/editor-image-upload.md` in full — §7 (the client inserts the
  returned `from_source` into the draft; the upload never touches a body),
  §8 (the binary conflict carries facts, not a diff; replace = re-issue with
  the returned hash, and §15.7 says that re-issue *is* the confirmation),
  §9.3 (the conflict payload names every referencing item), §10 (a sealed
  refusal has no `expected_hash` that unlocks it — hard refusal, never a
  confirmable conflict), §11 (raw bytes, metadata in the query, `data:`
  preview is CSP-legal), §12 (the endpoint already forces the rebuild).
- `src/refdes/serve/api.py`'s `_upload_asset` in full for the exact contract:
  `POST /api/assets?dest=&name=&item=&expected_hash=` with raw bytes;
  `kind` is `"uploaded"` (200, carries `from_source`, `rel`, `hash`, `bytes`,
  `created`, `replaced`, `referenced_by`), `"conflict"` (409, carries `path`,
  `conflict`, `current_hash`, `current_size`, `referenced_by`), or
  `"refused"` (4xx, carries `refusal` — `"sealed"` / `"ambiguity"` /
  `"capture"` / plain — and `details`). Note the success payload's digest key
  is `hash`, not `digest`.
- `src/refdes/serve/static/images.js`, `editor.js`, `api.js`, `item.js`,
  `links.js` — the Phase 0 picker, the insertion callback
  (`insertIntoBody`, caret-aware, rides the one draft/save/revision path),
  and the token-carrying JSON-only `api()` helper.

## The existing conflict-screen convention I matched

`editor.js`'s `showConflict` is the only conflict screen in the shell (no
`drafts.js` involvement — the draft never knows about conflicts). Its
convention: a `div.conflict` box appended inside the edit block, hidden by
default; an `h3` heading; muted `p` lines; a `pre.conflict-diff` block for
the facts; and a `div.conflict-actions` row of `.btn` buttons (Keep mine /
Keep theirs / Copy my draft), with "Keep mine" re-issuing the save against
the server's fresh revision. `style.css` styles `.conflict`, `.conflict h3`,
`.conflict-diff`, `.conflict-actions`.

The binary variant reuses all of it — same `div.conflict` element, same
`conflict-diff`/`conflict-actions` classes — and changes only the content:
there is no diff of two PNGs (§8), so the `pre` block carries the facts an
author can compare (`there: <path>`, `there: <size>, <current_hash>`,
`yours: <name> (<size>)`, plus the §9.3 `referenced_by` blast radius when
non-empty), an explicit muted line saying there is no visual diff of two
binaries, and exactly two actions: **Replace** (re-POST with
`expected_hash=current_hash` — the re-issue *is* the confirmation, §15.7, so
no second modal) and **Cancel** (hide the box, keep the preview, write
nothing).

## Design points worth recording

- **Upload lives inside the Phase 0 panel**, not a new module: `createImagePicker`
  gains a drop zone + file input + preview row + conflict box below the list,
  so the panel `item.js` already places carries both halves. `editor.js` and
  `item.js` are untouched — the picker is already imported and placed, and
  the upload reuses its `insertIntoBody` callback.
- **`postRaw` in `api.js`**, not a bare `fetch` in the caller: the launch
  token stays api.js's alone ("the only place the browser talks to Python"),
  and the thrown Error carries `status` + `payload` exactly like `api()`'s,
  because the caller branches on `status === 409 && kind === 'conflict'` vs
  `kind === 'refused'`.
- **Preview before upload**: `FileReader.readAsDataURL` into an `<img>` on
  pick; the POST happens only behind the explicit Upload button. CSP is
  `img-src 'self' data:` (§11), so no server round trip and no new read
  endpoint. Listeners only — an inline `onerror`/`ondrop` would be a CSP
  violation and is caught by the existing static test anyway.
- **Refusal vs conflict**: the conflict box is opened from exactly one place
  (the 409 branch). A `kind: "refused"` payload — sealed included — renders a
  hard `.image-note.bad` line and never a Replace button; the sealed case
  says outright that no confirmation unlocks it. `sendUpload` is called with
  a server-supplied hash from exactly one call site (the Replace button),
  which the static test pins by count.
- **Default alt text** is the filename stem (§7): `stemOf("curve.png") →
  ![curve](<from_source>)`. The path inside the `![...]()` is the server's
  `from_source` verbatim — the client composes no path of its own, and the
  old "no `![` in the picker" pin was narrowed to "no `../`" plus an exact
  assertion of the one template that wraps `payload.from_source`.
- **The old `test_the_image_picker_uploads_nothing` is deleted**, deliberately:
  it pinned "Phase 1 must not arrive early" and Phase 4 has arrived. Six new
  tests replace it, one per §17 row-4 clause (wiring, preview, transport,
  insertion/alt, conflict variant, sealed hard-refusal).

## Gotcha found

`tests/test_serve_static.py::test_served_js_parses_as_es2020_modules` walks
the whole file with a naive string-state machine that does not strip
comments: an odd number of apostrophes or backticks *in comments* flips its
string state and swallows a `}`. Two rounds of that failure before every
apostrophe was out of the added comments. Worth remembering for any future
comment in served JS: keep apostrophes and backticks balanced per file.

## Gates

- `pytest -q -x` → 2542 passed, 2 skipped (full suite; only JS + the static
  test file changed on disk).
- `ruff check src/refdes/serve/static tests/test_serve_static.py --select I`
  → clean.
