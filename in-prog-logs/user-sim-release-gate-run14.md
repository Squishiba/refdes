# User-simulation release gate, run 14

Acting as a hardware-author user of the shipped docs on branch
`user-sim-run14` (base `7acb47f`; run 13 base was `899ab91`). The user-facing
in-scope commits (from `git log --oneline 899ab91..7acb47f`):

- `ba6d153` feat(calc): inline spans enter calc_hash, dependency scans and the content hash (HASH_FORMAT 6) (#347)
- `76bc1e4` fix(release): the inline-calc gate names the unreadable history store when failing closed (F13-1) (#368)
- `92eea45` fix(serve): editor save accepts the keyless item's ~file:line handle (F13-2) (#370)
- `314823d` fix(pages): invalid page front-matter warns once, with the file line (F13-4) (#369)
- `27c4fda` fix(serve): editor responses never embed the server's absolute project paths (F13-3) (#372)
- `8018668` fix(check): imported items' diagnostics name the upstream source file and line (CHK-ATTR-002) (#361)
- `3c9035b` feat(editor): standalone transaction-journal module for editor saves (EDITOR-JOURNAL-1) (#367)
- `92ae18d` feat(serve): journal every editor save, gate loads on it, add refdes recover (#381)
- `7486c99` feat(sources): the picker lists a cited XLSX's defined names (#380)
- `f460e46` feat(history): baseline snapshot events and the item-page history disclosure (living notes H9) (#384)
- `a78e30f` feat(serve): read-only inline-calc preview route (live inline-calc slice A) (#386)
- `6b89e38` feat(serve): live inline-calc panel and auto-fill in the browser editor (live inline-calc slice B) (#388)
- `3377090` feat(serve): live-calc panel computes spans from the draft's fields (live inline-calc slice C) (#392)
- `7acb47f` feat(serve): browser-editor font setting (toolbar slice 3) (#394)
- `f7077ea` feat(navis): grammar, body scan, model and read-only CLI (slice 1) (#382)
- `a08f678` feat(navis): key minting on writable load (slice 2) (#390)
- `f94a503` feat(calc): field references in calc fences and spans via ITEM.$field (#387)

Judged against `docs/math.md`, `docs/lifecycle.md`, `docs/cli-reference.md`,
`docs/markdown.md`, `docs/pages.md`, `docs/output.md`, `docs/authoring.md`,
and the changelog fragments for each commit. Findings are reported, not fixed.

## 0. Headline

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| F14-1 | Medium | inline calc / release gate | a stale-span warning prints the raw binary float `4.3999999999999995 W` as the computed value; `docs/math.md` shows the display-formatted value (`4.4 W`) in the same message shape |
| F14-2 | Low | docs (math) | the docs never state the offset-unit rule: `Rth = 42 K/W` in a `degC` fence yields a raw pint error (`Ambiguous operation with offset unit (degree_Celsius, kelvin)`); only the `delta_degC` examples imply the fix |
| F14-3 | Info | navis CLI | `changelog.d/navis-slice-2.added.md` names the list-file mint refusal warning `NAVI_MINT_REFUSED`; the observed warning carries no code |
| F14-4 | Low | navis / render | docs/markdown.md promises marker bytes "never appear in the rendered HTML", yet they appear in list-page summary projections and in history-disclosure snapshot bodies |
| F14-5 | Low | docs (picker) | the XLSX picker endpoint `GET /api/item/<ref>/sources/entries` exists only in the changelog fragment — no docs page names it |

Everything else tested behaved as documented; the sweeps below record the
verified promises with evidence file names in
`in-prog-logs/user-sim-run14-evidence/`.

## 1. Harness

- `refdes` 0.5.0 from this worktree (`PYTHONPATH=<worktree>/src`, venv
  python), standard `hardware@3`, Python 3.13, Chromium via puppeteer-core.
- Helper `.scratch/rr <proj> <args...>`; projects under `.scratch/run14/`
  (`pwr` main multi-board project, `upstream` (imported), `keyless`,
  `xlsx3`, `nonavi`, `sealnavi`, plus targeted copies).
- Serves on 8755/8756 with `--no-open --token-file url.txt`, tokens read
  from the worktree, kills by PID. Browser flow gets its cookie from the
  launch URL; API writes use `X-Refdes-Token` + session cookie + Origin/Referer.

## 2. Sweep 1 — inline spans in hashes/gates (#347, #368)

Fixture `pwr`: spans over a CSV-pinned source, a cross-item quantity, and a
`RES-001.$rds_on` field reference; upstream project `upstream` imported.

- CSV pin + `fetch --update`: the three spans go stale with the documented
  message shape, names+file:line, exit 0 on `check` (01d):
  `inline calc Pdiss: stored result says 0.30 W, now computes 0.44 W`.
  The `Pin` span prints `now computes 4.3999999999999995 W` — **F14-1**:
  every other value in the same run is display-formatted, and
  `docs/math.md`'s stale-message example shows `4.4 W`.
- `inline_calc_results` gate names each stale span with item, name,
  file:line and fails the release (01e); fixing the spans makes it pass (01f).
- Spans now participate in hashes: editing only a span's stored result moves
  the item content hash (01i); `audit` explains a dependency change through
  the span (`LOG-THM-001 -- referenced LOG-PWR-003.P_diss: 0.2981 W -> 0.44 W`, 01h).
- Field references: editing `RES-001.rds_on` (field, not calc) stales
  `Rds := RES-001.$rds_on | mohm = 18 mohm` as documented (01g); the
  calc-value/field collision warning names the disambiguation `RES-001.$vin`.
- Offset arithmetic (`docs/math.md`): `Rth = 42 K/W` + `55 degC + P_stage * Rth`
  → raw pint diagnostic, not a refdes message — **F14-2** (docs gap);
  `42 delta_degC/W` computes and builds clean.
- #368: corrupting the history store fails the gate closed and *names the
  store* (01j): `FAIL inline_calc_results ...: cannot read the history store
  ... -- failing closed`, exit 1.

## 3. Sweep 2 — page front-matter (#369)

`pages/ov1.md` (no closing `---`) and `ov2.md` (stray tab): exactly **one**
warning per page on both `check` and `build`, each with the file line
(`pages/ov1.md:3`) — the F13-4 double-print and missing line are fixed
(02a, 02b). Rendered page keeps its body.

## 4. Sweep 3 — keyless editor handles (#370, #372)

Fresh `keyless` project (keys never minted), served on 8755.

- `/api/items` hands out `~items/reqs.yaml:6`-style provisional handles;
  the editor saves through exactly that handle — YAML list item and markdown
  item both `200` with the applied-patch echo (03-sweep3-keyless.json).
- A stale handle and a never-existing handle both refuse `422`
  `refused: no item '~items/reqs.yaml:14' in this project` (03b, 03c) —
  the F13-2 write-route refusal is fixed.
- Conflict/refusal messages carry only project-relative paths; no response
  body contains `/home/...` (03b) — F13-3 fixed.

## 5. Sweep 4 — save journaling + `refdes recover` (#367, #381)

- Normal saves leave no `.refdes/editor-transaction` behind.
- A crafted pending journal gates every command (exit 2, 04-gate-*.txt) with
  the documented recovery hint; `recover` with a clean tree is a no-op
  (04-recover-clean.txt); a corrupt manifest keeps the journal and changes
  nothing (04-recover-corrupt.txt); a live file matching neither hash makes
  recover refuse and survive (04-recover-neither.txt); journal dir without
  manifest is cleaned (04-recover-nomanifest.txt); `--no-write recover`
  refuses a pending journal (04-recover-nowrite.txt).
- Real restore path verified with the serve stopped and gates run:
  `restored items/reqs.yaml`, file back to the pre-crash bytes (04-recover.txt).
  An earlier "already matched" anomaly was a probe artifact (a no-op
  replacement in the test script), not a product bug — no finding.

## 6. Sweep 5 — XLSX picker (#380)

Fixture `analysis/thermal-model.xlsx` (built with openpyxl, sheet-scoped and
workbook-scope defined names, text/blank/range/formula-no-value names, merged
range, hidden sheet, second sheet with a same-name scope) cited by
`LOG-THM-001`.

- `fetch` extracts `Sheet1!case_rise` (qualified name resolves), pins
  `12.5`; after the workbook changes, `check` warns `SOURCE FILE CHANGED ...
  locked 12.5, file now 13.25` and `fetch --update` moves the pin (05a).
- Picker API (05b): `GET /api/item/LOG-THM-001/sources` lists the citation
  with `reader:"xlsx"`, `browse:"rows"`, `state:"ok"`; `.../sources/entries`
  lists every defined name — workbook-scope bare (`rail_eff`), sheet-scoped
  qualified (`Sheet1!case_rise`, `Sheet2!case_rise`, hidden sheet names with
  `sheet:"hidden"` context), merged top-left value readable, refusals marked
  `selectable:false` with the reader's words (text cell, blank, non-single-cell,
  `has no cached numeric value; open the workbook in a calculating application,
  save it, then fetch --update`), caps reported (5000 names, 1 MiB).
- Corrupt and oversized workbooks (05c, 05d): the file row shows a clear
  problem naming the file and the reader's reason
  (`cannot read XLSX workbook: File is not a zip file`;
  `the file is 12582916 bytes and a source listing refuses anything above
  1048576 bytes (1024 KiB) -- split it, ...`). No absolute paths.
- Browser picker (05e): in the editor the picker opens over the cited xlsx,
  rows render with values, refusals are visibly marked and their buttons
  disabled, picking `rail_eff` opens the confirm, typing unit `1` composes
  `rail_eff = source("analysis/thermal-model.xlsx", "rail_eff") | 1`, accept
  inserts it into the body and saves; `check` then computes from the pin.
- The entries endpoint is named only in the changelog fragment — **F14-5**
  (docs gap; an author following `docs/output.md`/`docs/cli-reference.md`
  cannot discover it).

## 7. Sweep 6 — baseline snapshot events, history disclosure (#384)

- `pwr` stamped baselines (`rev-a`, `rel-1`, `rev-b`) render a History
  disclosure on `log-pwr-003.html`: one row per keyed item with the snapshot
  the store captured at that stamp, `edited after captured` notes (06a).
- Moving one baseline's events out of the store and rebuilding makes that
  baseline's row say exactly the documented fallback sentence ("stamped before
  the history store existed, its snapshot write failed ... The page records
  only hashes for it."); restoring the events restores the snapshot.
- `keyless` (nothing stamped) builds with no History disclosure panel at all.

## 8. Sweep 7 — imported-item diagnostic source (#361)

Upstream `REQ-IF001` given `refines: [REQ-MISSING]`; downstream `pwr check`
reports `ERROR platform:items/interfaces.yaml:7 [REQ-IF001] — refines points
at 'REQ-MISSING' ...` (07a) — the qualified upstream file:line as promised.
Artifact variants with the source record removed, and with the line removed,
both fall back to `<import:platform>:1` as documented. Editor: imported items
are read-only (`external:true, origin:"platform"`, every control
`editable:false`) and a forged write is refused verbatim
(07a-pwr-check-full.txt, API exchange recorded).

## 9. Sweep 8 — Navis slices 1+2 (#382, #390)

Fixture `keyless`: duplicate keyless markers, a declared-key marker, a
corrupt-key marker, fenced/inline inert markers, a list-file `body:` marker.

- Read-only `--no-write navis ls` lists keyless rows (no key column), leaves
  every byte untouched, warns the corrupt key (08-navis.txt).
- Writable load mints one key per markdown marker, announces on stderr
  (`navis: minted key cq4f39 (cq4f39mzkpw) into REQ-010 (items/REQ-010.md)`),
  duplicate texts get distinct keys, the second writable run writes nothing.
- The list-file `body:` marker stays keyless with the documented refusal
  warning — which carries no `NAVI_MINT_REFUSED` code: **F14-3**.
- `navis show` resolves full key, unique 6-char prefix, and ordinal; a
  keyless marker's row says `(keyless -- the next writable command mints a
  key)`; a bogus selector and an out-of-range ordinal exit 2 naming the
  selector shapes.
- `navis all` = active list + the stated archive placeholder line;
  `nonavi` answers `no Navis: no \`<!--navi: text-->\` marker in any item
  body` with exit 0.
- `refdes index` payload gains a top-level `navis` key, absent when there
  are none (08a).
- Build consumes markers from the item body (body HTML has zero `<!--navi:`
  occurrences) and leaves inert fenced/inline occurrences literal.
  **F14-4**: marker bytes *do* reach the page elsewhere — the list pages'
  summary projections (`navi:cq4f39mzkpw Model worst-case copper tempera…`
  on `keyless/_site/index.html`) and the history-disclosure snapshot bodies
  (`navi:r5kd3ys7wsh ...` inside `log-thm-001.html`'s captured snapshots,
  08b) — against `docs/markdown.md:75` "the marker's bytes never appear in
  the rendered HTML".
- Mint cost clause: with a custom `append_only: true` markdown type
  (schema-overlay `memo`), a marker minted into a *sealed* entry still built
  clean — minting happens inside the load, before the seal compares, so the
  minted bytes are what the new seal records (no surprise refusal); the
  documented seal refusal itself works for real edits
  (`append-only and has been modified since it was sealed ... run with
  refdes build --reseal power`). No finding; recorded as verified shape.

## 10. Sweep 9 — live inline-calc panel + font setting (#386, #388, #392, #394)

Chromium on `pwr` served at 8755; drafts edited in the textarea, no saves
(09a/09b-live-calc.json).

- Panel mounts under the textarea for items with `:=` spans; rows show
  `ok/stale/error` with the computed value and the *same message* `check`
  reports (`inline calc Reff: stored result says 0.93, now computes 0.88`).
- Draft-only evaluation: editing a fence line in the draft changes the panel
  immediately; the file on disk never changes (`filesTouched:false`); the
  client only pre-gates on `:=` — every evaluation is `POST /api/item/<ref>/calc`.
- Fence-before-span rule: a span reads fence names from fences *above* it in
  the body; a span above the fence gets the documented unknown-name error.
- Stale row carries **Fill**; clicking it rewrites only the stored result
  slot in the draft (`... = 0.88`), row goes `ok`.
- Auto-fill: checkbox on by default, persisted per browser under
  `refdes.live-calc.autofill` (`off`/`on`, survives reload). With a
  fillable stale span and the box on, the result slot fills itself as the
  typing pauses. In headless Chromium the panel's "native undo may not cover
  these fills" note appears and auto-fill stood down for the session,
  leaving stale rows + working Fill — the documented stand-down shape.
  (Manual Ctrl+Z after a Fill did restore the text.)
- FIELD recalc (slice C, #392): `RES-001` panel row `Rdsf ... 20 mΩ`
  (`Rdsf := RES-001.$rds_on | mohm = 20 mΩ`); editing the FIELDS panel
  `rds_on` to `25 mohm` recalcs the row to `25 mΩ` live, unsaved.
- Font setting (#394): Font button opens the Family/Size/Line-height
  popover; choosing Sans and +2 sizes writes `{"family":"sans","size":14,
  "lineHeight":1.5}` to `refdes.editor.font`, applies through CSS custom
  properties (textarea computed `system-ui, sans-serif / 14px`), survives
  reload, and leaves body text untouched.

## 11. What I could not test

- Firefox launcher (only Chromium available here).
- Real crash mid-save (SIGKILL window) — sweep 4 used crafted journal
  fixtures for the same state.
- VS Code extension behavior for #361's diagnostic locations (out of
  simulation).
- Encrypted/password-protected XLSX (no writer available), and the
  behavior with the `refdes[xlsx]` extra missing (openpyxl present).
- The 5000-name truncation row cap with a real 5000+ name workbook,
  and the panel's `showing the first N spans` footer (fewer spans authored).
- `navis show` with a genuinely *ambiguous* 6-char prefix (needs two 11-char
  keys sharing a prefix; the code path names candidates and exits 2,
  untested at runtime).
- Diff-build byte-identity against the previous release for no-marker
  projects (single build verified; no previous-release artifact pair here).
