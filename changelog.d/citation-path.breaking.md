- A citation's `url:` field is now `path:` — one field for "where the
  document is", dispatched on scheme. `http`/`https` means remote, fetched
  and hashed exactly as before; anything else means a file inside the
  project, relative to the project root (the directory holding
  `refdes-project.yaml`), slash-separated. A local file is pinned by
  `refdes fetch` reading it from disk (no network), re-hashed at every
  build, and published with the site as a content-addressed copy at
  `assets/citations/<sha256><ext>` so the rendered link points at the bytes
  the pin vouches for. A local file that changed since it was pinned is a
  warning naming every item that cites it (an error under
  `--require-citations`); a cited local file that doesn't exist is an error.
  Absolute paths, drive letters, backslashes, `..` escapes, symlinks out of
  the project, and `keep_copy:` on a local path are refused, never guessed.
  `refdes fetch --url` is now `refdes fetch --path`. A stale `url:` fails
  validation with a message naming the rename; `refdes standard upgrade
  --to 3` rewrites hardware@2 content automatically, and the lockfile needs
  no migration (remote keys always carry `http(s)://`).
