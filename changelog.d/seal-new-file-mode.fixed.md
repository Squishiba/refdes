- Seals: the *first* seal file a project writes (`.refdes/log-seal.yaml` on
  the first sealing build) now gets the same file mode a plain write would
  give it — the umask default — instead of the private 0600 its temp file was
  created with. A rewrite has always carried the existing file's mode over,
  but with no earlier seal file there was nothing to carry, so a group-shared
  project (umask 002) got a `.refdes/` where `schema.json` and the write lock
  were group-readable and the one file holding the append-only guarantee was
  not. The seal file's own mode is still left exactly as it was by any
  rebuild, deliberate or not.
