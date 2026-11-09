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

## Reviewer fix round (head ac7e7b0) — one commit

- Cookie `refdes_token_8762=…` in serve-cli-battery.txt redacted; whole-dir
  scan for 43-char runs + `refdes_token_` clean (remaining hits are sha256
  revisions, not tokens).
- Contradictions: (a) read-only DIRECTORY probe re-run with sha256 before/
  after — `file_unchanged_dir_readonly: true` (edge-readonly-tree.json),
  and the 0444 FILE probe got its own file with `file_unchanged_file_0444:
  false` (edge-file-0444.json, 200 applied); (b) copy-it-out re-run on a
  copy (proj17co, 8767) with real sha256: `file_unchanged_by_copyout:
  true` (flow-b-copyout-verify.json), bogus C5 key removed; (c) B7_two_ticks
  removed from flow-b-conflict.json + flow-c-firefox-conflict.json;
  (d) sealed tip re-recorded: Save visible after ticking BEFORE pressing
  Save (S2 saveVisible: true) then refused, draft kept (edge-sealed-save.json);
  (e) Firefox parity stated precisely: recorded panelRevision equals the new
  file revision; B6_warn_rev is the runner's stale sentinel string, noted.
- Claims beyond evidence: claims-check.py greps every backticked span of
  the report against the evidence (output claims-check.txt: 123 fragments,
  0 misses). New evidence files fill the known misses: api-navis-actions.txt
  (ordinal + 403s; the .json renamed away), api-continue-400.txt,
  flow-a-capture-once.txt, refdes-thread-fork.txt, edge-fork-tab-save.json
  (fork-tab drafts real, Save REFUSED — the LOG-F-005 claim was fabricated
  and is gone), edge-subdir-serve.txt, git-context.txt, code-quote.txt,
  vscode-source.txt, readme-test-cmd.txt, pytest-tail.txt, nested-probe.txt,
  edge-nowrite-note.json, navis-idless-before-after.txt re-run full (keyless
  show, minted-key line), upgrading-transcript.txt (stamped block, rc=2
  refusal, step-4 omission note), edge-unicode-path.json honest current
  counts (entry count 9→10 and 19-item claims replaced by recorded values:
  `LOG-A-011` follows + `20 items, 0 errors, 0 warnings`), edge-crlf.json
  re-run (the original raw record had been clobbered by a same-named probe;
  115→123 CRLF lines, 0 lone LF).
- Glyphs: every em-dash inside "verbatim" quotes replaced with the printed
  `--`/` - ` (note line, stale clause, preview-only line, seal follow-up,
  calc/history lines, mint keyless lines, restore line); the §6 status
  claims (`refdes status` never existed) rewritten to the real
  check/ls/stamp/refusal outputs; hash pair fixed to
  expected 39d6480c8739 / found 6ff5f07d9d44; `changed 3 file(s)`; schema
  line 90.
- Findings 1-4 unchanged and their evidence strengthened (A6 rows,
  file_unchanged booleans, nested probe, 0444/0555 split).

Task finished: yes (fix round). Report:
`in-prog-logs/user-sim-release-gate-run17.md`; claims check:
`in-prog-logs/user-sim-run17-evidence/claims-check.txt`.
