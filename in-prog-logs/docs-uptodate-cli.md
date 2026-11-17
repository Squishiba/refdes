# docs up-to-date: cli group (`docs/cli-reference.md`)

Scope: one page. Compared every section with `refdes <cmd> --help` and live
runs on scratch projects under `.scratch/uptodate-cli/` (PYTHONPATH always the
worktree `src`).

## Coverage check

- `refdes --help` commands vs page headings: all covered (`serve`, `build`,
  `check`, `revision`, `release`, `index`, `ls`, `thread`, `navis`, `work`,
  `id`, `fetch`, `audit`, `recover`, `init`, `new`, `schema`, `standard`,
  `keys`, `rename`, `calc-rewrite`, `stub-tests`, `former-ids`, `history`).
  No documented command has been removed; `revise` still exists hidden.
- Every flag table checked against `--help`: build, check, index, ls, thread,
  navis verbs, work, id, fetch, init, new, schema, standard add/remove/upgrade,
  keys adopt/restore, rename, calc-rewrite, stub-tests, former-ids, history,
  serve. No missing or extra flags.

## `docs/cli-reference.md` — changed

- Release sample: ran `refdes release` on a scratch project with a draft
  requirement; actual output has 11 rules in the order draft_items,
  unpinned_citations, missing_kept_copies, uncovered_requirements,
  unverified_requirements, info_check_failures, unaccepted_board_moves,
  unaccepted_workspace_moves, open_tasks, captured_edits,
  inline_calc_results (`src/refdes/lifecycle.py` `_RULES`/`RULE_NAMES`,
  `src/refdes/model.py` `RELEASE_GATE_DEFAULTS`). Updated the sample and
  described skipped/enabled rules. Success output is a multi-line design-log
  starter, not a "one-line nudge" (ran it).
- `--no-write`: `refdes --no-write navis archive 1` and `navis restore`
  both print `--no-write: ... refusing to run it under --no-write` and exit 2
  (`src/refdes/cli.py` `_refuse_no_write` callers). Added both to the list.
- `check --refresh`: `citations.refresh` skips local paths
  (`src/refdes/citations.py:3208-3209`); a changed local citation is a warning
  and exit 0, verified by editing a fetched CSV. Said "pinned remote
  citation".
- `keys restore`: ran it with a different key; the refusal names the item's
  *current* key recorded in history (`src/refdes/key_restore.py:170-180`,
  help text). Page said "replacement keys"; corrected.
- `former-ids propose`: on a clean project with no candidates,
  `--confirm NOPE-999` prints `no candidate former-id mappings found` and
  exits 0 (`src/refdes/cli.py:2768-2776`); qualified the refusal claim and
  documented the no-candidate case.
- `new`: `refdes new requiremen` → `Did you mean 'requirement'?`, while
  `new nonsense` and `new decision` print no suggestion (ran all three).
  Softened "with a did-you-mean suggestion".
- `.refdes/schema.json` writer list: `refdes navis ls` rewrote the schema
  after it was removed; added `navis` to the list.
- "Files the tool writes": added `.refdes/navis/` (gzip record per archived
  Navi, `navis-slice-3.added.md`; path confirmed by running archive).
- `history redact` sample event id shape corrected to the UUID form the run
  prints (`82a35309-...`).

## `docs/cli-reference.md` — checked clean (no change)

- build (`--reseal` history warning text reproduced; Draft build banner
  present), revision no-op/re-stamp, release exit codes, index always-present
  keys and exit 0 on parse error, ls (`--keys`, unknown filters, `--workspace ''`
  message, former_ids text), thread text/`--as-of`/`--keys`/`--json`, navis
  verbs/selectors/archive/show/restore/`--no-write`/`archived: none`, work
  text/`--json`/`--as-of`, id, fetch (summary, `--item`/`--path` refusals,
  local pin, `values:` prune line), audit sections, recover (no journal,
  inert journal, `--no-write`, pending journal gate), init (gitignore
  contents and skip rule, preset errors), standard add/remove-preset errors,
  standard upgrade `--to 3`/`4`/`x`, rename (unreadable/unknown-section
  refusals, no-op mapping), calc-rewrite no-op, stub-tests output,
  keys adopt plan/already-adopted, history capture/redact/migrate-seals,
  serve (token file 0600 + one line + newline, SIGTERM exit 0 and removal,
  non-launch-file refusal), files table and recipes.

## Fix round 1 (reviewer: false superlatives)

- (1) "the only one that writes what a fetch learns" -- false. `refdes serve`'s
  editor accept writes the same records: `citations.stage_source_pins`
  (`src/refdes/citations.py:2409`), called from `src/refdes/serve/edit.py:829`,
  and the lockfile header at `citations.py:1396` says both writers. Reworded
  to name the editor accept, no superlative.
- (2) `.refdes/navis/` "written and removed only by" the CLI -- false.
  `src/refdes/serve/navis_write.py` serves `POST /api/navis/archive` and
  `/api/navis/restore` over the same store. Row now names both writers.
- (3) "the rule list is the one `release_gate:` enables" -- misleading:
  `RULE_NAMES` is always all eleven (`src/refdes/lifecycle.py:913`,
  `evaluate_gate`), and the config only selects skipped vs pass/FAIL. First
  clause rewritten.
- (4) `.refdes/copies/` "written only by `refdes fetch --path ...`" -- false.
  `fetch_all` (`src/refdes/citations.py:2690`) builds `want_keep_copy` from
  every citation in scope and writes copies at `:3041-3055`; `--path` only
  narrows scope. Row now says `refdes fetch`.

Superlative audit (`git diff origin/main -- docs/cli-reference.md | grep '^+'
| grep -i -E '\bonly\b|\bnever\b|\balways\b|\bevery\b|\ball\b'`):

- `--no-write` "Never modify anything under `items/` or `.refdes/`" -- TRUE;
  write commands refuse, build writes only its site, serve writes its temp
  preview/token outside the project.
- `--refresh` "every pinned remote citation" -- TRUE; `citations.refresh`
  loops every remote citer with a record (`citations.py:3203-3228`).
- "re-hashed against its pin on every run" -- TRUE; local citations go
  through `verify()` in build/check.
- "touches the network only for remote" -- TRUE; local paths are read from
  disk (`fetch_all`, `classify`).
- "The list is always all eleven rules" -- TRUE; `RULE_NAMES` length 11.
- "Fetches every path a `citations:` field declares" -- TRUE unscoped;
  `--item`/`--path` narrow it, as the flag table says.
- "With no candidates at all, a clean project ..." -- TRUE; ran it.
- redaction "by digest and event id only" -- TRUE; copied from the run's
  own output.


## Could not verify

- `serve` port-in-use and symlinked `--token-file` refusals (no spare listener
  or symlink fixture made this pass); text left as written and consistent
  with `src/refdes/serve/`.
- Remote-only `check --refresh` drift/unreachable output (no network run);
  code path read in `src/refdes/citations.py` and page sample left unchanged.
- `keys restore` success write path and `standard upgrade --dry-run` on a
  v1 project (no fixture made); help/code read only.
- Plain `refdes fetch` keeping a remote copy (no network run); read
  `fetch_all` and the `want_keep_copy` write path instead.

## Tests run

- `pytest tests/test_docs_anchors.py tests/test_docs_examples.py
  tests/test_crossplatform_lint.py` → 34 passed.
- `python docs-site/gen_examples.py --check` → both pages up to date.
- Full suite once before each push (fix round 1: 6456 passed, 2 skipped).
