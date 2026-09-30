- **`refdes serve` takes `--port PORT`.** It binds that exact `127.0.0.1` port
  instead of the ephemeral one the OS used to choose — still loopback only,
  still no host argument and no remote mode, and every `Host`/`Origin`/cookie
  check follows the port actually bound. A port something else holds is a
  refusal, not a crash: one line — `error: cannot listen on 127.0.0.1:8731:
  Address already in use -- something else holds it, or a launch that stopped a
  moment ago still has sockets closing on it; choose another --port, or drop
  --port to get an ephemeral one` — and exit `2`, never a traceback out of
  `socket.bind()` and never a silent fallback to a neighbouring port (a script
  that asked for 8731 and got 8732 is the quiet failure). `--port` outside
  1–65535 is a usage error and exit `2` at parse time, because Python raises
  `OverflowError`, not `OSError`, for a port over 65535. `allow_reuse_address`
  stays `False`, so a port a launch gave up a moment ago can report busy while
  its sockets finish closing, which the message says rather than leaving you to
  guess.
- **`refdes serve` takes `--token-file PATH`.** It writes this launch's URL to
  `PATH` — the whole URL, newline-terminated, exactly the string the stdout line
  carries, not the bare token, so it names the port too and is what
  `editors/vscode/serveClient.js` `parseLaunchUrl()` already parses. A script
  reads the credential from the file and needs no stdout scrape: that retires
  the trap finding F8 names, where the token's urlsafe-base64 alphabet (43
  characters of `A-Za-z0-9-_`) is silently truncated by a `[0-9a-zA-Z-]+` regex
  and the resulting 403 reads like an auth bug rather than a scraping bug. The
  file is a bearer credential and is treated as one: created `0600` with the
  mode set on the descriptor, so a pre-existing world-readable file at that path
  is tightened rather than kept; `O_NOFOLLOW`, so a symlink there is refused
  with exit `2` instead of written through; removed when `serve` stops on
  Ctrl+C, because the token dies with its launch. A hard kill leaves the file
  behind holding a token that authenticates nothing, and a later `--token-file`
  at the same path truncates and rewrites it rather than refusing to start.
  Putting it inside the project tree is your call and a bad one — `--no-write`
  does not gate this write, because it is not project state.
- Persisting the launch token is what `docs/design/browser-editor.md` (Security)
  says never to do and `docs/design/editor-vscode-adapter.md` §3.2 row 3 weighs
  and rejects; this is that rejected option, taken deliberately, per launch and
  only for whoever passes the flag. Two consequences of that are pinned by
  tests: `serve` now disables argparse abbreviation, because `--token` is a
  prefix of `--token-file` and `refdes serve --token=…` being accepted as
  `--token-file=…` would have quietly undone §3.2 row 4 ("no flag can carry a
  token") — `tests/test_vscode_adapter_contract.py` caught precisely that before
  it shipped — and `tests/test_serve_cli.py` drives the real process to pin the
  fixed port, the busy-port exit `2`, the file's `0600` mode, a token read from
  the file working against `/api/revision` where a tokenless request gets 403,
  the symlink refusal, and the file's removal on a clean stop.
