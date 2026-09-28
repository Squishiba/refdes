- **`refdes --version` exists, and prints the version you actually have.**
  `-V` works too. It prints `refdes 0.5.0` — the version of the installed
  package, read from its own metadata, so it can never disagree with `pip show
  refdes` — and exits `0`. It needs no project, no config, and no subcommand,
  so it answers in an empty directory as readily as inside a project. Running
  from a raw checkout with nothing installed prints `refdes (version unknown
  -- not installed as a package)` instead of raising. Previously the flag did
  not exist at all: `refdes --version` fell through to the top-level usage
  dump and a non-zero exit, which left the docs telling you that a later
  `refdes` may write a higher `standard.version` than the one in your config
  with no way to ask which `refdes` you were holding. The stale hardcoded
  `refdes.__version__` (still `0.1.0`, three minor releases behind) is gone;
  `refdes.__version__` and `refdes.get_version()` now both read the installed
  metadata.
