# CLI reference

```
refdes [-c CONFIG] {build,check,revision,release,index,id,fetch,audit,init,new,schema,standard,revise,stub-tests,former-ids} [options]
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

Validate without rendering. Faster, and verifies existing seals without creating
new ones — which makes it the right command for CI and pre-commit hooks. Nothing
of the project's own is written: no site, no seal, no board or citation manifest,
no baseline. (`.refdes/schema.json`, the gitignored editor-completion schema, is
refreshed by every command that loads the project, this one included.)

```bash
refdes check
```

```
ERROR   items/decisions/dec-pwr-001-regulator-topology.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING <project> — 1 item(s) with no coverage — see coverage.html
20 items, 1 errors, 8 warnings
```

(Wrapped here for the page; the tool prints each diagnostic on one line.)

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
  FAIL     uncovered_requirements BND-THM-002
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
Also expands a quoted bare number (`id: "042"`) into a full id against its
prefix, freezing the author's own chosen number rather than picking the next
free one — see [choosing your own number](ids.md#choosing-your-own-number).

| Option | Effect |
|---|---|
| `--dry-run` | Show what would be allocated, write nothing |

```bash
refdes id --dry-run
refdes id
```

```
allocated REQ-PWR-005  (items/requirements/power.yaml:36) The unit shall tolerate a reversed input without damage.
allocated 1 id(s)
```

Exits non-zero and prints the reason if a bare-numeric hint collides with an
id already used or burned — nothing is written for that item, but every
other pending item in the same run still allocates normally.

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
[former ids](ids.md#renumbering-former-ids).

```bash
refdes audit
```

```
Schema fields not tracked as 'invalidate':
  bound
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
library](standard-library.md#refdes-new-lt-type-gt).

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

## `refdes schema --graph`

Print Mermaid flowchart source describing the project's actual type/link
graph to stdout — the same resolved schema `--json` emits, walked with a
different renderer. Generated, not hand-drawn, so a preset or project
overlay changing a verb can't leave it silently stale. See [links and
traceability](links.md#starter-link-types) for a worked example, generated
against the bundled standard.

```bash
refdes schema --graph > graph.mmd
```

GitHub renders a ` ```mermaid ` fence natively in any Markdown file (README,
issue, wiki); paste the output into one, or into any other Mermaid renderer.

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

## `refdes standard upgrade --to N`

Move a project's pinned `standard.version:` forward, rewriting every item
file to match.

```bash
refdes standard upgrade --to 2
```

Each bundled standard version ships its own `migration.yaml` — the delta
from the version immediately before it (`hardware@2`'s renames
`constraint.title` to `constraint.text` and the `constraint` type to
`bound`, its `CON` prefix along with it). See [the versions shipped so
far](standard-library.md#the-versions-shipped-so-far). Upgrading across
several versions chains each intervening one's own migration, in order —
`v1→v2`, then `v2→v3`, and so on — never merged into one combined rename,
so a name a later version reuses (freed up by an earlier step) is never
mistaken for a collision. The bundled `hardware` standard has one step
today; the chaining is what keeps that true as it grows. Each step rewrites item
files, bumps `standard.version:` in `refdes.yaml`, and carries the affected
items' content hashes forward in every stamped baseline and seal file, the
same way `refdes revise` does (below) — see there for what that buys you.
A baseline stamped before it recorded which standard version it started at
(or stamped under `standard: none`) is left alone during a chained
upgrade, reported rather than guessed at, since there's nowhere recorded
to say where in the chain its hashes began.

Stops at the first version step that fails, leaving the project fully
valid at whatever version it reached — never partway through a single
step's own rewrite. Exits 1 on failure, 0 once every step to `--to N` has
applied.

> **The project must validate first — but a failing check is not that.**
> Both this and `refdes revise` refuse if the project doesn't validate: an
> item that doesn't parse, a missing required field, a link pointing at
> nothing, a schema the data no longer satisfies. The rule is that a hash
> change caused by the rename must not be able to hide behind an
> already-broken document.
>
> A failing `checks:` result is explicitly **not** a blocker. It means the
> arithmetic ran and the design does not currently meet a bound — the tool
> working, and a state a board sits in for weeks at a time. A rename moves
> the arithmetic and the limit together, so it cannot change a check's
> verdict, and blocking on one would make these commands unusable on
> exactly the projects most likely to need them.

---

## `refdes revise <mapping-file>`

Rewrite project-local vocabulary — type names, field names (scoped per
type), link verb names, id prefixes — across every item file in one
operation, from a hand-written mapping:

```yaml
# rename.yaml
types:
  constraint: bound
fields:
  constraint:      # keyed by the OLD type name
    title: text
links:
  refines: narrows
prefixes:
  CON: BND
```

```bash
refdes revise rename.yaml
refdes revise rename.yaml --dry-run   # show what would change, write nothing
```

For a bundled standard's own version upgrade, use `refdes standard upgrade
--to N` instead (above) — it needs no hand-written mapping. `revise` is
for your own project-local renames: something not part of the standard,
or a hand-rolled schema with no `standard:` pin at all.

Every rewrite is line-level surgical text editing — the same `id:`
write-back approach `refdes id` already uses — never a full YAML
re-serialization, which would silently destroy comments and formatting a
real item file relies on. The whole operation is computed and verified in
memory before anything touches disk: an ambiguous mapping (two old names
targeting the same new one, or a target name already in use) is refused
up front; a rename the rewrite can't locate, or that leaves the rewritten
project invalid, is refused and rolled back completely, never partially
applied. A type or required-field rename needs the schema to move with
the data — `revise` alone only touches item files, never `refdes.yaml`'s
own `types:`/`link_types:` — so on a hand-rolled schema, pair the rename
with your own edit to `refdes.yaml` (in whichever order makes both sides
agree once both are done).

**Structured references move; prose does not.** A link's own target list —
in either YAML spelling, `key: [A, B]` or a block sequence of `- A` entries
under a bare key — and a `checks:` entry's `against:` are rewritten along
with the ids themselves. An id written into a rationale, a log entry's body,
or a narrative page is deliberately left alone: rewriting prose means editing
a sentence, including sealed ones that are not supposed to change. What it
does instead is tell you, so the difference is never silent:

```
2 prose mention(s) of a renamed id left behind -- these no longer resolve,
and were not rewritten (a rename never edits prose):
  items/decisions/dec-pwr-001.md:36  CON-THM-001 -> BND-THM-001
  pages/overview.md:5  CON-THM-001 -> BND-THM-001
```

Fix each one by hand, or — usually better — record the old id once as a
[`former_ids:`](ids.md#renumbering-former-ids) entry on the renamed item, and
every mention of it resolves again, marked "(formerly CON-THM-001)", with no
historical sentence edited at all.

Every affected item's content hash is carried forward, id by id, in every
stamped baseline **and** every seal file (`.refdes/log-seal*.yaml`) — not
just baselines. The same hash drives both: a baseline that doesn't carry
it forward reports a purely cosmetic rename as a changed item; a seal that
doesn't is worse, since a seal mismatch on a sealed `log` entry is a build
**error**, not a diff — carrying it forward is what keeps a cosmetic
rename from turning a clean build into a failing one.

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
wrote 3 stub(s) to items/power/stub-tests.md: REQ-PWR-004, REQ-PWR-005, BND-THM-002
wrote 3 stub test(s) across 1 file(s)
Run 'refdes id' to allocate ids for the new items.
```

The generated items carry the verifier type's own default prefix (`TST`),
not one derived from the board they land in — so in a project whose boards
declare `token:`, each stub trips the token lint until its `prefix:` is
edited. Do that before `refdes id`, since an id is frozen once allocated.

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

## `refdes former-ids propose`

Infer old-to-new id mappings after a renumbering, and write `former_ids:`
only for the ones you confirm. See [renumbering](ids.md#renumbering-former-ids).

| Option | Effect |
|---|---|
| `--baseline NAME` | Compare against this baseline instead of the most recently stamped one |
| `--confirm OLD_ID[,OLD_ID...]` | Write `former_ids:` for these candidates, and only these |

```bash
refdes former-ids propose
refdes former-ids propose --confirm CAN_00,CAN_01
```

Compares the most recent [baseline](lifecycle.md) snapshot to the live
project: an id that was there at baseline time but is gone now, matched by
title similarity against a same-type id that's new since, is a candidate,
shown with its confidence:

```
$ refdes former-ids propose
1 candidate former-id mapping(s):
  CAN_00 (requirement 'The bus shall recover...') -> REQ-CAN-001 ('The bus shall recover...')  confidence 94%

Nothing written. Re-run with --confirm OLD_ID[,OLD_ID...] to record the ones you accept as former_ids:.

$ refdes former-ids propose --confirm CAN_00
wrote former_ids: [CAN_00] to REQ-CAN-001 (items/can/requirements.yaml)
```

**Nothing is ever written without `--confirm`, and only for the ids it
names.** This mirrors how a schematic annotation tool works: it proposes a
renumbering, a person reviews it, and only the accepted mappings become
real. A wrong link in a traceability tool is worse than a missing one, so
inference only ever drafts a suggestion here — the `former_ids:` entry
`--confirm` writes is what build actually reads afterward, never a fuzzy
match recomputed on the fly. An id passed to `--confirm` that isn't among
the currently proposed candidates is refused, not guessed at — re-run
`propose` without `--confirm` first if the project has changed since.

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
| `.refdes/baselines/<name>.yaml` | **yes** | One file per `refdes revision`/`refdes release` stamp. Not rewritten by any ordinary command; `refdes revise` and `refdes standard upgrade` do edit it, to carry an item's content hash across a rename |
| `.refdes/schema.json` | **no, gitignored** | The project's merged JSON Schema, for editor completion; rewritten by every command that loads the project |
| `.refdes/vendor/` | **no, gitignored** | Vendored datasheet bytes, content-addressed by sha256; written only by `refdes fetch --url ... ` for a citation with `vendor: true` |
| `_site/` | no | Generated output |

Source files are also rewritten by `refdes id`, which inserts allocated IDs in
place. `.refdes/citations.yaml` and `.refdes/vendor/` are the only things
`refdes fetch` writes — `build` and `check` (without `--refresh`) never touch
either.
