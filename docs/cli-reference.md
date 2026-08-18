# CLI reference

```
refdes [-c CONFIG] {build,check,revision,release,index,id,fetch,audit,init,new,schema,standard,stub-tests} [options]
```

| Global option | Effect |
|---|---|
| `-c`, `--config PATH` | Use this `refdes.yaml`. Default: search upward from the current directory. |

Exit codes: `0` success, `1` errors found, `2` configuration error.

---

## `refdes build`

Validate, evaluate, and render the site plus `items.json`.

| Option | Effect |
|---|---|
| `-o`, `--out DIR` | Output directory, overriding `site.out` |
| `--keep-going` | Exit 0 even when there are errors |
| `--reseal [BOARD]` | Accept edits to sealed append-only entries. Bare, accepts every board's; name one board to scope it, e.g. `--reseal power` |
| `--accept-board-move` | Accept a recorded [board](multi-board.md) or [workspace](workspaces.md) change for an item |
| `--require-citations` | Promote the unpinned-citation (info) and missing-cache-blob (warning) [citation](markdown.md#citing-a-datasheet) diagnostics to errors |

```bash
refdes build
refdes build -o public --keep-going
refdes build --reseal power
```

Build also **seals** any new [log entries](design-log.md) it finds. Seals are
stored per board — `.refdes/log-seal-<board>.yaml` for a registered board's own
entries, `.refdes/log-seal.yaml` for entries with no board (the only file used
at all when the project has no `boards:` registry). `--reseal <board>` only
accepts edits to that board's own entries; every other board's still fail as a
normal violation.

`--keep-going` is for local iteration when you want to look at the site despite a
failing check. Do not use it in CI — it defeats the point.

---

## `refdes check`

Validate without rendering. Faster, writes nothing, and verifies existing seals
without creating new ones — which makes it the right command for CI and pre-commit
hooks.

```bash
refdes check
```

```
ERROR   items/decisions/dec-pwr-001-regulator-topology.md:2 [DEC-PWR-001] —
        P_dens violates CON-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING <project> — 1 item(s) with no coverage — see coverage.html
20 items, 1 errors, 8 warnings
```

Errors go to stderr, warnings to stdout. Every diagnostic leads with
`file:line`, so editors and CI annotations can link straight to the source.

| Option | Effect |
|---|---|
| `--refresh` | Also re-fetch every pinned [citation](markdown.md#citing-a-datasheet) and report drift (network; writes nothing) |
| `--board NAME` | Only report diagnostics for one [board](multi-board.md)'s own items |
| `--workspace NAME` | Only report diagnostics for one [workspace](workspaces.md)'s own items |
| `-v`, `--verbose` | Also show info-level diagnostics |

`--board`/`--workspace` are report filters, not a smaller build: the whole
project is still parsed and every link still resolved, so a decision on one
board that `satisfies` a requirement on another still checks correctly. Only
what gets *printed* — and the item count in the summary line — is narrowed to
that scope's own items. A diagnostic that isn't attributable to any one item
(a project-level warning, for instance) is never hidden by either flag. The
two are combinable.

```bash
refdes check --board power
refdes check --workspace product-a
```

`--refresh` is the only thing that ever makes `check` touch the network, and
even then it writes nothing — it re-fetches each pinned citation to a scratch
buffer, compares hashes, and reports which items cite anything that drifted:

```bash
refdes check --refresh
```

```
1 citation(s) drifted from their pinned hash:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf
    pinned    a1b2c3...
    upstream  d4e5f6...
    cited by  CMP-PWR-001
```

Exits non-zero on drift, same as on any other error.

---

## `refdes revision <name>`

Cut an internal checkpoint. Stamps `.refdes/baselines/<name>.yaml`
unconditionally, past the always-on error floor — no readiness gate by
default. No flags; the name is the only argument.

```bash
refdes revision rev-c
```

```
41 items, 0 errors, 0 warnings

revision 'rev-c' stamped: 41 items.
  .refdes/baselines/rev-c.yaml
```

Re-running the same name with identical content is a no-op (exit 0, file
untouched); with different content it's an error (nothing written) — a
name is a permanent label once stamped. See
[lifecycle](lifecycle.md#edge-cases).

---

## `refdes release <name>`

Run the full readiness gate (`release_gate:` in `refdes-project.yaml`) and
stamp `.refdes/baselines/<name>.yaml` only if every enabled rule passes. On
failure, nothing is written and the blocking rules are printed. No flags —
running this when the project isn't ready *is* the check; there is no
`--dry-run`.

```bash
refdes release rev-b
```

```
41 items, 0 errors, 0 warnings

release 'rev-b' blocked -- not stamped:
  FAIL     draft_items            REQ-PWR-004, REQ-PWR-005
  FAIL     uncovered_requirements CON-THM-002
  pass     unpinned_citations
  pass     missing_vendored_copies
  skipped  unverified_requirements
  skipped  info_check_failures
  pass     unaccepted_board_moves
```

Fix what's listed and run it again. On success, a one-line nudge to record
the release in the [design log](design-log.md#after-a-release) — printed,
never auto-written. See [lifecycle](lifecycle.md) for the full readiness
gate, the baseline file's shape, `stamped_by`, and the diff `refdes audit`
surfaces against it.

---

## `refdes index`

Print `items.json` to stdout without rendering the site. Does everything `check`
does, and emits the export instead of a report.

| Option | Effect |
|---|---|
| `--compact` | Minified output, for tooling |

```bash
refdes index | jq '.coverage'
refdes index --compact
```

This exists for editor tooling and scripts that need the index on every save —
rendering hundreds of HTML files each time would make that unusable. Diagnostics
come back as structured JSON under `diagnostics`, so nothing has to parse console
output.

---

## `refdes id`

Allocate IDs for items that have none, writing them into the source files.

| Option | Effect |
|---|---|
| `--dry-run` | Show what would be allocated, write nothing |

```bash
refdes id --dry-run
refdes id
```

```
allocated REQ-PWR-005  (items/requirements/power.yaml:36)  The unit shall tolerate...
allocated 1 id(s)
```

Updates `.refdes/ids.yaml`. See [IDs](ids.md).

---

## `refdes fetch`

The **only** command that touches the network. Fetches every url a
`citations:` field declares, records its sha256 and fetch time in the
`.refdes/citations.yaml` lockfile, and vendors the bytes into
`.refdes/vendor/` for any citation that declares `vendor: true`. `build` and
`check` never do this themselves — see [citing a
datasheet](markdown.md#citing-a-datasheet).

| Option | Effect |
|---|---|
| `--item ID` | Fetch only this item's citations |
| `--url URL` | Fetch only this url |
| `--update` | Re-fetch even if already pinned |

```bash
refdes fetch
refdes fetch --item CMP-PWR-001
refdes fetch --url https://www.ti.com/lit/ds/symlink/tps62913.pdf --update
```

```
fetched  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=a1b2c3d4e5f6...  hash-only
1 citation(s) processed, 0 failed
```

Already-pinned urls are skipped (reported as `skipped`) unless `--update` is
given, so a routine re-run does not re-download anything. Updates
`.refdes/citations.yaml`, and `.refdes/vendor/` for any citation that opted
into vendoring.

---

## `refdes audit`

Report everything that has been made less visible: fields excluded from
invalidation, item-level overrides and their stated reasons, resealed log entries,
[board](multi-board.md) and [workspace](workspaces.md) moves, what's changed
since the last [revision and release](lifecycle.md), [blocked_by
chains](links.md#blocked-by-and-the-cascade-report), imported projects,
[citations](markdown.md#citing-a-datasheet), [parts](parts.md), and
[former ids](ids.md#renumbering-former_ids).

```bash
refdes audit
```

```
Schema fields not tracked as 'invalidate':
  constraint
    last_reviewed    ignore
    owner            log

Item-level overrides:
  REQ-PWR-004    owner -> ignore  — Owner rotates weekly during bring-up.

Append-only entries edited after sealing:
  (none)

Baselines:
  most recent stamp:   rev-c (revision, 2026-08-10T09:12:00Z)
  most recent release: rev-b (2026-07-02T16:40:00Z)

Since last revision (rev-c, 2026-08-10T09:12:00Z):
  changed   3   DEC-PWR-002, CMP-PWR-001, REQ-PWR-003
  added     1   TST-PWR-004
  removed   0
  (12 unchanged)

Since last release (rev-b, 2026-07-02T16:40:00Z):
  changed   9   CMP-PWR-001, DEC-PWR-001, DEC-PWR-002, REQ-PWR-002, ...
  added     4   TST-PWR-003, TST-PWR-004, DEC-PWR-003, CMP-PWR-005
  removed   0
  (7 unchanged)

Board moves since the manifest was last written:
  (none)

Workspace moves since the manifest was last written:
  (none)

Blocked chains:
  DEC-PWR-005 <- DEC-PWR-001 (on_hold, root)

Imported projects (read-only):
  platform       1 items pinned to 2026.3  <- ../platform/_site/items.json

Citations:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf
    unpinned       hash-only  cited by CMP-PWR-001

Parts:
  TPS62913       used by CMP-PWR-001 (component) — board: power

Former IDs:
  CAN_00         -> REQ-CAN-001

16 items audited (16 local)
```

The "Board moves" section only appears for a project that has declared a
`boards:` registry, and "Workspace moves" only for one that has declared
`workspaces:`. "Baselines" always appears — a project that has never run
`refdes revision`/`refdes release` (still in **draft**) shows `(none stamped
yet -- project is in draft)` there instead, and each "Since last..." section
shows `(no revision/release stamped yet)`. The "Citations" section only
appears for a project that declares a `citations`-typed field somewhere and
has at least one item using it; "Parts" only for one that has at least one
`part_number`, from either source — see [parts](parts.md). Each part gets
its own `— board(s):` line and, for a project with a `workspaces:`
registry, a `— workspace(s):` line the same way — a flat-layout project
never populates an item's workspace in the first place, so that line simply
never appears there rather than showing up empty.

---

## `refdes init`

Write a minimal `refdes.yaml` in the current directory, plus
`.vscode/settings.json`. See [the standard library](standard-library.md#refdes-init).

| Option | Effect |
|---|---|
| `--standard NAME` | Base standard to pin (default: `hardware`), or `none` for the fully self-declared escape hatch |
| `--preset NAME` | Layer a preset on top of the base (repeatable). Combined with `--standard none` is a load-time error. |

```bash
refdes init
refdes init --standard none
refdes init --preset design-debate
```

Refuses to run if `refdes.yaml` already exists in the current directory.

---

## `refdes new <type>`

Print a starter item's front matter for `TYPE` to stdout — any type in the
merged schema, standard or project-defined. See [the standard
library](standard-library.md#refdes-new-type).

```bash
refdes new decision > items/power/dec-005.md
```

An unknown type exits 1 with a did-you-mean suggestion, the same as an
unknown type anywhere else in the tool.

---

## `refdes schema --json`

Print the project's merged JSON Schema to stdout. The same document is
written to `.refdes/schema.json` by every command that loads the project
(`build`, `check`, `index`, `id`, `fetch`, `audit`, and this command
itself); this is the explicit, standalone form, for piping into something
else or inspecting directly. See [editor
support](standard-library.md#editor-support-json-schema-emission).

```bash
refdes schema --json > schema.json
refdes schema --json | jq '."$defs".decision__bare.properties'
```

---

## `refdes standard add-preset` / `remove-preset`

Change `standard.presets:` with validation and reporting. See [the standard
library](standard-library.md#presets).

```bash
refdes standard add-preset design-debate
refdes standard remove-preset design-debate
```

`add-preset` validates the name exists at the project's pinned version
before adding it. `remove-preset` reports what the removal breaks — as
ordinary diagnostics, printed the same way `check`'s are — **before**
writing the config change, then writes it regardless; the command's job is
to surface the consequence, not to block an author who already decided to
accept it. Exits 1 if the report contains any error, 0 otherwise; either
way, the removal is applied.

---

## `refdes stub-tests`

Generate a starter test item for every coverable item that has no
verifying test yet, so a wall of coverage warnings becomes a checklist
instead of a blank page. See [coverage](coverage.md#stub-tests).

| Option | Effect |
|---|---|
| `--type NAME` | Which type to generate (only needed when more than one type declares a `verifies` link) |
| `--dry-run` | Show what would be written without writing |

```bash
refdes stub-tests
refdes stub-tests --dry-run
```

Writes one multi-item markdown file per board (or workspace), each holding
one stub per still-uncovered item in that scope — `verifies:` already
pointing at it, the type's own default `status:` (`planned` in the bundled
standard), and an empty `method:` if the type declares one. Refuses to run
if the project has any build error, the same posture `refdes id` and
`refdes revision`/`release` already take. Run `refdes id` afterward to
allocate the new items' ids.

```
$ refdes stub-tests
wrote 3 stub(s) to items/power/stub-tests.md: REQ-PWR-004, REQ-PWR-005, CON-THM-002
wrote 3 stub test(s) across 1 file(s)
Run 'refdes id' to allocate ids for the new items.
```

**Deduplicates by declared links, never text.** An item that already has a
verifying test — even one still `planned`, even one that hasn't been
allocated an id yet — is skipped, so running this twice in a row is safe
and never doubles up. Deleting a stub (or its whole file) makes its target
eligible again on the next run, automatically. **Refdes does not own test
items after they're written** — one test often verifies several
requirements and one requirement often needs several tests at different
corners, so restructure freely; the generated file is a starting point,
never something the tool goes on maintaining. A prior run's file is
appended to, never overwritten, so nothing already there is ever touched.

---

## Recipes

**Pre-commit hook** — `.git/hooks/pre-commit`:

```bash
#!/bin/sh
refdes check || exit 1
```

**CI step:**

```yaml
- run: refdes check
```

**Multi-project build order** — upstream first:

```bash
cd platform-interfaces && refdes build
cd ../board-a          && refdes build
```

**Serve the output locally:**

```bash
python -m http.server -d _site 8000
```

---

## Files the tool writes

| Path | Commit it? | Purpose |
|---|---|---|
| `.refdes/ids.yaml` | **yes** | Burned ID numbers; two branches sharing it prevents collisions |
| `.refdes/log-seal.yaml` | **yes** | Append-only seals for log entries with no board (the only file used at all when the project has no `boards:` registry) |
| `.refdes/log-seal-<board>.yaml` | **yes** | Append-only seals for one registered board's own log entries |
| `.refdes/boards.yaml` | **yes** | Board and workspace drift manifest; the `workspaces:` section only appears for a project that has declared `workspaces:` |
| `.refdes/citations.yaml` | **yes** | Citation lockfile (sha256, fetch time, vendored flag); written only by `refdes fetch` |
| `.refdes/baselines/<name>.yaml` | **yes** | One file per `refdes revision`/`refdes release` stamp; never modified after it's written |
| `.refdes/vendor/` | **no, gitignored** | Vendored datasheet bytes, content-addressed by sha256; written only by `refdes fetch --url ... ` for a citation with `vendor: true` |
| `_site/` | no | Generated output |

Source files are also rewritten by `refdes id`, which inserts allocated IDs in
place. `.refdes/citations.yaml` and `.refdes/vendor/` are the only things
`refdes fetch` writes — `build` and `check` (without `--refresh`) never touch
either.
