**Image upload conflicts against other documents** (Phase 2, "Conflicts" of
`docs/design/editor-image-upload.md`) — the phase that closes the hole Phase 1
shipped open, because an upload is not a local operation: a new file can make
an unrelated document ambiguous, can capture a bare-name reference another item
already resolves, and a replace changes what every referring item shows.

`POST /api/assets` now takes `expected_hash` — the binary `expected_revision`.
The client re-issues with the hash the last response returned and that *is* the
confirmation; the bytes then go down through `serve/edit.py`'s `_atomic_replace`
(temp, fsync, `os.replace`, re-read, compare, restore on disagreement) inside
the same project write lock the create path holds, and the response says
`replaced` rather than `created`. A hash that no longer matches is a 409
carrying the **current** hash, so the client can re-fetch and decide again; a
hash for a file that is gone is a 409 too, never a quiet downgrade to a create;
a malformed hash is a 400, because a value that could never match is a typo
rather than a conflict. There is no diff of two PNGs: the conflict names path,
size, both hashes and who is looking at it.

Two refusals, both computed before the write from what the *build* already
decided, never from a re-derivation of the rule:

- **§9.1 ambiguity** — a write that would put a second file with that leaf on
  the `site.assets:` search path is refused, naming both paths. The condition
  is the build's own: `build._search_image_matches` would return more than one
  candidate afterwards, and more than one is a build error naming every
  candidate, not a tie-break. A destination that is not on the search path —
  which is §4's default — cannot trip it.
- **§9.2 capture** — a write that would silently re-point an existing bare-name
  reference is refused, naming each affected item, its source file, and what
  its image resolves to right now. A src that resolves beside its own source
  file always wins over the search, so nothing would error: the page would just
  show a different picture. The check reads `Project.image_results`, the
  per-item resolution the last build already recorded.

A **replace** additionally discloses §9.3's blast radius: the 409 the author
reads before confirming, and the 200 after, both carry `referenced_by` — every
item whose body currently resolves to the file, with its source file and the
srcs as written. A disclosure, not a refusal: an author who re-shoots a
diagram expects every document using it to change. Refusing a replace of a file
a *sealed* entry references is §10, and is still Phase 3.

`serve/upload.py` now takes the built `Project` rather than a root path, since
the checks are questions about what the build resolves; `serve/api.py` passes
the snapshot's project and maps the new fields (`conflict`, `current_hash`,
`current_size`, `referenced_by`, `refusal`, `details`). Nothing about a client
that does not send `expected_hash` changes.
