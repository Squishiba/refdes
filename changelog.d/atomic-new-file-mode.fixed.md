- Atomic writes: a file created *new* by the shared atomic-write helper
  (`textio.atomic_write_text`) now lands at the umask default a plain write
  gives it — 0644 under umask 022, 0664 under 002 — instead of the private
  0600 its temp file was created with. A rewrite has always carried the
  existing file's mode over, but with no earlier file there was nothing to
  carry: `refdes id` in a fresh project wrote `.refdes/ids.yaml` at 0600
  beside a 0644 `.refdes/schema.json`, and a group-shared tree (umask 002)
  got an id ledger the group could not read. Same fix as the seal file
  (PERM-OWNER-001) on the helper every id/preset/rename write shares; the
  temp is now created `O_CREAT | O_EXCL` at 0666 so the kernel applies the
  umask, and no caller of the helper creates a file it intends to be
  private (the serve token file, which does, writes through its own path
  and keeps its 0600).
