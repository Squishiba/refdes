# run17 — user-simulation release gate

Task: run 17 of the user-simulation release gate (docs-only). Scope =
changes since 9f15af87: tick-pane save seam, conflict panel, id-less tip,
navis id-less note, VS Code Navis view, serve launch surface, upgrading.md.

## What was done

- Full suite at base: 6419 passed, 2 skipped (`.scratch/run17/pytest.log`).
- Built probe projects under `.scratch/` (proj17b/c/ff2/unicode/navi/
  proj17upg/upg2/upg3) + `refdes serve` instances on 8762 (writable),
  8763 (--no-write), 8764 (sealed), 8765 (unicode path), 8766 (subdir).
- Real-browser flows (Chromium via puppeteer-core, Firefox via
  playwright-core): A save flow (draft, reload persistence, leave prompt,
  Save -> continuation contents, capture-once, thread after), B conflict
  flow (stale clause, 409 panel, Keep mine incl. late ticks, Keep theirs,
  Copy it out transcript), fork tabs (per-tip drafts + per-tip continuation),
  id-less tip (preview-only), --no-write (no controls), sealed tip
  (readable refusal, draft kept), read-only dir (readable refusal),
  read-only file (save succeeds — atomic rename), CRLF (preserved),
  unicode path, serve from subdir, Firefox parity (A+B full pass).
- CLI/HTTP: serve launch surface (port-in-use exit 2, token-file 0600 /
  SIGTERM removal / refusal over non-launch files, token shape, Host 403,
  cookie SameSite=Strict, 4xx battery), navis endpoints (archive/restore/
  mint, --no-write locks), stale-revision 409 body, id-less fork 422,
  navis id-less note before/after `refdes id`.
- upgrading.md run end-to-end against the real 0.5.0 wheel (init -> v2-era
  items -> build with 0.5.0 -> split config -> check renames (history: ->
  on_change: verbatim) -> calc-rewrite refusal -> rewrite -> standard
  upgrade (mode log -> timeline refusal verbatim) -> seal follow-up ->
  history capture -> revision post-upgrade -> audit changed 0).
- Evidence under `in-prog-logs/user-sim-run17-evidence/` (tokens redacted,
  scripts kept in `.scratch/`).

## Findings (report has details)

1. Medium: Discard leaves Save/Discard visible (zero pending ticks) —
   programmatic uncheck fires no change event; Chromium + Firefox.
2. Low (docs): upgrading.md step 1 "no longer loads" is unconditional;
   nested under an ancestor project the walk-up silently loads the
   ancestor (exit 0). Code/tests cover standalone only.
3. Cosmetic: conflict panel lists rows where yours == the file.
4. Low (Unconfirmed): file-mode 0444 does not block a save (atomic
   rename); dir 0555 does. Docs don't say which "read-only" is meant.

## Difficulties

- The 0.5.0 venv (`.scratch/venv050`) CLI has no `--version` (verified
  0.5.0 by the init output printing `standard: hardware@2` and the wheel
  install log).
- Nested probe dirs inherit the repo's own project (walk-up) — that IS
  finding 2; probes for upgrade steps run with the split config.
- A sealed log with no links showed no step-6 follow-up warning; the hash
  moves only with migrated link fields — needed a `records:` edge (doc
  text says this; my first probe was missing it).
- Browser two-tab repro crashed headless Chromium's renderer (3 tries);
  the same 409 path is verified server-side + via the disk-change flow.
- Shell constraints: no `rm -rf`, no paths outside the checkout, no `cd`
  in commands — used workdir params + new probe dirs per run.

Task finished: yes. Report:
`in-prog-logs/user-sim-release-gate-run17.md`.
