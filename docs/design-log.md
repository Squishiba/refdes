# The design log

A dated, append-only record of how the design actually got where it is: the
measurements, the dead ends, and the reasoning between a requirement being handed
to you and a decision being made.

A **decision** is the settled conclusion. A **log entry** is a step on the way to
one. You read decisions to find out why the board is the way it is; you read the
log in order to understand how it got there.

## Writing entries

Log entries suit a list file — you add to it most days.

```yaml
defaults:
  type: log
  prefix: LOG-A
  board: board-a
  author: J. Bin

items:
  - id: LOG-A-002
    date: 2026-02-24
    summary: Ruled out an LDO on thermal grounds before doing any layout work.
    addresses: [REQ-PWR-002]
    body: |
      Back of the envelope: (12 V − 3.3 V) × 1.2 A is 10.4 W in the pass element.
      The enclosure budget is under a watt for the whole power stage. Not a
      marginal call, so I did not model it further.
```

| Field | Purpose |
|---|---|
| `date` | required; orders the timeline |
| `summary` | required; the one-line version shown on the timeline |
| `author` | who wrote it |
| `board` | which board, when a project holds several — see below |
| `body` | the detail — markdown, may contain calc blocks |

| Link | Points at |
|---|---|
| `addresses` | a requirement or constraint this entry works on |
| `records` | the decision this entry led to |
| `amends` | an earlier log entry this corrects |

### `board` is a plain field here, not the reserved override

The starter schema's `log` type declares its own `board` field, which predates
the `boards:` registry described in [multiple boards](multi-board.md). The
reserved `board:` override key that scopes an item to a registered board only
applies to a type that does **not** already declare a field of that name — see
[reserved keys](authoring.md#reserved-keys) — so on a `log` entry, `board:`
stays exactly what it always was: free text, with no effect on board-scoped
pages, token linting, or drift tracking.

Once a project registers `boards:`, it is worth moving `log`'s hand-typed
`board` field out of the schema so `board:` picks up the reserved behavior
instead — the two cannot both be true for the same type at once, since the
field always wins.

## Append-only

Entries are **sealed on first build**. The hash of each is recorded in
`.refdes/log-seal.yaml` — or, once a project registers `boards:` *and* an entry
actually resolves onto one (the reserved `board:` override, not a same-named
plain field like the one this schema's own `log` type declares above),
`.refdes/log-seal-<board>.yaml` instead. Editing a sealed entry afterwards
fails the build:

```
ERROR items/log/board-a.yaml:33 [LOG-A-003] — LOG-A-003 is append-only and has
      been modified since it was sealed. Append a new entry with
      `amends: [LOG-A-003]` instead, or run with --reseal if the edit is
      deliberate.
```

Commit `.refdes/log-seal.yaml` (and any `.refdes/log-seal-<board>.yaml`) along
with your entries.

`refdes check` verifies existing seals without creating new ones, so it is safe
in CI. `refdes build` seals anything new it finds.

### Adopting boards on a project that already has `.refdes/log-seal.yaml`

Nothing to migrate by hand. An entry sealed before `boards:` existed stays
verified against that same hash even after it comes to resolve onto a board —
`refdes check` looks it up in the base file if the board's own file doesn't
have it yet, so a project that adopts boards without immediately rebuilding
still catches a real edit. The physical move only happens on a `refdes build`:
the entry is written into `.refdes/log-seal-<board>.yaml` and dropped from
`.refdes/log-seal.yaml` in the same run. `refdes check` never writes, so it
never performs this move itself.

### Corrections

Append a new entry rather than editing the old one:

```yaml
  - id: LOG-A-006
    date: 2026-03-19
    summary: Correction to LOG-A-003 — the 93 % figure was at 12 V in, not worst case.
    amends: [LOG-A-003]
    addresses: [REQ-PWR-003]
    body: |
      Re-read my own bench notes. The 93 % measurement was at 12 V input; at 36 V
      it drops to 91 %. DEC-PWR-001 uses 0.93, which is optimistic for worst case.
      Leaving LOG-A-003 as written and recording the correction here.
```

The original stays exactly as written. That is the point: the correction is more
informative *because* you can see what was originally believed. The timeline marks
amending entries, and `LOG-A-003` shows `amended_by: [LOG-A-006]`.

### The escape hatch

`refdes build --reseal` accepts an edit to a sealed entry, on any board. Name a
board to scope it to just that board's own entries — `refdes build --reseal
power` — leaving every other board's edits to fail as a normal violation. It is
reported as a warning at the time and listed permanently by `refdes audit`:

```
Append-only entries edited after sealing:
  LOG-A-003
```

Overriding is allowed. Overriding invisibly is not — the same principle that
governs [change tracking](change-tracking.md).

### What sealing can and cannot do

It **detects** an edit; it cannot **prevent** one. Anybody can open the YAML file.
No file-based tool can do better, and detection is what actually matters — the
build fails, CI goes red, and the diff is in git.

## Why append-only

Three reasons, in increasing order of importance:

1. A record you can quietly rewrite is not evidence of anything.
2. The dead ends are the valuable part. Six months later, "we tried the LDO and it
   dissipated 10.4 W" is what stops someone re-proposing it.
3. What you believed at the time is itself information. `LOG-A-006` correcting an
   efficiency figure tells you the thermal calculation was built on an optimistic
   number — you cannot learn that from a tidied-up document.

## The timeline

`log.html` renders all entries oldest-first with dates, authors, board tags,
amendment markers, and the requirements each entry addresses. Every entry also gets
its own page with full traceability.

## Coverage

An entry that `addresses` a requirement moves it from **open** to **addressed** —
somebody has worked on it, even though no decision has been reached and no test
exists. See [coverage](coverage.md).
