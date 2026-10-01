- `refdes serve` now treats a `SIGTERM` as a clean stop, the same as Ctrl+C.
  Finding N4 of `in-prog-logs/user-sim-release-gate-run3.md`: `--token-file`
  exists so a script can read the launch credential instead of scraping stdout,
  and the ordinary scripted stop is `kill $pid` — a `SIGTERM` — which was the
  one signal nothing handled. So the one line the flag's own `--help` promised
  ("removed when serve stops cleanly") was true of Ctrl+C and false of the stop
  a script actually sends: a credential-shaped file holding a token that
  authenticates nothing stayed on disk after every scripted run. `kill $pid` now
  exits `0` and removes the file, as Ctrl+C does, and removes the preview temp
  directory with it. The handler is installed for that launch only, never at
  import, and it raises `KeyboardInterrupt` so the stop takes the one existing
  shutdown path rather than a second copy of the teardown. Only a signal that
  cannot be caught — `kill -9` — still leaves the file behind, and the next
  `--token-file` at that path rewrites it as before.
- On Windows this is unchanged, deliberately: `signal.SIGTERM` exists there and
  registering a handler for it succeeds, but nothing can deliver it —
  `Popen.terminate()`, `taskkill` and `os.kill(pid, SIGTERM)` all end in
  `TerminateProcess`, which no handler intercepts. So no handler is installed
  there (rather than installing one that provably cannot run), a Windows
  `serve` stopped that way leaves the file behind exactly as a hard kill does,
  and the new test is skipped on `nt` for the same reason the Ctrl+C clean-stop
  test already was. The `--help` text and the stdout line now name the two
  clean stops and the one that cannot be caught, on every platform.
