- `refdes keys restore` no longer falsely refuses a batch that restores a
  linked pair of lost keys together. The baseline content comparison hashed
  each supplied item against the *pre-restore* project, where the link target
  was still keyless, so the owner's hash carried the `!nokey:`/`!unresolved:`
  sentinel where the baseline recorded the target's key -- an untouched item
  looked edited and the restore demanded `--force` (the target's own restore
  always passed, so restoring the target first, then the owner, worked). The
  comparison now runs on the proposed post-restore project: the same item,
  unedited, passes in either argument order, and a genuine content difference
  in either half of the pair is still refused, writing nothing.
