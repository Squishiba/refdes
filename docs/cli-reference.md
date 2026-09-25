# CLI reference

```
refdes [-c CONFIG] [--no-write] {serve,build,check,revision,release,index,ls,id,fetch,audit,init,new,schema,standard,keys,revise,calc-rewrite,stub-tests,former-ids,history} [options]
```

| Global option | Effect |
|---|---|
| `-c`, `--config PATH` | Use this `refdes-project.yaml`. Default: search upward from the current directory. |
| `--no-write` | Never modify anything under `items/` or `.refdes/`. Suppresses: key minting, link/check expansion to composite form, `.refdes/schema.json` regeneration, seal recording, board/workspace membership manifest, baseline stamping, and the ID ledger. Explicit write commands behave differently: commands with `--dry-run` (`id`, `revise`, `stub-tests`) report what would change and write nothing; `revision`/`release` report "would stamp" and write nothing; `keys adopt` reports the full plan and writes nothing; commands that fundamentally write (`fetch`, `init`, `standard upgrade`, `standard add-preset`, `standard remove-preset`, `former-ids propose --confirm`) **refuse to run** under `--no-write` and exit 2. `refdes build --no-write` still writes the site — that is the command's own output, not a side effect. |

Exit codes: `0` success, `1` errors found, `2` configuration error (including `--no-write` refusal).

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
| `--dry-run` | Render the site without sealing |
| `-v`, `--verbose` | Also show info-level diagnostics (routine states hidden by default) |

```bash
refdes build
refdes build -o public --keep-going
refdes build --reseal power
refdes build --dry-run
```

Build also **seals** any new [log entries](design-log.md) it finds. Seals are
stored per board — `.refdes/log-seal-<board>.yaml` for a registered board's own
entries, `.refdes/log-seal.yaml` for entries with no board (the only file used
at all when the project has no `boards:` registry). `--reseal <board>` only
accepts edits to that board's own entries; every other board's still fail as a
normal violation.

`--dry-run` skips only that seal-recording side effect — the site is still
rendered for real, to the same output directory, watermarked with a "Draft
build" banner on every page. This is different from `id`/`revise`/
`stub-tests`'s own `--dry-run`, which print a preview and write nothing: the
whole point of running `build` is the rendered site, so a dry-run that wrote
no HTML would be useless for "let me see what this looks like without
committing to it yet."

`--keep-going` is for local iteration when you want to look at the site despite a
failing check. Do not use it in CI — it defeats the point.

---

## `refdes check`

Validate without rendering. Faster, and verifies existing seals without creating
new ones — which makes it the right command for CI and pre-commit hooks. No
rendered output, no new seal, no board or citation manifest, and no baseline is
written. Loading the project can still write back surrogate `key:` fields and
expand resolvable link and `check` targets to composite form, and
`.refdes/schema.json` (the gitignored editor-completion schema) is refreshed by
every command that loads the project, this one included. Run
`refdes --no-write check` for a run that writes none of those either.

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
name is a permanent label once stamped. If the existing baseline carries
older-format entries whose stored hashes can't be checked against the current
definition, the conflict output names them on an `uncomparable N` line first —
part of the mismatch may be the hash definition having moved, not content.
See [lifecycle](lifecycle.md#edge-cases).

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
  pass     missing_kept_copies
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

An items file that fails to parse is printed to stderr — but `index` still emits
the JSON for everything that did load, and still **exits 0**. It is the one
command whose exit code is deliberately left alone: the VS Code extension
discards the whole index on a non-zero exit, so a half-typed YAML file mid-edit
would blank the editor on every save.

---

## `refdes ls`

List existing items as aligned text: id, type, board, title. `index`'s
CLI-native counterpart — the same underlying data, filterable and readable
without piping it through something else. For anyone not using the VS Code
extension: a quick check over SSH, a scripted query, or deciding what to
reference while reviewing a PR diff.

| Option | Effect |
|---|---|
| `--type TYPE` | Only items of this type |
| `--board BOARD` | Only items on this board |
| `--file PATH` | Only items declared in this source file |
| `--tag TEXT` | Only items with a tag containing this text |
| `QUERY ...` (positional, optional) | Free text, matched against title and `tags:`, case-insensitive. Zero or more words; the whole quoted string is the query, as in `refdes ls "current limit"` |

```bash
refdes ls
refdes ls --type bound --board platform
refdes ls --file items/common/power.yaml
refdes ls "current limit"
refdes ls --tag "current limit"
```

An items file that fails to parse is printed to stderr and `ls` exits 1 — the
listing of what did load is unchanged, it simply no longer passes for a
complete answer.

The board column is omitted entirely when the project has no `boards:`
registry, matching every other place board is conditionally shown.

Free text matches `tags:` as well as the title — deliberately, since the
real recall pattern is usually "I remember it was something about a current
limit," not the exact wording or the id. `tags:` is `on_change: ignore`, so
retagging never invalidates anything downstream; that asymmetry is what
makes it the right place to invest in findability, and what makes searching
it (not just the title) worth having. `--tag` narrows to tag-only matching,
for when that's specifically what's meant.

**`lint_own_tags: true`** in `refdes-project.yaml` (default off) warns on an
item whose `tags:` are entirely inherited from its file's `defaults:` — as
hard to find later as having none, since a file-level tag set is identical
across every item in the file and just re-encodes which file it's already
in. Off by default: `tags:` is optional, and plenty of projects won't want
the noise. Worth turning on once `refdes ls --tag`/free-text search is
actually part of how the project finds things — flagging under-tagged items
is only useful once something can act on the flag.

---

## `refdes id`

Allocate IDs for items that have none, writing them into the source files.
Also expands a quoted bare number (`id: "042"`) into a full id against its
prefix, freezing the author's own chosen number rather than picking the next
free one — see [choosing your own number](ids.md#choosing-your-own-number).
The expansion replaces the hint line wherever in the item's front matter or
list entry it sits, so the file never ends up holding two `id:` keys.

| Option | Effect |
|---|---|
| `--dry-run` | Show what would be allocated and skip the `id:` write-back. It is not write-free: loading the project can still mint missing surrogate `key:` fields and refresh `.refdes/schema.json`. Put the global `--no-write` first for a preview that writes nothing at all. |

```bash
refdes id --dry-run
refdes --no-write id --dry-run
refdes id
```

```
allocated REQ-PWR-005  (items/requirements/power.yaml:36) The unit shall tolerate a reversed input without damage.
allocated 1 id(s)
```

Exits non-zero and prints the reason if a bare-numeric hint collides with an
id already used or burned — nothing is written for that item, but every
other pending item in the same run still allocates normally.

An item in a file that failed to parse is not pending either, so when there
are load errors `id` prints them and exits 1 instead of reporting "no items
are missing an id" about files it never read.

Updates `.refdes/ids.yaml`. See [IDs](ids.md).

---

## `refdes fetch`

The **only** command that touches the network — and only for remote
(`http`/`https`) citations. Fetches every path a `citations:` field declares,
records its sha256 and fetch time in the `.refdes/citations.yaml` lockfile,
and keeps the bytes in `.refdes/copies/` for any remote citation that
declares `keep_copy: true`. A local path is read from disk instead, so pinning
one works with the network down. `build` and `check` never do this themselves
— see [citing a datasheet](markdown.md#citing-a-datasheet).

| Option | Effect |
|---|---|
| `--item ID` | Fetch only this item's citations |
| `--path PATH` | Fetch only this cited path (url or project-relative file) |
| `--update` | Re-fetch even if already pinned |

A citation's `section:` is resolved here and nowhere else: the PDF's own
outline is read once, at fetch time, and the page it points at is recorded in
the lockfile. This is the only part of refdes that reads a PDF, and it needs
the optional extra — `pip install refdes[pdf]`.

A local file cited by a calc [`source("path", "key")`](math.md#reading-a-value-from-a-source-file)
line also has each used key extracted and pinned under its lockfile record
(`values:`), atomically with the file hash: if any key cannot be read, the old
record is left exactly as it was. Without `--update`, missing keys are
extracted only while the file still matches its pin; a changed file is skipped
(its locked values are kept) or, when a key was never extracted, refused --
`--update` accepts the change and prints each moved value as `old -> new`.

```bash
refdes fetch
refdes fetch --item CMP-PWR-001
refdes fetch --path https://www.ti.com/lit/ds/symlink/tps62913.pdf --update
```

```
fetched  https://www.ti.com/lit/ds/symlink/tps62913.pdf  sha256=a1b2c3d4e5f6...  hash-only
         section 'Application and Implementation' -> page 14
1 citation(s) processed, 0 failed
```

Already-pinned paths are skipped (reported as `skipped`) unless `--update` is
given, so a routine re-run does not re-download anything — but a `section:`
added since the last run is still resolved then, from the bytes already on
disk, and only if those bytes are still the pinned ones: a local file that has
moved since it was pinned is not resolved against, and says to run `--update`
instead. Resolution covers every section any item in the project cites for the
path being pinned, not just the ones inside `--item`/`--path` scope — a page
number is a fact about the bytes being pinned, so re-pinning a file under one
item cannot leave another item's section pointing at the bytes it replaced.
Updates `.refdes/citations.yaml`, and `.refdes/copies/` for any citation that
opted into keeping a local copy.

A `section:` that cannot be resolved is reported as its own `FAILED` line and
makes the exit code nonzero, even though the pin itself succeeded — see
[citing a section by name](markdown.md#citing-a-section-by-name) for the six
things that can go wrong and what each one says.

---

## `refdes audit`

Report everything that has been made less visible: fields excluded from
invalidation, item-level overrides and their stated reasons, resealed log entries,
orphaned ledger allocations, [board](multi-board.md) and
[workspace](workspaces.md) moves, what's changed since the last [revision and
release](lifecycle.md), [blocked_by
chains](links.md#blocked-by-and-the-cascade-report), imported projects,
[citations](markdown.md#citing-a-datasheet), [parts](parts.md), and
[former ids](ids.md#renumbering-former-ids).

```bash
refdes audit
```

An items file that fails to parse is printed to stderr and `audit` exits 1 — an
audit that quietly omits a whole file is exactly the invisible suppression this
command exists to catch. The report itself is unchanged.

```
Schema fields not tracked as 'invalidate':
  bound
    last_reviewed    ignore
    owner            log

Item-level overrides:
  REQ-PWR-004    owner -> ignore  — Owner rotates weekly during bring-up.

Append-only entries edited after sealing:
  (none)

Ledger entries with no live item and no former_ids: explaining them:
  (none)

Baselines:
  most recent stamp:   rev-c (revision, 2026-08-10T09:12:00Z)
  most recent release: rev-b (2026-07-02T16:40:00Z)

Since last revision (rev-c, 2026-08-10T09:12:00Z):
  changed   3   DEC-PWR-002, CMP-PWR-001, REQ-PWR-003
  added     1   TST-PWR-004
  removed   0
  relabelled 1
    REQ-PWR-009 -> REQ-PWR-012   (k7f3m2q9x4a)
  (12 unchanged)

Since last release (rev-b, 2026-07-02T16:40:00Z):
  changed   9   CMP-PWR-001, DEC-PWR-001, DEC-PWR-002, REQ-PWR-002, ...
  added     4   TST-PWR-003, TST-PWR-004, DEC-PWR-003, CMP-PWR-005
  removed   0
  relabelled 2
    REQ-PWR-009 -> REQ-PWR-012   (k7f3m2q9x4a)
    BND-THM-001 -> BND-THM-004   (m9n2b5v8c1w)
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
shows `(no revision/release stamped yet)`.

**`relabelled`** — items that have the same surrogate key but a new display ID.
This happens when an item is renamed (its `id:` changed) after a baseline was
stamped: the key is the immutable identity, so the baseline diff recognises it
as the same item and reports it as `relabelled` rather than `removed` + `added`.
Each one is listed on its own line under the count, with the surrogate key in
parentheses.

**`uncomparable`** — baseline entries in an older hash format whose stored hash
no longer checks out under that format's own definition (see
[hash format versioning](lifecycle.md#hash-format-versioning)). refdes cannot
tell whether the content moved or only the hash definition did, so these are
listed on their own `uncomparable N` line instead of under `changed`, and are
not counted as unchanged either. The line only appears when the count is
nonzero. What to do: review the item's content, then stamp a new baseline once
it has been reviewed. `refdes revision`/`refdes release` name the same entries
when re-stamping an existing name conflicts.

The "Citations" section only
appears for a project that declares a `citations`-typed field somewhere and
has at least one item using it; "Parts" only for one that has at least one
`part_number`, from either source — see [parts](parts.md). Each part gets
its own `— board(s):` line and, for a project with a `workspaces:`
registry, a `— workspace(s):` line the same way — a flat-layout project
never populates an item's workspace in the first place, so that line simply
never appears there rather than showing up empty.

---

## `refdes init`

Write a minimal `refdes-project.yaml` in the current directory, plus
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

Refuses to run if `refdes-project.yaml` already exists in the current directory.

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

Print the project's actual type/link graph as an SVG document to stdout —
the same resolved schema `--json` emits, walked with a different renderer.
Generated, not hand-drawn, so a preset or project overlay changing a verb
can't leave it silently stale. It is byte-for-byte the drawing every built
site puts at the top of its [vocabulary page](vocabulary.md).

```bash
refdes schema --graph > graph.svg
```

Plain SVG with no script in it: open the file in a browser, embed it in a
page, commit it beside a README. Its colours are the site's CSS custom
properties with literal fallbacks, so it follows a theme when it is inside
one and still renders standalone. (This output used to be Mermaid source,
which needed a renderer of someone else's choosing — and went stale in the
docs page that embedded it anyway.)

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
refdes standard upgrade --to 3
```

Each bundled standard version ships its own `migration.yaml` — the delta
from the version immediately before it (`hardware@2`'s renames
`constraint.title` to `constraint.text` and the `constraint` type to
`bound`, its `CON` prefix along with it; `hardware@3`'s renames
`requirement.text`/`bound.text`/`test.method` to `body:`). See [the
versions shipped so far](standard-library.md#the-versions-shipped-so-far).
Upgrading across several versions chains each intervening one's own
migration, in order — `v1→v2`, then `v2→v3`, and so on — never merged into
one combined rename, so a name a later version reuses (freed up by an
earlier step) is never mistaken for a collision. Each step rewrites item
files, bumps `standard.version:` in `refdes-project.yaml`, and carries the affected
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
the data — `revise` alone only touches item files, never `refdes-schema.yaml`'s
own `types:`/`link_types:` — so on a hand-rolled schema, pair the rename
with your own edit to `refdes-schema.yaml` (in whichever order makes both sides
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

## `refdes calc-rewrite`

Rewrite every retired `name : unit = expression` calc line to the pipe
form `name = expression | unit`, in place:

```bash
refdes calc-rewrite --dry-run   # show every line that would change
refdes calc-rewrite             # rewrite them
```

Only lines inside ```calc fences in item bodies are touched — prose and
`{{name}}` references are never rewritten. Indentation, trailing comments
and the equals-column alignment are preserved, and a tolerance that sat in
the old annotation moves to the expression: `P : W ± 10% = V * I` becomes
`P = V * I ± 10% | W`.

The operation is transactional like `refdes revise`: the rewritten project
is reloaded and fully validated, and every calc's evaluated result and unit
are compared against the before picture — any calc that would compute
differently rolls every file back. Content hashes and calc hashes are
carried forward across stamped baselines **and** seal files, because a
spelling-only rewrite is not a content change.

Sealed append-only entries are never rewritten: their lines are listed on
stdout and left exactly as written. That is why the retired spelling still
*evaluates* — a sealed entry renders its numbers — even though anywhere
else in a project it is a build error naming the exact fix.

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

An items file that fails to parse is printed to stderr, and on the path where
nothing matched it says so and exits 1: those files were never searched, so
"no candidate former-id mappings found" would be a claim about them too.

---

## `refdes keys adopt`

Explicitly adopt surrogate keys for an existing project. This is a
one-time, transactional operation that:

- Mints a surrogate key for every item that doesn't have one yet (written as
  `key: <11-char>` in the source file)
- Expands structured link targets and `checks: against:` references that
  resolve to a keyed item to the composite `DISPLAY-ID@key` form
- Freezes bare `follows:` references at their thread tips (no bundled
  standard declares `follows:` yet, so a project has none until the threads
  work ships)
- Rebases every baseline (`.refdes/baselines/*.yaml`) and seal file
  (`.refdes/log-seal*.yaml`) to key-keyed storage, carrying forward entries
  whose content is provably unchanged (older hashes migrate automatically;
  entries that genuinely changed since the stamp are reported as
  `uncomparable` and left in the legacy display-id-keyed form)
- Converts the board/workspace membership manifest (`.refdes/boards.yaml`) to
  key-keyed storage, dropping entries for items that no longer exist
- Writes the adoption marker `.refdes/keys-adopted.yaml` (commit this file;
  future stamps, seals, and manifests use key-keyed storage)

| Option | Effect |
|---|---|
| `--dry-run` | Show the complete plan (keys to mint, links to expand, baselines/seals/manifests to rebase, files that would change) without writing anything |

```bash
refdes keys adopt --dry-run
refdes keys adopt
```

**Report lines** (on success, without `--dry-run`):

```
minted 42 key(s)
expanded 128 link reference(s) to composite form
expanded 7 check reference(s) to composite form
froze 3 follows reference(s) at their thread tips
baselines rebased:
  rev-c (41/41 entries carried)
  rev-b (41/41 entries carried)
seals rebased:
  .refdes/log-seal.yaml (12/12 entries carried)
  .refdes/log-seal-power.yaml (8/8 entries carried)
membership manifests rebased:
  .refdes/boards.yaml (35/35 entries carried)
changed files:
  items/power/requirements.yaml
  items/thermal/decisions.md
  .refdes/baselines/rev-c.yaml
  .refdes/baselines/rev-b.yaml
  .refdes/log-seal.yaml
  .refdes/log-seal-power.yaml
  .refdes/boards.yaml
  .refdes/keys-adopted.yaml
Review the diff before committing.
```

`uncomparable` entries (baseline or seal entries that genuinely changed since
the stamp, so their old-format hash no longer matches the current content)
are listed individually:

```
  uncomparable baseline entry rev-a: REQ-OLD-002
  uncomparable seal entry .refdes/log-seal.yaml: LOG-A-005
```

Membership entries get their own lines: an entry that cannot be matched to a
live item's key is left keyed by display id and printed as
`unidentified membership entry boards: REQ-PWR-004`, and entries for items that
no longer exist are dropped with a summary line —
`dropped 2 stale membership entries: boards: REQ-OLD-001, workspaces: REQ-OLD-004`
(`would drop ...` under `--dry-run`).

The operation is **transactional and idempotent**: if any write fails, all
changes are rolled back; running it again on an already-adopted project prints
`nothing to do -- project already adopted` and exits 0. The project must
validate cleanly (no build errors) before adoption runs — `keys adopt` refuses
on a broken project.

---

## `refdes history capture` / `redact` / `migrate-seals`

Direct author-facing access to the captured-history store
(`.refdes/history/`): a manual capture for notes a `follows:` edge will
never supply a successor for, redaction, and the documented legacy-seal
migration. Every subcommand **refuses under `--no-write`** (exit 2)
rather than pretending it wrote something.

### `refdes history capture <item>`

Capture ITEM's (display id or surrogate key) current semantic snapshot
as a manual `captured` event, and announce it:

```bash
refdes history capture LOG-A-011
# captured LOG-A-011: manual capture
```

Says "captured", never "final": the item stays editable, and a later
edit is the same `edited after captured` warning any other capture gives
— a diagnostic, never a failure. Idempotent: one capture event per item;
the second run prints `... is already captured; nothing was written`,
creates no files, and announces nothing. Unlike the automatic `follows:`
capture (deliberately clockless so an old-branch replay is
byte-identical), an explicit capture carries `occurred_at` — it is the
author moment §2 names as allowed to stamp a clock, and it cannot replay
without running this exact command.

### `refdes history redact <item-or-object> --confirm`

Remove matching history objects and events from `.refdes/history/` and
write one auditable `redaction` event naming what was removed — by
digest and event id only, **without repeating any of its content**.
TARGET is an item (display id or surrogate key: every capture event of
it, plus the snapshots no surviving event still references) or a full
64-hex object digest.

```bash
refdes history redact LOG-A-011 --confirm
# redacted 1 object(s) and 1 event(s)
# wrote redaction event 6f2a... naming what was removed (by digest and event id only -- its content is not repeated anywhere in this output)
# Redaction reaches this history store only. It cannot remove data already committed to Git, present in clones, or published in built sites: rewrite Git history and republish (and revoke anything secret) the way you would for any leaked file.
```

Without `--confirm` the command refuses (exit 2) and writes nothing. The
warning above is printed by every successful redaction too: this command
cannot un-publish a leak, only clear the working store. Redaction events
themselves are never redaction targets — removing the audit trail of a
prior redaction would make the second leak indistinguishable from no
leak. An object shared by two identical items is deleted only when the
last event referencing it goes. The removal is transactional: any failure
restores every file it had deleted.

### `refdes history migrate-seals [--capture-current]`

Read the legacy append-only seal files (`.refdes/log-seal*.yaml`) and
write one `legacy-seal` marker event per seal record: **recorded hash
only; original content was not captured.** The seal files themselves are
read, never modified, and stay on disk until a later phase retires them
(the migration must have run before legacy seal support ever goes away).
Idempotent via the derived event ids.

```bash
refdes history migrate-seals
# legacy-seal marker for LOG-A-001 (.refdes/log-seal-board-a.yaml)
#   recorded hash only; original content was not captured; the seal file is left untouched
# 1 legacy-seal marker(s) written, 0 already present
```

A marker carries no snapshot object — its reason names the seal file and
the recorded hash, and nothing about it may imply the original text is
recoverable. `--capture-current` additionally captures the *current*
snapshot of each sealed item whose live content still matches its
recorded hash, as a clearly dated `migrated-current` event — never
labelled seal-time text, which is the specific misrepresentation the
design forbids. An item whose live content has drifted reports `differs`
and is not captured.

---

## `refdes serve`

Serve the project on your own machine: the ordinary rendered site as a preview,
and a browser editor. Loads exactly one project and prints a launch URL.

| Option | Effect |
|---|---|
| `--no-open` | Print the launch URL but do not open a browser |

```bash
refdes serve
refdes serve --no-open
```

- **Loopback only.** It binds `127.0.0.1` on an ephemeral port — there is no
  `--host` and no remote mode. A request whose `Host` is anything but
  `127.0.0.1:<port>` or `localhost:<port>` is refused.
- **A launch token gates everything.** The printed URL carries a random,
  per-launch token. Opening it sets a `SameSite=Strict` session cookie and
  redirects to the token-free `/preview/`; every `/api/` call — reads too —
  must send the token in an `X-Refdes-Token` header, and every write must also
  come from the server's own `Origin`. Keep the URL out of screenshots and
  shared terminals.
- **The preview never touches `_site/`.** It is rendered into a directory under
  your OS temp directory, removed on Ctrl+C and pruned on a later launch if a
  crash left it behind. An "Editor" / "Edit this item" toolbar is added to the
  *HTTP response* only; a `_site/` you publish never contains it.
- **The preview is a workbench (thread workbench, `docs/design/thread-workbench.md`).**
  Served item pages carry author decorations the published site never shows —
  the item's own build diagnostics in a panel, image provenance (resolved
  source path and content hash, or a marker where an image did not resolve),
  and inline calc-value attributions: each `{{name}}` reference the build
  rendered as a bare value gains its name (and owning calc block's name) as a
  hover title and a small label, with a **values** toggle on each calc table
  to hide them. Every decoration is response-only like the toolbar, and every
  value on it is a string the build already computed — nothing is evaluated
  in the browser.
- **Loading writes nothing.** No key is minted, no link expanded, nothing
  sealed, no `.refdes/schema.json` written — the same guarantee as
  `--no-write`, pinned by `tests/test_no_write.py`. Files you edit outside the
  browser are picked up by polling (content hashes, so a touch changes
  nothing) and the preview is rebuilt. The watched inputs are the config
  files, item and page sources, `.refdes/` state, imported artifacts, and
  **every file under a `site.assets:` directory**: adding, replacing, or
  deleting an image moves the revision and rebuilds the preview just like a
  text edit does, whether or not any document references that file yet.

The editor is served from `/edit/` as plain JavaScript and CSS packaged with
refdes; no Node or build step is involved, and none of it is ever part of the
generated site.

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
| `.refdes/citations.yaml` | **yes** | Citation lockfile (sha256, fetch time, kept-copy flag); written only by `refdes fetch` |
| `.refdes/baselines/<name>.yaml` | **yes** | One file per `refdes revision`/`refdes release` stamp. Not rewritten by any ordinary command; `refdes revise` and `refdes standard upgrade` do edit it, to carry an item's content hash across a rename |
| `.refdes/schema.json` | **no, gitignored** | The project's merged JSON Schema, for editor completion; rewritten by every command that loads the project |
| `.refdes/copies/` | **no, gitignored** | Kept local copies of datasheet bytes, content-addressed by sha256; written only by `refdes fetch --path ...` for a remote citation with `keep_copy: true` |
| `.refdes/history/` | **yes** | Captured-history store: content-addressed snapshot objects and derived-id events; written by the `follows:` capture and by `refdes history capture`/`redact`/`migrate-seals` |
| `_site/` | no | Generated output |

Source files are also rewritten by `refdes id`, which inserts allocated IDs in
place. `.refdes/citations.yaml` and `.refdes/copies/` are the only things
`refdes fetch` writes — `build` and `check` (without `--refresh`) never touch
either.
