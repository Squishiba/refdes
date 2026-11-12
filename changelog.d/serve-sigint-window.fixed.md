- `serve --token-file` Ctrl+C race: the launch file is now written only
  once a clean stop is armed, so Ctrl+C the instant the file appears stops
  cleanly. `--token-file` is documented as "removed when serve stops cleanly --
  Ctrl+C or SIGTERM", and a scripted client's readiness signal is the file's
  existence (`until [ -s file ]`). Serve used to write the file at construction,
  *before* it entered the `try/except KeyboardInterrupt` that turns Ctrl+C into
  an exit 0. A SIGINT landing in that gap is an uncaught KeyboardInterrupt, and
  CPython's top-level behaviour for one is to re-raise SIGINT with the default
  action: the process died by signal 2 (returncode -2) and left the bearer
  credential on disk. The window is real and narrow -- a stress loop reproduced
  it at ~3% under CPU contention (10/300, token left behind every time), which is
  how `test_token_file_is_removed_when_serve_stops` failed on main's CI (run
  42651482508). The write now happens inside the guard, so "the file exists"
  always means "Ctrl+C is safe". After the fix the same 300-run stress finished
  0/300 signal-kills and 0/300 credentials left behind.
