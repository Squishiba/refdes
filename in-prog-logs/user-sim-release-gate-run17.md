# User-simulation release gate — run 17

Branch `user-sim-run17`, head `86c0d043` (includes #475 docs gaps, #476 navis
note, #477 save-seam polish, #474 save seam, #473 id-less tip, #472 VS Code
Navis). Base for "what shipped since": `9f15af87`. Simulated as a plain user:
`docs/` pages followed literally, CLI + a real browser (Chromium, Firefox
parity), probe projects under `.scratch/`. No fixes made. Full suite at base:
`6419 passed, 2 skipped in 110.46s` (`.scratch/run17/pytest.log`).

Headline:

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| 1 | Medium | `refdes serve` task pane | After Discard, Save/Discard stay visible with zero pending ticks — a stale pane state that invites a no-op click |
| 2 | Low (docs) | `docs/upgrading.md` step 1 | "no longer loads … exit 2" is true only when no ancestor directory carries `refdes-project.yaml`; a nested probe silently loads the ancestor project, exit 0 |
| 3 | Cosmetic | conflict panel | Conflict rows list ticks where your value already equals the file's ("yours open, the file has open") — noise when the change came from other fields |
| 4 | Low (Unconfirmed) | save on read-only file | File-mode-only read-only (0444) does not block a save — the atomic rename replaces the file; only a read-only *directory* refuses. Docs never say which the "read-only" guarantee means |

Counts by severity: **Medium 1, Low (docs) 1, Low (Unconfirmed) 1, Cosmetic 1**.

## 1. The tick-pane save flow (docs: cli-reference serve section, thread workbench)

Chromium 141 via puppeteer-core, Firefox via playwright-core, on
`refdes serve --no-open --port 8762 --token-file …` (writable). Evidence:
`user-sim-run17-evidence/flow-a-save.json`, `flow-c-firefox-save.json`,
`flow-a-capture-once.json`.

- Opening the pane shows the verbatim note: `Preview: ticking a row changes
  this page only — nothing is saved.` Ticking a row reveals **Save** +
  **Discard**, the status line names the count (`1 unsaved tick`), Save is
  hidden again when the draft empties.
- The draft survives a page reload (status `1 unsaved tick` after reload);
  the pane starts closed after reload (progressive enhancement holds:
  content is the page's own).
- Leaving the page with a draft fires the before-unload prompt (Firefox:
  `leave_prompt: true`).
- **Save applied** posts `POST /api/item/<key>/continue` and the response is
  `applied: continuation LOG-A-004 appended to items/board-a/log.yaml (1
  tick)`. The new entry copies `author/date/summary/status` from the tip,
  carries the full task list with the ticked row updated, and
  `follows: [LOG-A-003@fkv1gp0tkm9]` — the composite naming the tip's key.
  The page re-renders on the new tip; the pane's tick note reappears; Save
  is gone (no draft).
- After the save, `refdes thread LOG-A-004` announces
  `Snapshot Captured: LOG-A-003 (followed by later entry)` — and in
  `.refdes/history/events/` there is exactly one `followed` event per
  predecessor (`flow-a-capture-once.json`): capture-once, as the fragment
  says.
- **Finding 1 (Medium)**: after clicking **Discard** the checkboxes reset
  and the status indicator clears, but **Save** and **Discard** stay visible
  (rows: `[]`, `saveVisible: true`, `discVisible: false` in Chromium;
  `saveVisible: true` in Firefox). A click on the visible Save with no
  draft is a no-op. The visibility recompute listens for `change`; Discard
  resets the checkboxes programmatically, which fires no `change` event.
- A tick on a tip whose thread has an *older* page entry shows the workbench
  note `viewing LOG-A-001 · tasks as of tip LOG-A-008` — the pane's tip
  list is always the thread tip, matching the docs verbatim.

## 2. The conflict flow (docs: "a changed file opens the keep-mine/keep-theirs/copy-it-out conflict panel")

Evidence: `flow-b-conflict.json`, `flow-b-copyout.json`,
`flow-b-keepmine-late-tick.json`, `edge-stale-revision-409.json`.

- Change the file on disk behind an open page with a draft: the page
  auto-reloads, the draft survives with the stale clause
  `1 unsaved tick made against an older version — saving will ask to
  resolve`, and Save stays visible.
- Saving the stale draft is refused with 409 and the panel:
  `conflict: items/board-a/log.yaml changed since this edit was planned
  (expected 0259427c1ef2, found aafbdc900a16)` plus per-task rows
  (`T-thermal-model: yours -, the file has done`) and the three outcomes.
- **Keep mine** re-stamps the draft onto the new revision: the panel's
  revision becomes the file's, the draft (`1 unsaved tick`) survives, no
  entry is written. Ticks added *while the panel stood open* are kept
  (`flow-b-keepmine-late-tick.json`: status `2 unsaved ticks` after Keep
  mine with the late tick counted) — #477's polish, verified.
- **Keep theirs** discards the draft; nothing is written; Save hides.
- **Copy it out** replaces the panel with a read-only transcript:
  `Tick draft made at e3f4468c40a1…, the file is now at 4b73ac03b4dd…:
  T-demco: open` (a headless clipboard refuses `writeText`; the transcript
  stands — #477's polish).
- Server-side, a stale-revision POST 409s with
  `expected_revision`/`current_revision`/`current_text`/`diff` fields
  (`edge-stale-revision-409.json`); the pane's three outcomes sit on top of
  it. The pane is the only writer UI; the API body field is
  `expected_revision` (the 400 names it: `expected_revision is required:
  the file_revision from GET item<ref>`; `ticks` are `[id, state]` pairs).
- **Finding 3 (Cosmetic)**: rows where your tick equals the file (`T-demco:
  yours open, the file has open`) are listed as if in conflict.

## 3. Edge cases

Evidence: `edge-idless-nowrite-sealed-subdir.json`, `edge-fork-tabs.json`,
`edge-fork-endpoint-422.json`, `edge-idless-endpoint-422.json`,
`edge-readonly-tree.json`, `edge-crlf.json`, `edge-stale-revision-409.json`,
`serve-cli-battery.txt`.

- **Id-less tip (key, no `id:`)**: the pane renders, the checkbox works as
  preview, the status says `ticks on this tip are preview-only — nothing is
  saved`, and the panel carries no `data-refdes-tip-key`/`data-refdes-revision`
  (no save context, as the fragment says). `POST /api/item/<key>/continue`
  refuses naming the key: `refused: no item 'k7f3q2x8d0f' in this project`
  — the empty-subject text is gone.
- **Forked thread**: `refdes thread` reports
  `Thread: LOG-F-001 (forked: tips LOG-F-002, LOG-F-003)`; the pane shows
  one tab per open tip (`["LOG-F-002","LOG-F-003"]`), each tab's heading
  names its own tip (`Tasks at LOG-F-002: …`), ticking tab 2 counts only
  tab 2's draft, and Save on that tab appends a continuation to *that* tip
  (`applied: continuation LOG-F-005 appended to items/board-a/fork.md (1
  tick)`, page lands on `log-f-005.html`). A POST naming a tip whose thread
  is forked by ref (an entry in the middle) refuses:
  `refused: dwz1zj7bxhm's thread is forked across tips LOG-F-002, LOG-F-003:
  a continuation names one tip, and this request cannot pick one` — names
  both tips, readable.
- **`--no-write`**: pane opens, note present, **no tick checkboxes at all**
  (progressive enhancement: read-only), no Save; the served page loads only
  `preview.js` (no `taskpane-ticks.js`).
- **Sealed tip** (project overlay `types: {log: {sealing: build}}`): Save is
  offered (the pane can't know), refused with
  `refused: LOG-A-006 is a sealed append-only entry: a continuation appends
  a new entry, it never rewrites a sealed one` — names the tip and the
  remedy; the draft is kept (`1 unsaved tick`).
- **Two-tab conflict**: the browser repro crashed headless Chromium's
  renderer three times (unload-prompt + dual-target navigation); same-code
  path verified as the stale-revision 409 above (the pane behaves as in
  section 2, which was browser-tested with a disk change between).
- **Read-only tree**: `chmod 0555` on the item's directory —
  `refused: the write failed ([Errno 13] Permission denied:
  'items/board-a/.log.yaml.refdes-tmp-p8q75jsx'); items/board-a/log.yaml
  still holds its original bytes` (draft kept). **Finding 4 (Low
  (Unconfirmed))**: `chmod 0444` on the file alone does NOT block the save
  — the atomic write renames a fresh file over it (file_unchanged: false,
  200 applied). Nothing in the docs says which "read-only" the save seam
  honors.
- **CRLF**: with `log.yaml` in CRLF, the tick-save applies and the file
  stays all-CRLF (`crlf lines: 75, lone lf: 0`).
- **Non-ASCII project path**: project dir renamed to
  `.scratch/proj17ünïcodé` — serve, pane (tip key, 3 tick rows), tick,
  Save all work on the non-ASCII path (`edge-unicode-path.json`: status
  `1 unsaved tick`, Save applied appends the continuation — entry count
  9 → 10, check `19 items, 0 errors`).
- **Serve from a project subdirectory** (`items/`): launch URL, preview,
  item pages, and the pane all work — project discovery walks up.
- **Launch surface** (cli-reference): `--port` in use →
  `error: cannot listen on 127.0.0.1:8762: Address already in use; choose
  another --port, or drop --port to get an ephemeral one`, exit 2.
  `--token-file` lands `0600`, one line, token is 43-char urlsafe
  base64 (`[A-Za-z0-9_-]{43}`), removed on `SIGTERM`, refused (with the
  verbatim text: `…it already exists and is not a refdes serve launch
  file, so it will not be overwritten…`) over a non-launch file. A foreign
  `Host:` is 403; `Set-Cookie: refdes_token_8762=…; HttpOnly;
  SameSite=Strict`; `/api/*` needs `X-Refdes-Token` (reads too: 200 with /
  403 without). Refused requests answer with bodies (405 `method not
  allowed`, 413 `request too large`, 415 `expected application/json`,
  403 `missing or invalid launch token`) — the early-refusal drain,
  Linux-side; Windows specifics untestable here.
- **Static-site rule**: `_site/log-a-004.html` carries the read-only pane
  (11 taskpane nodes, `viewing LOG-A-004 · tasks as of tip LOG-A-008`) and
  zero tick checkboxes, zero tokens — published pages never show a
  writable control.

## 4. VS Code Navis claims (READMEs + fragments), via CLI/HTTP

Endpoints (`api-navis-actions.json`): `GET /api/navis` returns
`navis[]` with `key/key6/text/item/href/file/line/archived/changed/orphan`
and `counts`; archive/restore accept a full key, a unique prefix
(`63q89n`), or the ordinal; mint returns
`{"kind":"ok","changed":false,"minted":[],"still_keyless":0}`. Under
`--no-write`: `this server was started with --no-write: navis archive and
restore are disabled` / `…navis mint is disabled` (403, matching the
fragment's lock claim). Extension manifest/code: all commands registered
(`navisArchive/navisRestore/navisMint/navisOpenInEditor/refreshNavis`),
`Mint keys (N)` row + `No key yet — use Mint keys`, session lock, version
`0.2.0`. The extension UI itself (tree, context menus, deep-link reveal)
was not launched — no VS Code here; code inspection only.

## 5. navis with an id-less marker (docs/navis.md, #476)

Full transcript: `navis-idless-before-after.txt`.

- Before `refdes id` (markers with keys, no ids): `check` 2 errors
  `item has no id`; `navis ls` / `navis all` print on stderr
  `note: 2 items have no id yet and were not scanned — run 'refdes id' to
  allocate them` and `no Navis: no `<!--navi: text-->` marker in any item
  body` on stdout, rc 0 — the #476 note, verbatim. `navis show 1` → rc 2
  with the range explanation.
- `refdes id`: allocates REQ-MECH-001/002 (mints keys while loading).
- After: `navis ls` lists the marker (`1. d2zvg3 Recheck decoupling near
  U14.  REQ-MECH-002`); `navis show 1` →
  `key: (keyless — the next writable command mints a key)`; after the next
  writable command the marker key is minted into the file
  (`navis: minted key d2zvg3 (d2zvg318q5a) into REQ-MECH-002`);
  `navis show 99` → rc 2 `no Navi '99': `refdes navis all` numbers them
  1..1; a selector is a number, a full key, or a key prefix` — docs'
  selector story matches.

## 6. Upgrading from 0.5.0 (docs/upgrading.md), step by step

Built a real 0.5.0-era project (`refdes init` from the 0.5.0 wheel:
`refdes.yaml` at `standard: hardware@2`, `text:` requirement, colon-unit
calc, a sealed log entry with item-level `history: log`, built with 0.5.0),
then ran today's build. Transcript: `upgrading-transcript.txt`,
`upgrading-step2-check.txt`.

- Step 1: **Finding 2 (Low (docs))** — the doc's error text (verbatim in
  `schema.py:91`, exit 2, covered by `tests/test_config_split.py`) fires
  only when no ancestor has `refdes-project.yaml`. My probe sat inside the
  repo checkout, so the first `refdes check` silently loaded the ancestor
  project (repo's own, 20 items, exit 0) — the doc's "no longer loads"
  holds for standalone projects, not nested ones.
- Step 2: renames surface — the quoted trio matches for the items present:
  `item-level history: was renamed to on_change: — rename this key in the
  source file. Its override is used in this build so the change policy is
  not silently lost.` (verbatim), the colon-calc retirement naming
  `calc-rewrite`, `minted 3 key(s) and rewrote 1 reference(s) while
  loading`, the `schema.json … refreshed` warning. (No citations in the
  probe; `url:`/`vendor:`/lockfile rows left unexercised.)
- Step 4 refusal: `project has existing build errors — fix those first, so
  a calc that changes meaning under this rewrite can't hide behind an
  already-broken build` (verbatim), with the `history:` error listed as the
  reason; after the rename `calc-rewrite` rewrote the colon line and the
  build went green.
- Step 5: `standard upgrade --to 3` refused with the `decision` row's
  quoted `on_change: mode 'log' was renamed to 'timeline' …` text, rolled
  back; after renaming the mode the upgrade printed `changed 2 file(s)` +
  `upgraded to v3.` (probe has no baselines — the doc's
  `baselines carried forward:` line belongs to a stamped probe; my probe's
  run says nothing, consistent).
- Step 6: the seal follow-up fired verbatim on the link-bearing sealed
  entry (`records:` → `follows:` moves the hash):
  `LOG-PWR-001: edited while uncaptured — the current content no longer
  matches the hash 5d1f8457ee45e9e8 recorded in .refdes/log-seal.yaml …
  Run `refdes history capture LOG-PWR-001``; running it printed
  `captured LOG-PWR-001: manual capture`; check green. (A plain sealed log
  with no links: no follow-up warning — the hash moves only for migrated
  fields, so the doc's probe needs the `records:` edge, as its §Seals
  section says.)
- Step 7: `refdes revision post-upgrade` →
  `revision 'post-upgrade' stamped: 3 items.`; `audit` →
  `Since last revision (post-upgrade, …): changed 0`; a repeat
  `standard upgrade --to 3 --dry-run` →
  `configuration error: project is already at hardware@3, not below the
  requested --to 3`, exit 2.

## 7. README / changelog fragments

- README test command (`README.md:410`): the venv path it shows is the
  project's; suite runs (section 0). ✓
- Every `changelog.d/` fragment in `9f15af87..HEAD`:
  `continue-capture`, `continue-idless-tip`, `docs-run16-gaps`,
  `navis-idless-note`, `navis-polish`, `navis-vscode-actions`,
  `navis-vscode-panel`, `serve-early-refusal-reset` (Linux-side portion),
  `tick-save-model`, `tick-save-polish` (both fixes), `tick-save-ui` —
  each claim above, exercised in sections 1–6. No fragment claim found
  false; the gaps found are docs-side (Findings 2, 4).

## What I could not test

- The Windows halves: `serve-early-refusal-reset`'s `WinError 10053/10054`,
  token-file ACLs (Linux box; the 4xx bodies + 43-char token + 0600 +
  SIGTERM removal verified here).
- The VS Code extension UI (tree rows, context menus, deep-link reveal) —
  no VS Code installed; verified endpoints, manifest commands, and the
  extension source paths only.
- A denied clipboard permission prompt (headless Chromium has no prompt UI;
  the transcript-stands path fired).
- The browser two-tab race (renderer crash repro; same 409 code path
  verified end-to-end via the disk-change flow).
- Published-page pane under JavaScript-disabled conditions (rule verified
  structurally: no write controls in `_site/`).

*Run 17, 2026-11-09. Simulated by Qwen3.8-Flash-Next; every quoted line is
pasted output, evidence files in `user-sim-run17-evidence/` (launch tokens
redacted).*
