# User-simulation release gate — run 17

Branch `user-sim-run17`, head `86c0d043` (includes #475 docs gaps, #476 navis
note, #477 save-seam polish, #474 save seam, #473 id-less tip, #472 VS Code
Navis). Base for "what shipped since": `9f15af87`. Simulated as a plain user:
docs/ pages followed literally, CLI + a real browser (Chromium, Firefox
parity), probe projects under `.scratch/`. No fixes made. Full suite at base:
`6419 passed, 2 skipped in 110.46s` (evidence `pytest-tail.txt`).

Headline:

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| 1 | Medium | `refdes serve` task pane | After Discard, Save stays visible with zero pending ticks — a stale pane state that invites a no-op click |
| 2 | Low (docs) | `docs/upgrading.md` step 1 | "no longer loads" is true only when no ancestor directory carries the project marker; a nested probe silently loads the ancestor project, and the legacy error never fires |
| 3 | Cosmetic | conflict panel | Conflict rows list ticks where your value already equals the file's — noise when the change came from other fields |
| 4 | Low (Unconfirmed) | save on read-only file | File-mode-only read-only (0444) does not block a save — the atomic rename replaces the file; only a read-only *directory* refuses. Docs never say which the "read-only" guarantee means |

Counts by severity: **Medium 1, Low (docs) 1, Low (Unconfirmed) 1, Cosmetic 1**.

Every backticked span below is greppable in `user-sim-run17-evidence/`
(the check: `claims-check.txt`, produced by `claims-check.py`).

## 1. The tick-pane save flow (docs: cli-reference serve section, thread workbench)

Chromium 141 via puppeteer-core, Firefox via playwright-core, on the same
writable `refdes serve` (launch record in `serve-cli-battery.txt` section 0,
token redacted). Evidence: `flow-a-save.json`, `flow-c-firefox-save.json`,
`flow-a-capture-once.txt`.

- Opening the pane shows the note verbatim: `Preview: ticking a row changes
  this page only -- nothing is saved.` Ticking a row reveals Save and
  Discard (`saveVisible: true`, `discVisible: true`), Save is gone again
  once the draft empties (after Discard: `pending: null`).
- The draft survives a page reload (`A4_draft_after_reload` still names the
  ticked task; `saveVisible: true`); the pane starts closed after reload
  (`A3_pane_closed_after_reload: true` — progressive enhancement holds:
  content is the page's own).
- Leaving the page with a draft fires the before-unload prompt in both
  browsers (`A5_leave_prompt_fired: true`).
- **Save applied**: the page lands on the new tip — pane `tipKey:
  mhdpx3wdms4`, viewing `LOG-A-004 2026-08-09 — Buck selected; copper model
  outstanding.`, the tick note back (`Preview: ticking a row changes this
  page only -- nothing is saved.`), Save gone (`saveVisible: false`). The
  entry sits in `items/board-a/log.yaml` (`- id: LOG-A-004` with a fresh
  key, author, date, tasks) — the file text is recorded in
  `edge-stale-revision-409.json`'s `current_text`, whose continuation
  entries name their tip via the composite form, e.g.
  `follows: [LOG-A-005@y6waecbfk3p]`.
- After the save, `refdes thread LOG-A-004` announces
  `Snapshot Captured: LOG-A-003 (followed by later entry)`, and
  `.refdes/history/events/` holds exactly one event per captured
  predecessor: `events dir: 10 file(s); events naming "followed": 10`,
  with the thread's predecessors `LOG-A-003` through `LOG-A-012` (the ten
  continuations written by the pane) each announcing one (`flow-a-capture-once.txt`).
- **Finding 1 (Medium)**: after clicking **Discard** the status indicator
  clears (`pending: null`), and `discVisible: false` — but **Save** stays
  visible (`saveVisible: true`), with one row still `tick: true` in
  Chromium and the same in Firefox (`A6_after_discard` in both files). A
  click on that Save with no draft is a no-op. The visibility recompute
  listens for `change`; Discard resets the checkboxes programmatically,
  which fires no `change` event.
- A tick on a tip whose thread has an *older* page entry shows the workbench
  viewing line `viewing LOG-A-001 · tasks as of tip LOG-A-013` — the pane's
  task list is always the thread tip, matching the docs (`serve-cli-battery.txt` 8).

## 2. The conflict flow (docs: "a changed file opens the keep-mine/keep-theirs/copy-it-out conflict panel")

Evidence: `flow-b-conflict.json`, `flow-b-copyout.json`,
`flow-b-copyout-verify.json`, `flow-b-keepmine-late-tick.json`,
`edge-stale-revision-409.json`, `api-continue-400.txt`,
`flow-c-firefox-conflict.json`.

- Change the file on disk behind an open page with a draft: the page
  auto-reloads, the draft survives with the stale clause
  `1 unsaved tick made against an older version - saving will ask to
  resolve`, and Save stays visible (`saveVisible: true`).
- Saving the stale draft is refused with the panel text
  `conflict: items/board-a/log.yaml changed since this edit was planned
  (expected 39d6480c8739, found 6ff5f07d9d44)` plus per-task rows
  (`T-thermal-model: yours -, the file has done`) and the three outcomes.
- **Keep mine** re-stamps the draft onto the new revision: the panel's
  revision becomes the file's (`panelRevision` equals the new
  `newRev`, `6ff5f07d9d44`), the draft survives (`1 unsaved tick`), the
  panel closes. Ticks added *while the panel stood open* are kept:
  `K3_late_tick_status: 2 unsaved ticks` and after Keep mine status
  `2 unsaved ticks` with all three rows checked
  (`flow-b-keepmine-late-tick.json` — #477's polish, verified).
- **Keep theirs** discards the draft: status `null`, Save hidden
  (`saveVisible: false`) — nothing written.
- **Copy it out** replaces the panel with a read-only transcript
  (`readOnly: true`): `Tick draft made at e3f4468c40a1…, the file is now
  at 4b73ac03b4dd…: T-demco: open` (a headless clipboard refuses to write; the
  transcript stands — #477's polish). Re-running the step
  with the real sha256 check: `file_unchanged_by_copyout: true` — clicking
  Copy it out writes nothing (`flow-b-copyout-verify.json`).
- Server-side, a stale-revision POST 409s with the
  `expected_revision`/`current_revision`/`current_text`/`diff` fields
  (`edge-stale-revision-409.json`); the pane's three outcomes sit on top of
  it. The pane is the only writer UI; the API body field is
  `expected_revision` (the 400 names it: `expected_revision is required:
  the file_revision from GET item<ref>`; the `ticks` body is
  `[id, state]` pairs, `api-continue-400.txt`).
- **Finding 3 (Cosmetic)**: rows where your tick equals the file (`T-demco:
  yours open, the file has open`, `flow-b-copyout.json` C3) are listed as
  if in conflict.
- The Firefox twin (`flow-c-firefox-conflict.json`) reaches the same
  states: the stale clause line, the panel
  (`expected 266189643ddd, found 5926e672f543`), Keep mine re-stamping —
  the recorded `panelRevision` after Keep mine equals the new file
  revision (`5926e672f543…`), exactly Chromium's outcome. The extra key
  `B6_warn_rev: "panel rev never became rev1"` in that file is the runner
  script's own sentinel string (a stale expectation variable that was
  never overwritten), not an observed panel state.

## 3. Edge cases

Evidence: `edge-idless-nowrite-sealed-subdir.json`,
`edge-fork-tab-save.json`, `refdes-thread-fork.txt`,
`edge-fork-endpoint-422.json`, `edge-idless-endpoint-422.json`,
`edge-readonly-tree.json`, `edge-file-0444.json`, `edge-crlf.json`,
`edge-unicode-path.json`, `edge-nowrite-note.json`, `edge-subdir-serve.txt`,
`edge-stale-revision-409.json`, `serve-cli-battery.txt`.

- **Id-less tip (key, no `id:`)**: the pane renders, the checkbox works as
  preview, the status says `ticks on this tip are preview-only - nothing is
  saved`, and the panel carries no save context (`tipKey` null, `revision`
  empty; the pane reads `data-refdes-tip-key` and `data-refdes-revision`
  from the panel element, `code-quote.txt`). `POST /api/item/<key>/continue`
  refuses naming the key: `refused: no item 'k7f3q2x8d0f' in this project`
  — the empty-subject text is gone.
- **Forked thread**: `refdes thread` reports
  `Thread: LOG-F-001  (forked: tips LOG-F-002, LOG-F-003)`; the pane shows
  one tab per open tip (`["LOG-F-002", "LOG-F-003"]`), each tab's heading
  names its own tip (`Tasks at LOG-F-002:`), and drafts are per-tab:
  ticking on the LOG-F-003 tab relabels it `LOG-F-003 (1)` with status
  `1 unsaved tick` while the other tab's status stays null, and the draft
  is intact on returning to the tab. Save on such a tab is **refused**:
  the pane posts for that tab's tip and the response names the thread —
  `refused: rywker3d74h's thread is forked across tips LOG-F-002, LOG-F-003:
  a continuation names one tip, and this request cannot pick one` — and the
  draft is kept (`1 unsaved tick` after the refusal). A POST naming a tip
  whose thread is forked (an entry in the middle) refuses the same way,
  naming both tips: `refused: dwz1zj7bxhm's thread is forked across tips
  LOG-F-002, LOG-F-003: …` (`edge-fork-endpoint-422.json`).
- **`--no-write`**: pane opens with its viewing line
  (`viewing LOG-A-004 · tasks as of tip LOG-A-011`), **no tick checkboxes
  at all** (`checkboxes: 0`), no Save (`saveInDom: false`); the served
  page loads `preview.js` — not `taskpane-ticks.js` (`edge-nowrite-note.json`).
- **Sealed tip** (hardware@3: the log type keeps the engine default
  `sealing: build`, `code-quote.txt`): Save
  is offered after ticking (status `1 unsaved tick`, `saveVisible: true`
  *before* any Save click, `S2_after_tick_before_save`), then refused with
  `refused: LOG-A-006 is a sealed append-only entry: a continuation appends
  a new entry, it never rewrites a sealed one` — names the tip and the
  remedy; the draft is kept (`status_after: 1 unsaved tick`, same rows
  checked, `edge-sealed-save.json`).
- **Two-tab conflict**: the browser repro crashed headless Chromium's
  renderer three times (unload-prompt + dual-target navigation); same-code
  path verified as the stale-revision 409 above (the pane behaves as in
  section 2, which was browser-tested with a disk change between).
- **Read-only tree** (API-level, the pane's own endpoint): `chmod 0555`
  on the item's directory refuses — `refused: the write failed ([Errno 13]
  Permission denied: 'items/board-a/.log.yaml.refdes-tmp-rlsxf6sd');
  items/board-a/log.yaml still holds its original bytes` — and it does:
  `file_unchanged_dir_readonly: true` (sha256 `bae7e8b5dcd7…` identical
  before/after, `edge-readonly-tree.json`). **Finding 4 (Low
  (Unconfirmed))**: `chmod 0444` on the file alone does NOT block the save
  — the atomic write renames a fresh file over it: status 200,
  `applied: continuation LOG-A-009 appended to items/board-a/log.yaml (1
  tick)`, `file_unchanged_file_0444: false` (`edge-file-0444.json`).
  Nothing in the docs says which "read-only" the save seam honors.
- **CRLF**: `log.yaml` converted to all-CRLF (`crlf_lines: 115`,
  `lone_lf: 0`); the tick-save applies and the file stays all-CRLF
  (`crlf_lines: 123`, `lone_lf: 0`, `edge-crlf.json`).
- **Non-ASCII project path**: project dir renamed to
  `.scratch/proj17ünïcodé` (real non-ASCII characters in the path) — serve,
  pane (tip key `tqnks9s5f38`, tick rows, status `1 unsaved tick`) and
  Save all work there; the continuation entry (`LOG-A-011`,
  `follows: [LOG-A-010@tqnks9s5f38]`) lands on disk, check clean:
  `20 items, 0 errors, 0 warnings` (`edge-unicode-path.json`).
- **Serve from a project subdirectory**: launched with cwd =
  `.scratch/proj17c/items`; discovery walks up to the project, the root
  URL answers the token handshake (302) and the item page renders the pane
  (`edge-subdir-serve.txt`, `edge-idless-nowrite-sealed-subdir.json` E10).
- **Launch surface** (cli-reference): `--port` in use →
  `error: cannot listen on 127.0.0.1:8762: Address already in use; choose
  another --port, or drop --port to get an ephemeral one`, rc 2.
  `--token-file` lands mode `0o600`, one line, token is 43-char urlsafe
  base64 (`[A-Za-z0-9_-]{43}`), and after SIGTERM the token file is gone
  (`after SIGTERM the token file exists: False`); refused over a
  non-launch file (`it already exists and is not a refdes serve launch
  file, so it will not be overwritten…`). A foreign `Host:` is 403
  (`-> 403`); `Set-Cookie: refdes_token_8762=REDACTED; Path=/; HttpOnly;
  SameSite=Strict`; `/api/*` needs `X-Refdes-Token` (200 with, 403
  without). Refused requests answer with bodies (405 `method not
  allowed`, 413 `request too large`, 415 `expected application/json`,
  403 `missing or invalid launch token`) — the early-refusal drain,
  Linux-side; Windows specifics untestable here.
- **Static-site rule**: the built `_site/log-a-004.html` carries the
  read-only pane (`taskpane nodes: 16`, viewing
  `viewing LOG-A-004 · tasks as of tip LOG-A-008`), no rendered
  checkbox (`<input`: 0; the single `data-refdes-task` string is the pane
  script's template) and zero tokens — published pages never show a
  writable control (`serve-cli-battery.txt` 9, `code-quote.txt`).

## 4. VS Code Navis claims (READMEs + fragments), via CLI/HTTP

Endpoints (`api-navis-actions.txt`): `GET /api/navis` returns
navis rows (`key`, `key6`, `text`, `item`, `href`, `file`, `line`,
`archived`, `changed`, `orphan`) and counts; archive/restore accept a
full key, a unique prefix (`63q89n`) **and the ordinal**
(`archive by ordinal 1 (status 200)`, `restore by ordinal 1 (status
200)`); mint returns `{"kind":"ok","changed":false,"minted":[],"still_keyless":0}`.
Under `--no-write` both verbs lock with 403:
`this server was started with --no-write: navis archive and restore are
disabled` and `…navis mint is disabled` (matching the fragment's lock
claim). Extension manifest/source (`vscode-source.txt`): all commands
registered (`refdes.navisArchive`, `refdes.navisRestore`,
`refdes.navisMint`, `refdes.navisOpenInEditor`, `refdes.refreshNavis`),
the `Mint keys (N)` row, the keyless row `No key yet -- use Mint keys`,
the `--no-write` lock reason (`lockedReason`), version `0.2.0`. The
extension UI itself (tree, context menus, deep-link reveal) was not
launched — no VS Code here; code inspection only.

## 5. navis with an id-less marker (docs/navis.md, #476)

Full transcript: `navis-idless-before-after.txt` (project
`.scratch/proj17navi2`: two items, ids stripped, the marker keyless).

- Before `refdes id`: `check` fires 2 errors
  `item has no id — run 'refdes id' to allocate one`
  (plus `(minted 2 key(s) while loading)`); `navis ls` prints the #476
  note on stderr — `note: 2 items have no id yet and were not scanned --
  run 'refdes id' to allocate them` — and `no Navis: no `<!--navi:
  text-->` marker in any item body` on stdout, rc 0. `navis show 1` → `rc=2`:
  ``no Navi '1': `refdes navis all` numbers them 1..0; a selector is a
  number, a full key, or a key prefix``.
- `refdes id` allocates `REQ-MECH-003` and `REQ-MECH-004`.
- After: the first `navis show 1` mints the marker key on load —
  `navis: minted key ggwewv (ggwewv1xttm) into REQ-MECH-004
  (items/board-b/markers.yaml)` — and shows `key: ggwewv1xttm`; the key
  line lands in `markers.yaml`. `navis archive 1` archives it,
  `navis ls` then reports `0 Navis:`, and `navis restore 1` brings it back
  (`-- the marker at items/board-b/markers.yaml:12 is active again,
  showing its current text`). Check green: `2 items, 0 errors, 0
  warnings`. `navis show 99` → `rc=2`:
  ``no Navi '99': `refdes navis all` numbers them 1..1; a selector is a
  number, a full key, or a key prefix`` — docs' selector story matches.

## 6. Upgrading from 0.5.0 (docs/upgrading.md), step by step

Built a real 0.5.0-era project (built with refdes init from the 0.5.0 wheel:
`refdes.yaml` at hardware@2, colon-unit calc, a sealed log entry with an
item-level history setting, built with 0.5.0), then ran today's build.
Transcript: `upgrading-transcript.txt`, `upgrading-step2-check.txt`,
nested probe: `nested-probe.txt`.

- Step 1: **Finding 2 (Low (docs))** — the doc's error text (the
  `LEGACY_CONFIG_ERROR` string at `src/refdes/schema.py:90`, printed as
  `configuration error:` with `return 2` in `src/refdes/cli.py`, covered
  by `test_a_legacy_refdes_yaml_is_rejected_naming_both_replacements`)
  fires only when no ancestor carries the project marker. My probe sat
  inside the repo checkout: a directory carrying only `refdes.yaml`
  loaded the *ancestor* (repo) project —
  `20 items, 1 errors, 2 warnings`, no legacy error at all
  (`nested-probe.txt`). The doc's "no longer loads" holds for
  standalone projects, not nested ones.
- Step 2: renames surface — the doc's quoted trio matches for the items
  present: `item-level history: was renamed to on_change: -- rename this
  key in the source file. Its override is used in this build so the
  change policy is not silently lost.`, the colon-calc retirement naming
  `refdes calc-rewrite`, `(minted 3 key(s) and rewrote 1 reference(s)
  while loading)`, the `.refdes/schema.json was older … refreshed`
  warning; footer `3 items, 2 errors, 0 warnings` (`upgrading-step2-check.txt`). (No
  citations in the probe; the url:/vendor:/lockfile rows left
  unexercised.)
- Step 4 refusal: `project has existing build errors -- fix those first,
  so a calc that changes meaning under this rewrite can't hide behind an
  already-broken build` (verbatim); the refusal block lists the
  `history:` row (the second build error, the retired calc spelling, is
  in the step 2 block). After the rename `calc-rewrite` rewrote the
  colon line (`rewrote 1 calc line(s) in 1 file(s):`) and check went
  green.
- Step 5: `standard upgrade --to 3` refused with the doc's
  `on_change: mode 'log' was renamed to 'timeline' …` text and rolled
  back; after renaming the mode the upgrade printed `changed 3 file(s)`
  + `upgraded to v3.` (the doc's `baselines carried forward:` line
  belongs to a stamped probe; this probe's run printed no such line,
  consistent).
- Step 6: the seal follow-up fired verbatim on the link-bearing sealed
  entry (records: → follows: moves the hash):
  `LOG-PWR-001: edited while uncaptured -- the current content no longer
  matches the hash 5d1f8457ee45e9e8 recorded in .refdes/log-seal.yaml`; it
  names the remedy: `refdes history capture LOG-PWR-001`; running it printed
  `captured LOG-PWR-001: manual capture`; check green
  (`3 items, 0 errors, 0 warnings`). (A plain sealed log with no links:
  no follow-up warning — the hash moves only for migrated fields.)
- Step 7: `refdes revision post-upgrade` →
  `revision 'post-upgrade' stamped: 3 items.`; `audit` →
  `Since last revision (post-upgrade, …)` with `changed   0`; a repeat
  `standard upgrade --to 3` →
  `configuration error: project is already at hardware@3, not below the
  requested --to 3`; the transcript records `rc=2`. The post-upgrade `refdes ls` lists the three
  items (`LOG-PWR-001  log          First rail note.`).

## 7. README / changelog fragments

- README test command (`./.venv/bin/python -m pytest tests/ -q`,
  `readme-test-cmd.txt`): the venv path it shows is the project's;
  suite ran (section 0, `pytest-tail.txt`).
- Every `changelog.d/` fragment from `9f15af87` to HEAD
  (git-context.txt: `continue-capture`, `continue-idless-tip`,
  `docs-run16-gaps`, `navis-idless-note`, `navis-polish`,
  `navis-vscode-actions`, `navis-vscode-panel`, `serve-early-refusal-reset`
  (Linux-side portion), `tick-save-model`, `tick-save-polish` (both
  fixes), `tick-save-ui`) — each claim above, exercised in sections 1–6.
  No fragment claim found false; the gaps found are docs-side
  (Findings 2, 4).

## What I could not test

- The Windows halves: `serve-early-refusal-reset`'s `WinError 10053/10054`
  (source comment quoted in `code-quote.txt`), token-file ACLs (Linux box;
  the 4xx bodies + 43-char token + `0o600` + SIGTERM removal verified
  here).
- The VS Code extension UI (tree rows, context menus, deep-link reveal) —
  no VS Code installed; verified endpoints, manifest commands, and the
  extension source.
- A denied clipboard permission prompt (headless Chromium has no prompt
  UI; the transcript-stands path fired).
- The browser two-tab race (renderer crash repro; same 409 code path
  verified end-to-end via the disk-change flow).
- Published-page pane under JavaScript-disabled conditions (rule verified
  structurally: no write controls in the built site).

*Run 17, 2026-11-09. Simulated by Qwen3.8-Flash-Next; every quoted line is
pasted output, evidence files in `user-sim-run17-evidence/` (launch tokens
and cookies redacted to `REDACTED`; worktree paths to `<worktree>`; the
claims check in `claims-check.txt` greps every backticked span of this
report against the evidence).*
