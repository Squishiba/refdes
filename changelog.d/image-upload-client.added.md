Image upload in the browser editor (docs/design/editor-image-upload.md §17
Phase 4, "Client"). The image panel gains a drop zone and a file input: drop
or pick a PNG/JPEG/GIF/WebP and the author sees the exact bytes as a
browser-built `data:` preview -- the editor CSP already allows it -- before
anything is sent. Pressing Upload posts the raw bytes to `POST /api/assets`
through a new `postRaw` in api.js (metadata in the query, the launch token
still api.js's alone; no multipart, no base64, §11), and on success the
server's `from_source` spelling is inserted into the body draft as
`![stem](from_source)` -- default alt text from the filename stem, §7 -- to
reach disk through the ordinary Save, the ordinary revision check, and the
ordinary delta gate. A 409 conflict opens the editor's own conflict-box
convention in binary form: no diff of two binaries, but the facts to compare
-- path, current size and hash versus the picked file -- plus the §9.3 list
of items a replace would change, and two actions: Replace (re-issue with the
returned hash as `expected_hash`, which §15.7 makes the confirmation) or
Cancel. A refusal -- including §10's sealed refusals -- is shown as a hard
stop with the server's reason and never a confirmable replace, because no
`expected_hash` unlocks a seal.
