# Upgrade-guide evidence — 0.5.0 → next release (2026-10)

Task: write `docs/upgrading.md` from real evidence, add the two missing
breaking fragments the release-readiness audit found, link the page from
`docs/index.md` and `README.md`. Branch `docs-upgrading-from-050` off
main (base e66bf6f, ff-merged to cf99252 during work: CHK-ATTR fixes +
agentcoder landed). Every command below was run; every quoted message is
captured output.

## Method

1. `git archive v0.5.0 | tar -x -C ./.scratch/v050/`.
2. Built a v0.5.0-era project with the OLD tool
   (`PYTHONPATH=.scratch/v050/src … -m refdes.cli`, cwd
   `.scratch/proj-v050`): its own `refdes init` (wrote `refdes.yaml`,
   printed `standard: hardware@2`), then 2 requirements (`text:`),
   1 bound (`text:`+`limit:`), 1 decision (markdown, colon-unit calc,
   `checks:`, `options:`, `satisfies/constrained_by/selects:`), 2
   components (`equivalent:` pair, `datasheets:` citation with
   `url:`+`page:`+`vendor: true`), 1 test (`method:`), 1 log entry
   (`records:`, append-only). A local `http.server` on 127.0.0.1:8765
   served a stub PDF; old `refdes fetch` pinned+vendored it (lockfile
   `vendored: true`, bytes in `.refdes/vendor/`). Old `refdes build`
   wrote `.refdes/log-seal.yaml` (LOG-PWR-001 hash `d141e66be61d4851`);
   old `refdes revision pre-upgrade-baseline` stamped the baseline. Old
   build: `8 items, 0 errors, 2 warnings` (both coverage warnings),
   exit 0.
3. Copied to `.scratch/proj-up`, ran CURRENT main
   (`PYTHONPATH=src … -m refdes.cli`) step by step, recording every
   message; applied each fix and re-ran to green.

## Environment notes

- The probe project lives under this repo's `.scratch/`, and this repo is
  itself a refdes project: current discovery walks UP to
  `refdes-project.yaml`, so a plain nested probe silently loads the
  OUTER project (observed: `refdes check` in `.scratch/proj-up` printed
  the repo's own 20 items before the marker split). The legacy
  `refdes.yaml`-retired error (which needs an upward walk that finds no
  marker) was reproduced in a private user/mount namespace
  (`unshare -rm`, tmpfs probe dir, `/dev/null` bind-mounted over the
  worktree's `refdes-project.yaml`) — script
  `.scratch/legacy-probe.sh`, real output quoted in the page.
- The stub PDF is not fully pypdf-parseable (`startxref not found`), so
  the page-count check surfaces its documented `page_count_error` row —
  quoted as such.

## Ordered evidence (condensed; full text in docs/upgrading.md)

1. `refdes check` (pre-split): `configuration error: refdes.yaml is
   retired. …` exit 2. Fix: settings → `refdes-project.yaml` (rename),
   no `types:` → no `refdes-schema.yaml`.
2. First writable load: `minted 8 key(s) and rewrote 8 reference(s)`;
   4 ERRORs: citation `url:`→`path:`; two retired colon-unit calc lines
   (exact rewrite shown per line); lockfile `vendored:`→`kept_copy:`.
   Warnings: schema.json refresh; NEW status/link-disagreement warning
   (`status is 'selected' but nothing selects it` — the old tool built
   this project clean); `.refdes/vendor/` rename; 2 pre-existing
   coverage warnings.
3. Ordering constraints, both observed verbatim: `standard upgrade
   --to 3` and `calc-rewrite` each refuse while the build is red
   ("fix those first, so a … change can't hide behind one
   already-broken build"). The `url:` error names `standard upgrade` as
   the fix, which refuses → circular; the working path is the manual
   rename the message also states. Fixed by hand: `url:`→`path:`,
   `vendor:`→`keep_copy:`, lockfile key rename,
   `mv .refdes/vendor .refdes/copies`.
4. `refdes calc-rewrite`: rewrote 2 lines, values preserved, exit 0.
5. `refdes standard upgrade --to 3 --dry-run` (plan, exit 0), then real:
   `changed 6 file(s)` + `baselines carried forward:
   pre-upgrade-baseline` + `upgraded to v3.` Verified in files:
   `text:`→`body:` (requirement, bound), `method:`→`body:` (test),
   `datasheets:`→`citations:` (component), `equivalent:`→`drop_in:`,
   `type: decision`→`log` + `title:`→`summary:`,
   `records:`→`follows: [DEC-PWR-001@xd6hk1vhg05]` (composite, anchored
   by the writable load), `standard.version: 3`.
6. Post-upgrade `check`: seal-drift WARNING on LOG-PWR-001
   (`edited while uncaptured … d141e66be61d4851 … Run 'refdes history
   capture LOG-PWR-001'`). Ran it → `captured LOG-PWR-001: manual
   capture`. Status/link warning fixed by `status: candidate` on the
   unselected second-source part.
7. `refdes fetch --update --path …`: re-pinned (`kept`), pages-unchecked
   row names the command, page count fails on the stub PDF (quoted).
8. `refdes build` exit 0, site written. `refdes revision
   post-upgrade` stamped; `audit` then reads `changed 0 … (8 unchanged)`.
9. Seals/baselines (task step 4): baseline carried forward by the
   upgrade, then `uncomparable 5 — older-format entries whose stored
   hash can't be checked against the current definition -- not counted
   as changed; … stamp a new baseline`. The append-only seal is NOT
   carried by the upgrade (it carries baselines and history-layer seals;
   log-seal hashes move with the v3 hash change): legacy row
   `(legacy seal: recorded hash only; original content was not
   captured)` + the warning above; warning-level, exit stays 0.
10. `check --refresh` against a dead citation server: ERROR `could not
    refresh … upstream drift was NOT verified …`, exit 1; with
    `--allow-unreachable`: same text as WARNING, exit 0 (both exit codes
    captured directly).

## Facts for the two new fragments

- `hardware3-init-pins-v3.breaking.md`: v0.5.0 `init` wrote
  `refdes.yaml` pinned `version: 2`; current `init` writes
  `refdes-project.yaml` printing `standard: hardware@3` (run in
  `.scratch/init-now`); `latest_version` pinning in
  `src/refdes/scaffold.py:836`; v3 shipped by 50cf460; docs/standard-
  library.md: hardware@3 ships no presets, v1/@2 frozen.
- `body-fold-text-method.breaking.md`: `v3/migration.yaml` `fields:` =
  requirement/bound `text:`→`body:`, test `method:`→`body:`, component
  `datasheets:`→`citations:`; refusal path =
  `revise.check_body_merge_conflicts` (docstring quoted there: rename
  into reserved `body:` would orphan one of the two texts; caught before
  writing). Both migrations observed running in step 5 above.

## Gaps (breaking changes with no upgrade PATH I could find)

1. Citation `url:`→`path:` / `vendor:`→`keep_copy:` while pinned at
   hardware@2 with a red build: the error message points at
   `refdes standard upgrade`, which refuses red builds — circular
   remedy. The page documents the manual edits (the message's other
   sentence) as the real path; the tool has no command that closes this
   loop (e.g. a citation-only rewrite).
2. `check --refresh` CI drift-guard: `--allow-unreachable` restores the
   old exit-code posture, but that IS a capability loss (unverified
   sources pass) — the fragment says so; recorded here as inherent, no
   path recovers both.
3. `design-debate` preset projects at v3: no migration command (migrate
   to plain logs by hand, or declare the 4 types in your own schema).
   Fragment self-declares this; the guide's table carries it.
4. Colon-unit calc lines inside SEALED entries: warning-only forever
   (the tool refuses to edit sealed history); no reseal flow was run
   here, so no verified remedy is quoted in the page.
5. `vocab-p9` (mode `log`→`timeline`) and P2 (`history:`→`on_change:`):
   no automated path exists (`refdes rename` renames keys, not values;
   `revise` can't express them) — per their own fragments; the guide
   states "rename by hand". Not gaps in the guide; gaps in tooling,
   listed for completeness.

## Not reproduced (clean-probe limitation)

Duplicate-key (item/config), scalar-for-list, confident-typo,
verb-named-reserved-key, `field_sets:` error: the probe project carried
none of these shapes. Their symptoms/fixes in the guide table are
described from the fragments (validated against main in #344), not
quoted as probe output — the page quotes verbatim only what this probe
emitted.

## Gates

- Full suite (foreground): `4394 passed, 2 skipped in 483.46s`, exit 0.
- `ruff check` not run repo-wide (not a valid gate — AGENTS.md);
  changes here are docs/fragments only, no Python touched.
