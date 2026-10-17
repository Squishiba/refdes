- `serve`: a creation whose id reservation failed no longer destroys the
  destination file. The create appends read the destination as text, and
  the rollback that runs when `ids.reserve_id` fails afterwards handed
  that decoded text to a binary write: the old in-place restore opened
  the file `"wb"` -- which truncates it to zero bytes *before* the write
  -- so the write raised `TypeError` past the restore's `except OSError`,
  out of `create_item` where the contract says it returns a result, and
  the items file was left empty. The rollback payload is the raw bytes
  now, and the restore stages them in a temp file and swaps them in
  atomically, so a restore that itself fails -- a full disk hits the
  reservation and the restore alike -- leaves the destination exactly as
  the restore found it instead of truncating it (what is on it is what
  the last writer put there; a writer that bypasses the write lock may
  have changed it in the interim), and the refusal says the bytes
  `could not be restored` rather than claiming a rollback that did
  not happen. A failed creation burns nothing; it now also destroys
  nothing. The check-vs-replace window tracked by EDITOR-API-007 is
  untouched here (it remains held in PR #241).
