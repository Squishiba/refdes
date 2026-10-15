- `init`: a `.gitignore` in the project directory that `init` cannot
  use — a directory (or symlink) wearing the name, non-UTF-8 bytes, a
  file the process cannot read, or a read-only file that is missing a
  pattern `init` wants to append — now refuses with a named
  `configuration error` at exit 2 and creates no files at all. These
  shapes used to escape as raw tracebacks, and the directory and
  read-only shapes left `refdes-project.yaml` and
  `.vscode/settings.json` behind, a half-created project whose orphaned
  config made every retry refuse to overwrite it. A read-only
  `.gitignore` that already covers every pattern `init` wants needs no
  append and still inits, as before.
