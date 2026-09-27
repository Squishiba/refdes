**Image upload refuses where a seal is involved** (Phase 3, "Seals" of
`docs/design/editor-image-upload.md` §10) — the two refusals that turn §9.3's
*disclose and let the author confirm* into a flat no, because what is protected
is not the author's ownership of a file but a sealed record's immutability.

A seal hashes an entry's fields and its normalized body text, and the body text
of an entry with an image contains `![alt](path)` — the **path**, not the bytes
behind it. So the bytes a sealed entry points at sit outside everything the seal
protects while being the one thing that decides what the sealed page shows. The
build side of that already shipped: `HASH_FORMAT` 5 folds each referenced
image's resolved path and digest into the entry's hash, so a hand edit to the
file moves `content_hash` and the existing modified-since-sealed error fires.
This is the editor side, which ships independently of it.

`POST /api/assets` now refuses in two places, both before a single byte is
written, both inside the project write lock:

- **An upload *for* a sealed entry.** The request already carries the item it is
  for, and that item is now checked with `seal.is_sealed` — the exact predicate
  `apply_edit` applies to a body save under the same lock, so the two refusals
  cannot disagree about which entries are frozen. The body edit that would
  reference the image is itself refused, so any bytes written here could only be
  an orphan on an entry that can never take the reference. An explicit `dest`
  elsewhere does not launder it: the reference still has to reach that entry's
  body. An append-only entry that no build has sealed yet is not frozen and
  takes the upload normally.
- **A replace, or a create, of a file a sealed entry references.** Replacing the
  file behind a sealed entry's image would change what that record displays
  while its hash still verifies — the audit trail says untouched, the page shows
  a different picture. Creating a file at a path a sealed entry's bare `src`
  would capture is the same damage by way of §9.2's relative lookup winning.
  Both refuse, **naming the sealed item**, its source file, and the src as
  written.

No `expected_hash` buys either write back, which is why these are 422 refusals
rather than 409 conflicts: a conflict is a question, and there is no answer here
that lets the write proceed. Re-uploading the **identical** bytes stays the §5
no-op it has always been — nothing about what any sealed page displays changes,
so there is nothing to refuse. A replace with no sealed referrer is unchanged:
still a confirmable 409 with §9.3's `referenced_by` disclosure, whose rows now
also carry a `sealed` flag — the same field the refusal is decided on, computed
the same way, so the disclosure and the refusal cannot disagree about who is
looking at the file. A sealed refusal's `details` carry every referrer, sealed or
not: the message names the entries that are the reason, and the blast radius is
still worth seeing.

`serve/upload.py` gained `_sealed_target_refusal`, `_sealed_replace_refusal`,
`_sealed_capture_refusal` and `_mark_sealed`; `store_asset` takes the item the
upload is for, and `serve/api.py` passes the request's `item` through. Nothing
about a client that never touches a sealed entry changes. §10 also says *delete*:
this endpoint deletes nothing (§11), so that half has no editor surface to
refuse yet, and the rule is written into the module docstring so the next
endpoint that removes a file knows it applies.
