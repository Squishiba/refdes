# The design log

A history-backed, append-only record of how the design actually got where it is: the
measurements, the dead ends, and the reasoning between a requirement being handed
to you and a decision being made.

A log entry can be a narrative note or a verdict. A verdict declares `status:`,
while a note can leave it blank. A thread links successive entries with
`follows:`; its current conclusion comes from its tip.

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
| `date` | optional; records when an entry was written if known |
| `summary` | required; the one-line version shown on the timeline |
| `author` | who wrote it |
| `status` | optional verdict; leave it blank for a narrative entry |
| `citations` | document `path:` or another item's `item:` id; a dangling item id is a build error |
| `board` | which board, when a project holds several — see below |
| `body` | the detail — markdown, may contain calc blocks |

| Link | Points at |
|---|---|
| `addresses` | a requirement or bound this entry works on |
| `follows` | the earlier log entry this one continues |
| `amends` | an earlier log entry this corrects |
| `satisfies` | a requirement or bound addressed by an accepted verdict |

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

**If you can't retire the field**, because the entries are already sealed and
dropping it would change every content hash, put the file under the
registered board's own folder instead: `items/<board>/log.yaml`. The path is
what the registry matches, and it needs no reserved key to work. Leaving the
file somewhere that isn't a registered board means every entry resolves to no
board at all — one warning per entry, on every build. This repository's own
sample project does exactly this; see
[`items/board-a/log.yaml`](../items/board-a/log.yaml).

## Append-only

What enforces "append-only" is the type's `sealing:` setting. The bundled
`hardware@3` standard's `log` — this project's own included — is
**`sealing: history`**: nothing is sealed, and an edit is never a build error;
see [history-backed types](#history-backed-types-sealing-history) below.
The sealing, seal files and `--reseal` described from here to that section
are **`sealing: build`** (only [corrections](#corrections) apply to both): the
build-time hash lock, which is still the default for every other append-only
type, what `log` itself uses under `hardware@1` and `hardware@2`, and what a
`hardware@3` project gets back for its `log` by opting out (below).

With `sealing: build`, entries are **sealed on first build**. The hash of each
is recorded in `.refdes/log-seal.yaml` — or, once a project registers `boards:` *and* an entry
actually resolves onto one (the reserved `board:` override, not a same-named
plain field like the one this schema's own `log` type declares above),
`.refdes/log-seal-<board>.yaml` instead. Editing a sealed entry afterwards
fails the build:

```
ERROR items/log/board-a.yaml:33 [LOG-A-003] — LOG-A-003 is append-only and has
      been modified since it was sealed. Append a new entry with
      `amends: [LOG-A-003]` instead, or run with `refdes build --reseal` if the
      edit is deliberate.
```

**Deleting a sealed entry fails the same way.** A page torn out of the
notebook is worse than one written over, so the two are reported alike:

```
ERROR  LOG-A-003 is append-only and was sealed, but no item with that id is
       in the project any more. An append-only entry is corrected by appending
       one that `amends` it, never by deleting it -- restore it, or run with
       `refdes build --reseal` if the removal is deliberate.
```

An id that is still in the project under a different board, or that another
item now claims through [`former_ids:`](ids.md#renumbering-former-ids) after a
renumbering, has not been deleted and is not reported. `--reseal` accepts the
removal and drops the orphaned seal.

Commit `.refdes/log-seal.yaml` (and any `.refdes/log-seal-<board>.yaml`) along
with your entries.

`refdes check` verifies existing seals without creating new ones, so it is safe
in CI. `refdes build` seals anything new it finds — which means an entry that
has never been through a build is not passing an append-only check: it has no
seal to pass or fail, and editing it fails nothing.

Which is why a build that *could not* seal says so. On a read-only checkout the
site still renders and every check still runs, but the entries stay unsealed and
the run says which file it could not write rather than reporting a clean build:

```
ERROR   .refdes/log-seal.yaml — could not write this file (read-only tree?) -- the entries in it are NOT sealed, so they have no append-only protection until a build can write this file; run with --no-write to silence this
```

That is an error, and `refdes build` exits `1` for it, because "these entries
have append-only protection" and "these entries have none" have to read
differently. See [keys §2](design/keys.md#a-tree-that-will-not-take-the-write)
for the whole read-only story.

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
reported as a warning at the time. The seal file retains a `reseals` event for
each accepted edit: the item label and key (when available), UTC timestamp,
and old/new hashes. `refdes audit` reads those durable events separately from
outstanding edits that have not been accepted (`src/refdes/seal.py::verify`,
`src/refdes/cli.py::cmd_audit`; verified with `refdes build --reseal` and
`refdes audit`):

```
Append-only entries edited after sealing:
  (none)

Accepted append-only reseals (durable history):
  LOG-001 2026-09-28T05:54:27.345055+00:00 edit
    item key kqkm6e6dv9c
    was 4d34265af98c51b2, now 71059aef2108bb46
  (the key is the item's own surrogate key: it does not change when
   the item is renamed, where the id above is the label as it stood)
```

The board is shown bracketed after the id when the entry has one
(`LOG-A-001 [power] …`) and left out entirely when it has none — the same way
every other section of the `audit` report treats an absent board. The id on a
row is the label as it stood when the event happened, so a
[renumbering](ids.md#renumbering-former-ids) splits one entry's history across
two ids; the key is what ties them back together, and it is also the half of
`refdes keys restore ID@KEY` that proves which item you mean.

Repeated reseals append events, including edits that restore older content.
Deliberate removals accepted by `--reseal` also retain the removed hash and
are shown as `remove`, with `now (removed)`. A preview (`--dry-run` or
`--no-write`) records neither a seal nor an acceptance event. Keep the seal
files committed alongside the item sources; their hashes record acceptance,
not the old text itself. Past reseals made before this mechanism was added
cannot be reconstructed from the current seal file.

Overriding is allowed. Overriding invisibly is not — the same principle that
governs [change tracking](change-tracking.md).

### History-backed types (`sealing: history`)

This section applies to the bundled `hardware@3` `log`, which declares
`sealing: history`, and to any type a project declares that way itself. Every other append-only type
keeps the engine default, `sealing: build` — everything above — as does `log`
under `hardware@1` and `hardware@2`. A `hardware@3` project that wants the
build-time lock back for its log says so with an overlay in
`refdes-schema.yaml`:

```yaml
types:
  log:
    sealing: build
```

The entries stay append-only in the authoring sense — a correction is still a
new entry that `amends` the old one — but nothing is sealed any more:

- A build seals none of the type's entries, and an edit to one is **not** a
  build error. If the entry was captured into `.refdes/history/` (a
  `follows:` successor froze an edge to it, or `refdes history capture`), the
  edit is the warning `LOG-001: edited after captured -- ...` under both
  `check` and `build`; exit codes are unchanged. An entry that was never
  captured has no snapshot to compare against, so there is nothing to compare
  it to — but a project that upgraded from the build-time lock still holds
  each entry's prior hash in its legacy seal record, and an edit that moves it
  is the warning `LOG-001: edited while uncaptured -- ...` under both `check`
  and `build`, naming the record it no longer matches and the
  `refdes history capture` command that ends the blind spot. That one is a
  warning too: the exit code and the build are unchanged. An entry no record
  names at all stays silent — nothing recorded what it used to say, so there
  is no edit to report. `refdes audit` lists either kind of changed entry
  (below).
- A bare `follows:` on an entry a seal file already mentions freezes and is
  captured like any other, instead of being left bare with "already sealed".
- Seal files that already exist are kept and read as **legacy-seal markers** —
  recorded hash only; original content was not captured. `build`, `check`,
  `--reseal` and `revise` never change or delete their records, and never
  delete a seal file. Two exceptions rewrite the *file* around them:
  - When one seal file also holds records for a type that still uses
    `sealing: build` (two append-only types sharing a board, or both on no
    board), a build that legitimately writes for that type — sealing a new
    entry, upgrading a hash format, accepting a `--reseal` — re-serializes the
    whole file. The legacy-seal records come through with their data
    unchanged, but the file's bytes can change: an older header is normalized
    to the current one, for instance. A project where every append-only type
    is history-backed never hits this.
  - `refdes keys adopt`, an explicit one-time migration, re-keys them like any
    seal file.

  Deleting an entry one of them mentions is a warning
  naming the record and the seal file, not an error:
  `LOG-A-001 has a legacy seal record in .refdes/log-seal-board-a.yaml (key
  5wh2j90t4hg) but is no longer in the project. ...`. Restore the entry from
  version control if the removal was not deliberate — the record cannot bring
  it back. A key that changed under such a record is still an error, as it is
  for a sealed entry: a key never changes legitimately.
- `refdes build --reseal` is accepted and says it has nothing to do:
  `--reseal: sealing no longer applies to the 'log' type; nothing was
  rewritten. ...`. It captures nothing.
- `refdes audit` still lists such an entry under "Append-only entries edited
  after sealing" when it no longer matches its legacy record (marked
  `(legacy seal: recorded hash only; original content was not captured)`), and
  lists captured entries that changed under "Entries edited after captured".
- **A retired calc unit spelling becomes a build error.** Inside a sealed
  entry, a `calc` line using a retired unit spelling is only a warning, because
  fixing it would mean resealing (and `refdes calc-rewrite` refuses to touch a
  sealed entry). A history-backed entry is not sealed, so neither exception
  applies: the moment a type switches to `sealing: history` — for the bundled
  `log`, the moment a project pinned to `hardware@3` picks up the refdes
  version that made it the default — any such line in an existing entry is a
  `retired_unit_spelling` build **error**.
  `refdes calc-rewrite` now rewrites those entries too, which clears it (the
  legacy seal file is not touched; a captured entry then reads as edited after
  captured). Run it, or fix the line by hand, when a type switches.

`refdes history migrate-seals` writes one `legacy-seal` event per seal record
into the history store; it is independent of the switch and leaves the seal
files untouched either way. This repository has run it: its six entries'
records in `.refdes/log-seal-board-a.yaml` have markers in
`.refdes/history/events/`, and the seal file itself is unchanged.

A `sealing: history` type must be `append_only: true`, and a subtype cannot
declare it under a parent that keeps the build-time lock. (Verified against
`src/refdes/seal.py` and `tests/test_history_seal.py`; the retired-spelling
behaviour against `src/refdes/build.py`'s `_run_item_calcs` and
`src/refdes/calc_rewrite.py`, both of which read `seal.is_sealed`.)

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

Entries that continue one another — a chain of entries linked by `follows:` —
will additionally show a **Thread** section on their page: what the thread
currently concludes, with each value attributed to the entry that concluded it,
and the whole thread as a timeline. A thread that has forked would show no
conclusion at all, only the open tips.

The bundled standard declares `follows:`. The thread conclusion and timeline
page described above are later threads work; see [threads](design/threads.md).

## Coverage

An entry that `addresses` a requirement moves it from **open** to **addressed** —
somebody has worked on it, even though no decision has been reached and no test
exists. See [coverage](coverage.md).

## After a release

`refdes release <name>` does not write a log entry for you, and never
prompts for one. A machine-generated "released rev-b" entry with no
rationale is exactly the low-value noise this file's own append-only
discipline exists to keep out of the timeline — an empty auto-entry is
worse than no entry. `revision`/`release` also can't reliably guess a log
entry's prefix or board on the project's behalf the way they can guess a
gate result, so writing one would mean guessing at both.

What it prints instead is a nudge, on a successful `release` only (a
`revision` is allowed to be a mid-thought checkpoint with nothing to
announce yet):

```
Consider recording this in the design log, e.g.:
  - id: LOG-A-0NN  # placeholder: your log prefix, next free number
    date: 2026-08-17
    summary: Released rev-b — sent to fab.
    citations:
      - item: DEC-A-0NN  # an earlier log entry this release turned on
```

Both ids are placeholders and say so: `LOG-A-0NN` is not shaped like a display
id (`ids.split_id` wants a trailing `-<digits>`), so a copy-paste that skips
substituting them fails the id check rather than minting something you then
have to `refdes revise` away.

Write the entry the same way you'd write any other — cite the earlier log
entry or entries the release actually turned on, and say in `summary:` what
shipped and why, the same as any other point on the timeline. See
[lifecycle](lifecycle.md) for `revision`/`release` themselves.
