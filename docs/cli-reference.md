# CLI reference

```
refdes [-c CONFIG] {build,check,id,audit} [options]
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
| `--reseal` | Accept edits to sealed append-only entries |
| `--accept-board-move` | Accept a recorded [board](multi-board.md) change for an item |

```bash
refdes build
refdes build -o public --keep-going
```

Build also **seals** any new [log entries](design-log.md) it finds, writing
`.refdes/log-seal.yaml`.

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
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens =
        0.2366 W/in² violates CON-THM-001 (<= 0.15 W/in^2)
WARNING items/requirements/power.yaml:26 [REQ-PWR-004] — nothing addresses,
        satisfies, or verifies this yet
16 items, 1 errors, 4 warnings
```

Errors go to stderr, warnings to stdout. Every diagnostic leads with
`file:line`, so editors and CI annotations can link straight to the source.

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

## `refdes audit`

Report everything that has been made less visible: fields excluded from
invalidation, item-level overrides and their stated reasons, resealed log entries,
[board](multi-board.md) moves, and imported projects.

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

Imported projects (read-only):
  platform       1 items pinned to 2026.3  <- ../platform/_site/items.json

16 items audited (16 local)
```

The "Board moves" section only appears for a project that has declared a
`boards:` registry.

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
| `.refdes/log-seal.yaml` | **yes** | Append-only seals for log entries |
| `.refdes/boards.yaml` | **yes** | Board drift manifest; only written by a project with `boards:` |
| `_site/` | no | Generated output |

Source files are also rewritten by `refdes id`, which inserts allocated IDs in
place.
