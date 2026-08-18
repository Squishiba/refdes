# IDs

An ID is the one thing in Refdes that is genuinely permanent. Links, coverage,
content hashes, and every future baseline are keyed on it.

## Allocation

Write items without an `id:`, then run:

```bash
refdes id
```

```
allocated REQ-PWR-005  (items/requirements/power.yaml:36)  The unit shall tolerate...
allocated 1 id(s)
```

The ID is written back into your source file, preserving comments and indentation:

```yaml
  # No id yet — refdes id will allocate one here.
  - id: REQ-PWR-005
    text: The unit shall tolerate a sustained 40 V input transient for 100 ms.
```

Use `--dry-run` to see what would be allocated without writing.

## Numbers are never derived from position

This is the rule everything else depends on. If IDs came from an item's position in
a file, inserting a requirement at the top would shift every ID below it — silently
repointing every link, invalidating every hash, and orphaning all history.

So allocation happens once, at author time, and the result is written into the
file. Inserting an item later gives it the next free number wherever it sits:

```yaml
items:
  - id: REQ-TMP-001
    text: First.
  - id: REQ-TMP-003     # inserted later, keeps its own number
    text: Inserted in the middle.
  - id: REQ-TMP-002
    text: Second.
```

Out of order in the file, stable forever. Display order comes from the file, not
from the number.

## Numbers are never reused

Deleting `REQ-PWR-003` does not free `003`. The ledger at `.refdes/ids.yaml`
records the high-water mark per prefix:

```yaml
burned:
  CON-THM: 2
  DEC-PWR: 1
  REQ-PWR: 5
allocated:
- REQ-PWR-005
```

Someone reading revision B in two years must find that ID meaning what it meant
then. **Commit this file** — if two branches allocate from different ledgers, they
will hand out the same number.

## Prefixes

The prefix comes from, in order:

1. `prefix:` on the item itself (a list entry, or one item in a multi-item
   markdown file — see [authoring](authoring.md#prefix-per-item))
2. `defaults.prefix` in a list file or a markdown file's leading `defaults:`
   block (`REQ-PWR`)
3. the type's `prefix` in `refdes.yaml` (`REQ`)

Prefixes may contain hyphens, which is how you get `REQ-PWR-001` and `CON-THM-001`
from the same `requirement`/`constraint` types.

## Width

`id.width` in `refdes.yaml` sets zero-padding:

```yaml
id:
  width: 3      # REQ-PWR-004
```

Set this generously at the start. Going from `-004` to `-0004` later means either
breaking existing IDs or living with permanent inconsistency. Three digits suits
most boards; use four if you expect more than a thousand of any one prefix.

## Merge collisions

Two branches can both be allocated `REQ-PWR-004`. Merging puts them side by side
and `refdes check` fails:

```
ERROR items/requirements/power.yaml:22 [REQ-PWR-004] — duplicate id 'REQ-PWR-004'
      (also defined at items/requirements/thermal.yaml:9)
```

Renumber whichever is younger. This is safe **only before the ID has appeared in a
baseline**, which gives the rule to remember:

> An ID is provisional until it is baselined. After that it is frozen forever.

Sequential numbering plus detection is a better trade than collision-proof random
suffixes, which nobody wants to read or type.

## Renumbering: `former_ids:`

Migrating into Refdes, or renumbering to adopt a [board
token](multi-board.md), leaves external references -- schematics, review
notes, commit messages -- citing an id that no longer exists. `former_ids:`
records what an item used to be called, so those references still resolve:

```yaml
- id: REQ-CAN-001
  text: The bus shall recover from a bit error within one frame.
  former_ids: [CAN_00]
```

`[[CAN_00]]` and a bare `CAN_00` in prose now resolve to `REQ-CAN-001`,
rendered with a visible "(formerly CAN_00)" marker rather than a silent
redirect -- a reader following the old id needs to see it landed somewhere
else. Bare (bracket-free) autolinking only reaches an id shaped like
`PREFIX-NNN`, the same pattern any live id already needs; a former id from an
external scheme that doesn't fit that shape -- `CAN_00` above, underscore-
joined rather than hyphenated -- still resolves, but only written explicitly
as `[[CAN_00]]`. `refdes check` warns when a declared `former_ids:` entry
can't bare-autolink, so the gap is visible instead of a silent no-op.

A `former_ids:` entry naming a still-live id -- another item's, or its own --
is a build error: `former_ids` may only retire ids, never claim one still in
use. So is a former id declared by two different items, since a reference to
it has to resolve to exactly one. Every retired number is also burned into
the ledger's high-water mark, the same as an allocated one, so the allocator
can never reissue it. `refdes audit` lists the full former-id mapping.

Writing `former_ids:` by hand for every item a renumbering touches is easy to
skip, which is exactly how the mapping gets lost in the first place.
`refdes former-ids propose` infers candidates by comparing the most recent
[baseline](lifecycle.md) to the live project -- see [CLI
reference](cli-reference.md#refdes-former-ids-propose) -- and writes nothing
until you confirm which ones to accept.

## Planning ahead for multiple boards

If there is any chance of a second board, put a board token in the prefix now:

```yaml
defaults:
  prefix: REQ-A-PWR      # not REQ-PWR
```

It costs nothing today and it is the difference between splitting boards into
separate projects later and being unable to. See
[multiple boards](multi-board.md).
