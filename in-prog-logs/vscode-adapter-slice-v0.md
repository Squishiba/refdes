# Slice V0 — read-only hover and one deep link (VS Code adapter)

Task: `docs/design/editor-vscode-adapter.md` §8, "Slice V0 — read-only hover and
one deep link. (The slice that proves the token.)" Branch
`feat/vscode-adapter-slice-v0`. Status: **finished** — committed (`901a353`),
pushed, PR opened: https://github.com/Squishiba/refdes/pull/66. CI green on all
three jobs — `gh pr checks 66 --repo Squishiba/refdes --watch`: ubuntu-latest pass
4m0s, ubuntu-latest / py3.13 pass 4m28s, windows-latest pass 3m52s.

Scope held to §8's five bullets. No Python server code touched, no new server
flags, no webview, no writes.

## What landed

### `editors/vscode/serveClient.js` (new, ~300 lines, no `vscode` import)

§7.2 asks for exactly this shape — "a pure module with no `vscode` import so it is
testable without an extension host" — so everything about the process and the
token lives here and nothing in it needs an extension host to run.

- `LAUNCH_PREFIX = "refdes serve: "` and `parseLaunchLine(line)` /
  `parseLaunchUrl(text)`.
- `ServeClient.start()` spawns `<refdes.command> <configured args> -c <root>/refdes-project.yaml serve --no-open`
  with `cwd: root`, reads stdout line by line, and resolves `{base, port, token}`
  off the first line that parses. 30 s boot timeout; `child.on("error")` (ENOENT
  when `refdes` is not on `PATH`) and `close`-before-ready both resolve `null`
  rather than hanging. Never rejects — every caller is a hover.
- `ServeClient.attach(parsed)` for the pasted-URL path.
- `request(pathname)` — Node `http`, `host: "127.0.0.1"`, `X-Refdes-Token` header.
  `revision()` and `item(ref)` on top of it.
- `deepLink(key)` / `deepLinkForLog(key)`.
- `kill()` — `SIGTERM`, or `taskkill /T /F` on Windows because the child is spawned
  through a shell there and killing the child alone would orphan the Python
  process still holding the port.
- `redact()` keeps `?token=…` out of the output channel; it stops at `#` as well
  as at whitespace and `&`, so redacting a deep link leaves its fragment.

### `editors/vscode/extension.js`

- `itemMarkdown(item, view)` — the existing hover body, unchanged, plus
  `appendSnapshotFacts(md, view)`: coverage stage, check state (the server's own
  `none`/`pass`/`unknown`/`fail` rollup) and the item's attributed diagnostics.
  Where both paths speak about coverage, the snapshot's answer is the one the
  single `_coverage:` line shows, so one hover never shows two stages for one item
  (§6 Q3).
- `hoverProvider.provideHover` is now `async` and awaits `serveItemView(id)` —
  which waits on the boot for at most `HOVER_SERVE_WAIT_MS` (1500 ms) so a
  booting server can never make a hover hang; the boot continues in the background
  and the next hover gets its facts.
- `codeLensProvider` — one lens per `id:` line, `Open in editor`.
- `commandOpenInEditor`, `commandAttachServer`, `commandShowServerLog`.
- Serve lifecycle: `startServe` / `ensureServe` / `serveItemView` /
  `pollServeRevision` / `handleServeForbidden` / `onServeExit` / `stopServe` /
  `setServeState`.
- Second status bar item (priority 90, so it sits right of the existing one) with
  the four §8 states; its command shows the output channel.
- `deactivate()` kills the child.

### `editors/vscode/package.json`

Three contributed commands; `refdes.openInEditor` is hidden from the command
palette (`"when": "false"`) because it only makes sense with a CodeLens argument.

### `editors/vscode/README.md`

New "Live snapshot" section (the four status states, on-demand lifecycle, token
policy, attach flow); hover and commands table updated; "How it works" no longer
claims one fetch path.

### `tests/test_vscode_extension.py`

Four more textual tests, described under Verification below.

## The token: which method, and why

**§3.2 option 1 — parse the launch URL off the child's stdout — as the recommended
default, with option 2 (paste the launch URL) as the fallback.** Both converge on
one `ServeClient` holding `{base, port, token}`, per §3.1.

The design doc's decision is not marked unresolved anywhere: §3.2's table marks
rows 1 and 2 **Recommended**, rows 3–5 **Rejected**, and §6 Q2's recommendation
spells the same pairing ("the extension spawns `refdes -c <config> serve --no-open`
lazily … plus a `Refdes: Attach to running server` command that takes a pasted
launch URL. No new server flags."). Q1 (HTTP vs the CLI/RPC bridge) is likewise
answered — HTTP — and §9.4 keeps the stdio bridge rejected. So there was nothing to
re-derive and nothing open to guess at.

Verified against the real CLI rather than from the doc's citation: `cmd_serve`
(`src/refdes/cli.py`) prints, as its first line, flushed —

```
refdes serve: http://127.0.0.1:34271/?token=JxnbztOg2aLWzzOMdXGJyz0ksZNFOGXSADDmn5csgC0
```

— followed by two banner lines. That is the line `parseLaunchLine` parses, and the
port is never cached (§3.2: "never cache the port").

The token is held in the `ServeClient` object in the extension host's memory, is
sent only as `X-Refdes-Token`, is never in argv, never on disk, never in a setting,
and never in the output channel (`redact()` on everything the child prints).

## The one place the deep link departs from §8's literal text

§8 says the CodeLens "opens `…/edit/#/items/<key>`". Opening that bare URL in an
external browser gets a **403**: `/edit/` is a navigable surface authenticated by
an `HttpOnly` `SameSite=Strict` cookie that only the launch URL sets
(`serve/security.py:8-11`, `serve/server.py:_dispatch`/`_start_session`) — verified,
not inferred:

```
no cookie and no token is a 403   PASS   403
```

§3.3's own last row resolves this in the same breath as the deep link ("the launch
URL's `?token=` sets the cookie and strips itself"), so the extension opens

```
http://127.0.0.1:<port>/edit/?token=<t>#/items/<key>
```

and the server answers `302 → /edit/` with `Set-Cookie: refdes_token_<port>=…`,
leaving the address bar carrying nothing. Confirmed against a live server:

```
deep link sets the cookie and strips the token  PASS
  {"status":302,"location":"/edit/","cookie":"refdes_token_55889=…; Path=/; HttpOnly; SameSite=Strict"}
```

The browser keeps the `#/items/<key>` fragment across the redirect, which is what
the editor's hash router (`serve/static/app.js:2`) reads.

## Verification

- `node --check editors/vscode/extension.js` → OK.
  `node --check editors/vscode/serveClient.js` → OK.
  `python -m json.tool editors/vscode/package.json` → valid.
- **End-to-end against the real server, no extension host** —
  `.scratch/drive_serve_client.js` drives `serveClient.js` for real
  (`python -m refdes.cli -c refdes-project.yaml serve --no-open`, spawned by the
  module itself). All 14 checks pass: launch line parses; a banner line is not
  mistaken for it; `localhost` rewritten; a URL with no token or a non-loopback
  host refused; `redact` hides the token; boot succeeds; `GET /api/revision` →
  `{"serial":1,"stale":false}`; **a wrong token → 403**; `GET /api/item/BND-THM-001`
  → 200 with 25 keys; deep link shape; the cookie handshake above; bare `/edit/`
  → 403; `kill()` leaves no child. This is the "does the extension host talk to
  this API correctly" question, answered against the real thing.
- `.scratch/probe_hover_facts.py` checked that the three hover facts are real and
  non-trivial in the sample project, and found the edge cases the renderer had to
  handle: `coverage` is `null` for items with no coverage record (`DEC-PWR-001`,
  `CMP-PWR-001`), and `diagnostics[].level` has a **third** value, `info` — the
  first cut of the renderer mapped everything-not-error to a warning icon, which
  is now `$(error)` / `$(warning)` / `$(info)`. `DEC-PWR-001` is the interesting
  hover: `check=fail`, 2 checks, 1 attributed error.
- `pytest -q tests/test_vscode_extension.py -v` → 5 passed. The four new ones:
  - `test_hover_still_renders_the_index_body_and_adds_the_snapshot_facts` — the
    hover body is still `itemMarkdown(item, view)` and still handed to
    `new vscode.Hover(...)`, and each of `coverage` / `check` / `diagnostics` is
    asserted on **both** sides: returned by `_item_view` in `serve/api.py` and read
    off `view.<fact>` in the JS. That is the cheap version of §7.2's
    `test_hover_facts_come_from_the_api_not_a_local_guess`.
  - `test_serve_client_and_the_cli_agree_on_the_launch_line` — the literal
    `refdes serve: ` extracted from `cli.py`'s `print(f"refdes serve:
    {app.launch_url}"` must equal `serveClient.js`'s `LAUNCH_PREFIX`. Two sides of
    one string, so a CLI change fails in CI instead of silently emptying every
    hover.
  - `test_the_token_travels_only_in_the_header_the_server_checks` — the header name
    comes from `security.py`'s `TOKEN_HEADER` and must appear in the client; no
    `--token` anywhere in the client; the spawn argv is exactly
    `this.args.concat(["serve", "--no-open"])`; requests dial `host: "127.0.0.1"`
    and never `host: "localhost"`.
  - `test_no_direct_item_file_writes_in_extension_source` — §7.2's named test.
    Greps every `editors/vscode/*.js` for `applyEdit` / `WorkspaceEdit` /
    `fs.writeFile` / `fs.appendFile` (+ `Sync` variants), skipping comment lines so
    the prose in `extension.js:15` that *names* the ban doesn't trip it.
- `ruff check tests/test_vscode_extension.py` → All checks passed.
- Full `python -m pytest -q` (repo root) → **2541 passed, 2 skipped in 183.81s**.
  No Python source changed, so this is a no-regression gate, not a test of the
  change.

## Difficulties and judgement calls

1. **The deep link's token** — the §8 text and the shipped cookie model disagree,
   and §3.3 is the tie-breaker. Recorded above rather than silently resolved.
2. **When to boot.** §6 Q2 says "lazily on first refdes feature use". Hover is the
   V0 feature, so the first hover on an ID asks for the server; activation does
   not. That keeps a window that only ever runs `refdes build` from the palette
   from paying a Python process and a whole project build, and it means the status
   bar legitimately reads `no server` until something asks. The hover waits at
   most 1.5 s for a boot that may take seconds, so the first hover shows the old
   body and the next one shows the facts — a visible ramp, not a hang.
3. **Two fetch paths, one fact.** Coverage stage is in both payloads. The snapshot
   wins for the single `_coverage:` line and the snapshot block names its own
   source (`From refdes serve · snapshot serial N`), which is what §6 Q3 asks for
   ("the choice is visible in the status bar").
4. **403 handling.** §3.2 wants "retry the handshake once (respawn), then say so".
   Implemented with a one-shot counter, because a 403 that survives a respawn is
   not transient and an unbounded respawn is a boot loop wearing an error message.
   For an *attached* server there is nothing to respawn, so it says so and offers
   "Attach again".
5. **Liveness of an attached server.** No child to watch, so the 5 s
   `GET /api/revision` poll is its liveness check — which is also what keeps
   "snapshot serial N" honest. §3.3 says to poll it; the interval is the only new
   timer, cleared on deactivate.
6. **Windows kill.** `shell: true` on win32 (matching the existing `run()` helper)
   means `child.kill()` would leave the Python process holding the port, so
   `kill()` uses `taskkill /T /F` there. Not exercised — no Windows runner in this
   session — but it is the same four lines every Node tool that spawns through a
   shell uses, and it is called out here as unverified-on-Windows.

## Not done (out of scope, by instruction)

- No webview, no sidebar (`WebviewViewProvider`) — Slice V1, "only if V0 earns it".
- No writes, no `POST` from the client at all. Consequence worth naming: §3.2's
  "the client sets `Origin: http://127.0.0.1:<port>` explicitly on every mutation"
  has no code to live in yet, because V0 has no mutations. It lands with the first
  slice that POSTs, and §7.1's two Origin tests already pin the server's side.
- No Python server change of any kind, and no new server flags.
- §7.1's contract tests (`test_serve_prints_launch_url_as_first_stdout_line`, the
  Origin pair, `test_deep_link_shape_matches_server_toolbar`, …) and §7.2's
  `tests/test_vscode_extension_http_client.py` are not added here. The scratch
  driver in `.scratch/drive_serve_client.js` is the shape that file would take, and
  promoting it into `tests/` with a live `EditorApp` fixture is the obvious next
  test-side commit; the four textual tests above are the ones that cost nothing.
