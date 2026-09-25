# CLI reference accuracy audit

Scope: `docs/cli-reference.md` only, checked against the `main` worktree at `99eabcd` with the repository virtual environment and `PYTHONPATH` pointed at this worktree's `src/`. Each top-level command is being checked in generated `--help` order. Behavioral probes use projects under `.scratch/cli-ref-audit/`; no source or test files are edited.

## Top-level help

`refdes --help` reports these 20 commands, in this order: `serve`, `build`, `check`, `revision`, `release`, `index`, `ls`, `id`, `fetch`, `audit`, `init`, `new`, `schema`, `standard`, `keys`, `revise`, `calc-rewrite`, `stub-tests`, `former-ids`, `history`.

**Proven discrepancy:** the synopsis at `docs/cli-reference.md:4` omits `keys`, `calc-rewrite`, and `history`, although all three have command sections later in the page. No edit applied yet; continue the one-command-at-a-time audit before changing the document.

The documented global flags and their placement before the subcommand match top-level help. Detailed `--no-write` behavior remains to be checked against representative write commands.

## `serve`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['serve','--help']))"`.
- Help exposes only `--no-open` beyond `-h`; the documented option is complete.
- Runtime probe: ran `refdes -c <scratch-project> serve --no-open` from the scratch project, confirmed it stayed running, printed a random-token URL on `127.0.0.1`, then stopped it. Exit could not be observed because the normal command is intentionally long-running; startup emitted no stderr.
- After startup, the project still contained only `refdes-project.yaml` (no `_site/`, `.refdes/`, or `items/` output), confirming the documented load-time no-write behavior for this probe.
- No discrepancy found.

## `build`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['build','--help']))"`.
- **Proven discrepancy:** generated help includes `-v, --verbose` (“also show info-level diagnostics”), but the `build` option table omits it. The other generated flags match the table.
- A clean scratch build exited 0 and wrote `_site/`; `build -o audit-out` exited 0 and wrote the override directory.
- A separate project with a missing link target exited 1. Repeating `build --keep-going` on the same project printed the error, wrote the site, and exited 0.
- `build --dry-run` exited 0, wrote real HTML to the requested output, reported “(dry run, not sealed),” and put the documented “Draft build — not sealed” banner on every page. In the reseal probe, a newly added log entry remained absent from `.refdes/log-seal.yaml` after the dry run, confirming that only sealing was skipped.
- A sealed-log probe failed with exit 1 after an edit; `build --reseal` then exited 0 and emitted the documented reseal warning. In a board-scoped project the first seal was `.refdes/log-seal-power.yaml`; `--reseal signal` left the power edit as an error (exit 1), while `--reseal power` accepted it (exit 0).
- A board-move probe showed the recorded move as a warning. `build --accept-board-move` accepted and recorded it (still with a warning), matching the documented option effect.
- With one unpinned citation, `build -v` exposed the info diagnostic and exited 0; `build --require-citations` promoted it to an error and exited 1.
- On a fresh project, global `--no-write` before `build` still wrote `_site/` but no `.refdes/schema.json` or other project metadata, matching the global-option explanation.
- No other discrepancy found.

## `check`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['check','--help']))"`.
- Generated flags match the documented `--refresh`, `--board`, `--workspace`, and `-v` set.
- Stream-capture probe on a broken link confirmed the documented split: the error was on stderr, the warning and summary on stdout, and the exit code was 1.
- A fresh valid project exited 0 and created only `.refdes/schema.json`; it did not create `_site/`, a baseline, or a board manifest. Adding a new log entry and rerunning `check` did not create `.refdes/log-seal.yaml`.
- **Proven discrepancy:** despite the paragraph saying `check` writes no project files except `.refdes/schema.json`, a normal `check` inserted a missing surrogate `key:` into an item and expanded a resolving `refines:` target from bare `REQ-PWR-001` to `REQ-PWR-001@x1gzeefmhta`. This is real source write-back, not just schema refresh. The documentation must describe these load-time writes (and direct readers to global `--no-write` to suppress them).
- On a fresh linked project, global `--no-write` before `check` left both files byte-for-byte in bare form and created no `.refdes/` directory at all, confirming the suppression behavior described globally.
- In a two-workspace/two-board project, unfiltered `check` printed both item errors; `--board board-a` and `--workspace alpha` each printed only the matching item and narrowed the item summary from 2 to 1 while retaining the project-level warning. Combining mismatched `--board board-a --workspace beta` printed no item errors, reported `0 items`, and exited 0. This confirms the documented filter-only and combinable behavior.
- A local HTTP citation fixture was fetched and pinned, then `check --refresh` exited 0 with no drift. After the served bytes changed, the same command printed the documented pinned/upstream/cited-by block and exited 1; `.refdes/citations.yaml` retained the original pin, confirming that refresh reports without updating it.
- `check -v` exposed the unpinned-citation info diagnostic and exited 0, matching the flag.
- No other discrepancy found.

## `revision`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['revision','--help']))"`.
- Help requires exactly one positional `name` and exposes no command-specific option beyond `-h`, matching the documentation. It also explicitly describes global `--no-write` as a report-only mode.
- On a valid project with a warning, `--no-write revision rev-c` exited 0, printed “would stamp,” and created no `.refdes/` directory. A normal `revision rev-c` then exited 0 and wrote `.refdes/baselines/rev-c.yaml`, confirming that the normal revision path does not apply the release readiness gate.
- An immediate identical re-run exited 0 and left the baseline SHA-256 unchanged. After changing the authored Markdown content, the same name exited 1 and again left the baseline unchanged, matching the permanent-name behavior.
- On the project with a missing-link error, `revision rev-error` exited 1 and created no baseline, confirming the unconditional error floor.
- No discrepancy found.

## `release`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['release','--help']))"`.
- Help requires exactly one positional `name`, has no command-specific option beyond `-h`, explicitly has no `--dry-run`, and describes global `--no-write`; this matches the documentation.
- An uncovered-requirement project exited 1, printed `release 'rev-b' blocked -- not stamped` with `FAIL uncovered_requirements`, and created no baseline.
- A covered-requirement/passing-test project exited 0, stamped `.refdes/baselines/rev-b.yaml`, and printed the documented design-log nudge. On the same passing project, `--no-write release rev-c` exited 0, printed “would stamp,” and did not create `rev-c.yaml`.
- No discrepancy found.

## `index`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['index','--help']))"`.
- Help exposes only `--compact` beyond `-h`, matching the documented option table.
- A normal run emitted the merged index as indented JSON and exited 0 without creating `_site/`. `--compact` emitted the same document as one minified JSON line and exited 0.
- In a project with one valid item and one syntactically broken YAML file, the JSON still parsed, contained the valid item, and the process exited 0; the parse error was on stderr. This confirms both the partial-output and deliberate exit-0 claims.
- No discrepancy found.

## `ls`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['ls','--help']))"`.
- **Proven discrepancy:** help declares the positional as `query ...`, and `ls current limit` successfully matched the title “Current limit audit.” The option table currently labels it singular `QUERY` and does not say that multiple query words are accepted.
- The documented `--type`, `--board`, `--file`, and `--tag` flags match help. Runtime probes narrowed by component, signal board, source file, and a case-insensitive tag substring, each exiting 0 with the expected rows.
- Free-text matching was confirmed against both a multiword title and a tag whose text was absent from the title. A no-boards project omitted the board column, matching the documented conditional layout.
- A project containing a broken YAML file printed the parse error plus the valid rows and exited 1, matching the documented incomplete-answer behavior.
- With `lint_own_tags: true`, `check` warned both for an item whose tags were entirely inherited and for an item with no tags, confirming the setting's documented default-off warning behavior. (`ls` itself prints the listing and does not print diagnostics.)
- No other discrepancy found.

## `id`

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['id','--help']))"`.
- Help exposes only `--dry-run` beyond `-h`, matching the documented option table.
- A dry run correctly previewed allocation of an unnumbered item and a quoted numeric hint (`REQ-PWR-007`), then a normal run allocated both and wrote `.refdes/ids.yaml`.
- **Proven discrepancy:** ordinary `id --dry-run` is not write-free. It inserted missing `key:` fields into the source items (and refreshed `.refdes/schema.json`) while leaving their ids absent. The truly side-effect-free form is global `--no-write` before `id` (with or without `--dry-run`); that form previewed the allocation and left the source and `.refdes/` directory untouched.
- **Proven discrepancy:** when a markdown item starts with the documented `id: "007"` form, a normal `id` run inserts `id: REQ-PWR-007` but leaves the original `id: "007"` line in place, yielding duplicate `id` keys in the front matter. The same happened in a bulk YAML probe. The docs currently say it expands the hint, so this behavior needs to be stated accurately or the source bug fixed separately.
- Follow-up on that duplicate: the quoted value wins on the next load, so the affected item reports `ERROR items/hint.md:2 — id: 007 has no prefix yet -- run 'refdes id' to expand it into a full id` and `check` exits 1, and a second `refdes id` run refuses the same item with `id: 007 would expand to 'REQ-PWR-007', but that number is already used or was burned`. The documented quoted-hint flow is therefore self-stuck after one run; this is a source bug, not a documentation choice, and is called out in the `id` section of the reference.
- A collision probe (`id: "001"` against a live `REQ-PWR-001`) printed the refusal, still allocated an unrelated pending sibling, and exited 1, matching the documented partial-progress behavior. A project with a load error printed the parse error and exited 1 without claiming there were no missing ids.
- No other discrepancy found.

## `fetch` (partial — stopped before the `section:`-PDF probe)

- Generated help: `python -c "import sys;from refdes.cli import main;sys.exit(main(['fetch','--help']))"`.
- Help's `--item`, `--path`, and `--update` flags and its remote/local description match the documented flags and scope.
- A local HTTP fixture plus a project-local file verified both paths: the remote citation was fetched and kept under `.refdes/copies/` only because `keep_copy: true`; the local citation was hashed without a kept copy. The lockfile recorded bytes, fetch time, kept-copy flag, and sha256 as documented.
- A second `fetch` reported already-pinned paths as `skipped`; `--path` fetched only the requested unpinned path; changing the served bytes and rerunning without `--update` skipped them, while `--update` re-pinned them. A changed project-local file was reported as skipped with the documented “locked source values are kept” guidance, and `--update` printed the changed value transition.
- A calc `source("analysis/power.csv", "rail_eff") | 1` fixture confirmed that `fetch` extracted and stored the used key under the lockfile record's `values:`.
- `--no-write fetch` refused with exit 2 and did not run, matching the global-option table.
- A PDF fixture with a `section:` citation was prepared, but the command was not run against it before the audit was stopped. No fetch documentation change is proposed.

## Audit status at handoff

### (a) Commands fully audited

1. `serve`
2. `build`
3. `check`
4. `revision`
5. `release`
6. `index`
7. `ls`
8. `id`

### (b) Commands not yet audited

1. `audit`
2. `init`
3. `new`
4. `schema`
5. `standard` (including `add-preset`, `remove-preset`, and `upgrade`)
6. `keys` (including `adopt`)
7. `revise`
8. `calc-rewrite`
9. `stub-tests`
10. `former-ids` (including `propose`)
11. `history` (including `capture`, `redact`, and `migrate-seals`)

`fetch` is partial as described above. The scratch HTTP fixture was stopped; no probe process was left running.

## Wrap-up (audit split into smaller chunks)

- Only `docs/cli-reference.md` was edited, and only for discrepancies proven above: the usage line (all twenty subcommands plus global `--no-write`), `build`'s missing `-v/--verbose`, `check`'s "nothing is written" claim, `ls`'s `query ...` arity, `id --dry-run`'s write-free claim, and the quoted-hint expansion bug.
- Added `changelog.d/cli-reference-audit.fixed.md` covering the same six changes.
- No source or test file was modified.
- Gates: `python -m pytest -q -x` → 2123 passed; `python -m ruff check --select E9,F src tests` → all checks passed.
- A `section:`-PDF fixture was prepared in `.scratch/cli-ref-audit/fetch-section/` (PDF and item written) but `fetch` was never run against it; that probe is the first thing to pick up if the `fetch` audit resumes.
- Source bug worth a follow-up issue: `refdes id` expanding a quoted bare-number hint leaves the quoted line in place, which permanently breaks the item (`check` errors, second `id` run refuses it as burned). Not fixed here — out of scope for a docs-only audit.
