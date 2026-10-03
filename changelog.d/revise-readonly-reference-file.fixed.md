- `refdes revise` refuses the one read-only layout it was still renaming through:
  a single unwritable item file that holds **only a reference** to the item
  being renamed, while the renamed item itself sits in a writable sibling file.

  Every other read-only layout already rolled back — the whole tree, `items/`,
  a read-only subdirectory — because `apply()` writes the rename's own file
  rewrites through a hook that refuses on the first unwritable file. This one
  slipped past that guard for a structural reason: the read-only file holds no
  id the rename moves, so the rename's rewrite pass never plans a write for
  it. The display half of its `DISPLAY-ID@key` composite moves one step later,
  in the post-rename refresh, which went through the *load-time* write path —
  the one that degrades with a warning by design, because key minting and
  reference expansion are a normalisation nobody asked for.

  So the refresh dropped that file's planned rewrite, said nothing, and the run
  renamed ids in the writable files, left a structured composite naming the
  retired id, reported it as `1 prose mention(s) ... (a rename never edits
  prose)` — it was never prose, it was the reference the refresh was supposed
  to move — and exited `0`. `docs/cli-reference.md`'s destination table already
  promised a refusal and a full rollback here; this makes that sentence true
  for the last layout it was false for.

  The fix is the smallest one that reaches it: the post-rename refresh now
  refuses the way the rename's own writes do (`cannot write <file>
  (read-only tree?)`, exit `1`, whole transaction rolled back), and the
  `--dry-run` preview reports the same refusal instead of previewing a clean
  run. Load-time callers keep degrading exactly as before — minting a key on a
  read-only file is still a warning, not a failure.

  Exit code is unchanged (`1`); this is a refusal where there was a silent
  success, not a new code.