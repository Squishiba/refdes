**Byte uploads for the browser editor** (Phase 1, "Bytes" of
`docs/design/editor-image-upload.md`). `POST /api/assets?dest=<dir>&name=<file>`
-- or `item=<handle>` to default the destination to that item's own source
directory -- takes the raw bytes as the request body and writes one file: no
multipart, no base64, no metadata outside the query, no directory created,
nothing else touched. Both halves of the destination are validated on their
own (`security.safe_relative_parts` plus real-path containment, `.refdes/`
refused) and never joined as a client-supplied path. The type is read from
the bytes -- PNG, JPEG, GIF, WebP by signature -- and the extension has to
agree with what the sniff found; `.svg` refuses outright, because the only
thing between an uploaded SVG and a same-origin script is the preview's CSP,
and the client's `Content-Type` decides nothing. The §5 collision table is
four rows: absent writes, identical bytes are a no-op that still returns the
path and hash, different bytes refuse naming the existing file's path, size
and hash, and a name differing only in case from an existing file refuses
rather than producing two files no two checkouts agree on. Nothing is ever
silently renamed or suffixed, and the write underneath is `serve/edit.py`'s
`_atomic_create` -- create-must-not-exist -- so a destination that appears
between the check and the write is refused, not clobbered. The size cap
(`MAX_ASSET_BYTES`, 8 MiB) is enforced twice: against `Content-Length` before
a body byte is read, and against the bytes in hand. A successful upload forces
the preview rebuild rather than waiting for the debounced poller, and returns
`from_source` -- the path rewritten relative to the item's source file, which
is the exact spelling the editor inserts into the draft. The endpoint writes
bytes only: no `.md` or `.yaml` is touched, and the reference reaches disk
through the ordinary `set_body` save, so the existing gate is what rejects a
body naming a file that is not there. `serve/upload.py` is the new service;
the route rides the existing token, `Origin`, Host and `--no-write` gate. The
`expected_hash` replace path and the checks against other documents are
Phase 2, the sealed-target refusals Phase 3.
