# CLI reference

```
refdes [-c CONFIG] {build,check,index,id,fetch,audit} [options]
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
[board](multi-board.md) and [workspace](workspaces.md) moves, imported projects, and
[citations](markdown.md#citing-a-datasheet).

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

Board moves since the manifest was last written:
  (none)

Workspace moves since the manifest was last written:
  (none)

Imported projects (read-only):
  platform       1 items pinned to 2026.3  <- ../platform/_site/items.json

Citations:
  https://www.ti.com/lit/ds/symlink/tps62913.pdf
    unpinned       hash-only  cited by CMP-PWR-001

16 items audited (16 local)
```

The "Board moves" section only appears for a project that has declared a
`boards:` registry, and "Workspace moves" only for one that has declared
`workspaces:`. The "Citations" section only appears for a project that
declares a `citations`-typed field somewhere and has at least one item using it.

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
| `.refdes/vendor/` | **no, gitignored** | Vendored datasheet bytes, content-addressed by sha256; written only by `refdes fetch --url ... ` for a citation with `vendor: true` |
| `_site/` | no | Generated output |

Source files are also rewritten by `refdes id`, which inserts allocated IDs in
place. `.refdes/citations.yaml` and `.refdes/vendor/` are the only things
`refdes fetch` writes — `build` and `check` (without `--refresh`) never touch
either.
