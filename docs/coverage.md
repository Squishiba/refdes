# Coverage

Coverage answers "what still needs doing" with several separate questions rather
than one done/not-done flag.

## The five stages

| Stage | Means | Produced by |
|---|---|---|
| `open` | Nothing references it at all | — |
| `addressed` | Somebody has worked on it | a **log** entry `addresses` it |
| `claimed` | An entry or component says it meets it, but that claim hasn't settled | a **log**/**component** `satisfies` it, with a `status` not (yet) in the type's `satisfying_statuses:` |
| `satisfied` | A settled log entry or component claims to meet it | a **log**/**component** `satisfies` it, with a `status` in `satisfying_statuses:` |
| `verified` | A test proves it | a **test** `verifies` it |

The stage shown is the highest reached. They are cumulative in intent but not
required to be in practice — a requirement can be verified without any log entry
ever mentioning it.

`claimed` only appears for types that declare `satisfying_statuses:` — see
[below](#which-statuses-count-as-satisfying). A type that doesn't declare it never
produces a `claimed` requirement: every linked log entry or component counts as
satisfying immediately, exactly like before this existed.

## Why several and not one

Because these fail differently:

- **Claimed but not settled** is the one that bit a real migration: a `status:
  on_hold` (or `proposed`) entry was being read as fully satisfying, silently.
  An entry that hasn't settled is a claim, not a fact yet.
- **Satisfied but not verified** is the next most dangerous. A settled entry
  says the design meets the requirement; nothing has proven it. This is normal
  mid-project and catastrophic at ship time, and a single "done" flag hides it
  completely.
- **Addressed but not satisfied** is work in progress. Somebody has been at it for
  three weeks and no verdict has landed. Worth seeing.
- **Open** is untouched. Sometimes fine, sometimes a requirement everyone forgot.

## What gets coverage

Governed by two engine-level flags on the type, not a hardcoded list of type
names — see [schema reference](schema-reference.md#types) for the full
picture:

- **`coverable: true`** puts items of this type in coverage at all. A type
  that declares no `coverable:` falls back to the old convention
  (`requirement`/`constraint` are coverable by name -- the two names that
  convention has ever recognized, kept as-is for compatibility rather than
  following the `hardware@2` rename) with a one-time warning. The
  [standard library](standard-library.md) declares it explicitly on both.
- **`coverable_statuses:`** narrows which of those items actually participate,
  by `status`. Unset, it excludes only `status: retired` (if the type has a
  `status` field at all) — the original behavior. Set, it's an *inclusion*
  list: `coverable_statuses: [active]` means a `draft` item isn't tracked
  either, not just "open" — it doesn't appear in coverage or its warnings at
  all. The standard sets this on `requirement`/`bound`.

A type that [`extends:`](schema-reference.md#extends) another inherits both
flags (and `satisfying_statuses:`/`verifying_statuses:`), so a subtype is
covered by the parent's rules with nothing redeclared, and satisfies or is
verified through any link that names the parent. The coverage page, summary
and `{{index}}` show subtype items under the parent unless
[`coverage.group_inherited`](schema-reference.md#coverage) is `false`.

Imported items are excluded regardless — an upstream project's coverage gaps
are that project's problem.

## Which links feed coverage

**The rule, stated so that it has no exceptions:** *the suffix never tells
you whether a link feeds coverage; the type's `satisfying_statuses` and
`verifying_statuses` do.* Check the type's status declarations and the verb's
pair — never the name's ending.

Coverage is computed from exactly three verb pairs — `addresses`/`addressed_by`,
`satisfies`/`satisfied_by`, `verifies`/`verified_by` — and since
[links are declarable from either end](links.md#back-links-are-computed), each
pair counts whichever end authored it (`build._coverage_for`). No other verb is
ever read by the computation, whatever it is called: `constrained_by`,
`governed_by`, `blocked_by`, `refines`, `derives_from` and their backlinks
contribute nothing (`build.compute_coverage`).

What the status lists then decide:

- `satisfies` — the link counts as `claimed` while the authoring item's
  `status` is outside its type's `satisfying_statuses:` (`log`: `accepted`,
  `component`: `selected`), and as `satisfied` once inside; a type that
  declares no `satisfying_statuses:` counts every link as satisfying.
- `verifies` — the link counts once the verifier's `status` is in the
  verifier type's `verifying_statuses:` (`test`: `passing`); unconfigured,
  every link counts.
- `addresses` — the `addressed` stage records that somebody has worked on the
  item and written it up, without claiming it is met, so it is the one
  coverage stage with no status gate.

The rule earns its automaticity precisely because both halves of the suffix
intuition fail it — and the rule holds in each failure:

- A `_by` suffix does not keep a link out. `satisfied_by`, `verified_by` and
  `addressed_by` — the very names the computation reads as backlinks — all end
  in `_by`. And an authored `verified_by: [TST-…]` on a requirement — the
  legacy spelling of a [link declarable from either
  end](links.md#back-links-are-computed), written on the requirement instead
  of the test declaring `verifies:` — feeds coverage just the same: the
  verifier type's `verifying_statuses:` decides whether each such link
  counts, exactly as it would for `verifies:`
  (`build._verifier_type_names`, `build._coverage_for`).
- A `_by` suffix does not put one in either. **`constrained_by` does not feed
  coverage**, however strongly the name suggests otherwise. A log entry that
  only `constrained_by`'s a bound leaves it exactly as open as if no link
  existed at all. `satisfies` is what closes it (see the
  [`governed_by` vs. `constrained_by`](links.md#governed_by-vs-refines-vs-constrained_by)
  distinction).

So: to know what a link does to coverage, find out which of the three pairs it
is, and read the types' status declarations — `satisfying_statuses:` and
`verifying_statuses:` above, and the item's own `coverable_statuses:` for
whether it is tracked at all, [above](#what-gets-coverage). The active-voice
spelling (`satisfies`, `verifies`, `addresses`, authored from the item doing
the claiming) remains the standard's convention for *authoring* a coverage
claim — a convention for where to write it down, not a test for whether it
counts.

## The coverage page

`coverage.html` is one table, least-covered first, with a column per stage —
so the row tells you not just how far an item got but exactly which items
carried it there:

| ID | Title | Stage | Addressed by | Claimed by | Satisfied by | Verified by |
|---|---|---|---|---|---|---|
| BND-THM-002 | Minimum converter efficiency | open | — | — | — | — |
| BND-THM-001 | Board power density | addressed | LOG-A-005 | — | — | — |
| REQ-PWR-003 | Converter efficiency shall exceed 90 % at half load. | satisfied | LOG-A-003, LOG-A-004, LOG-A-006 | — | LOG-PWR-001 | — |
| REQ-PWR-001 | The unit shall operate from an input supply of 9 V to 36 V. | verified | LOG-A-001 | — | — | TST-PWR-001 |

**Claimed by** is its own column, separate from **Satisfied by**. An
unsettled log entry claiming a requirement is not the same as a settled one
meeting it (see [the five stages](#the-five-stages)). Collapsing the two is
exactly what this page exists to avoid.

Counts by stage appear at the top, and the site index carries an **Outstanding
work** panel with the same rows. Each item's own page shows a coverage strip.

### Coverage per board

One platform-wide requirement — "every board uses the standard debug header" —
is one item, so the table above goes `satisfied` the moment *any* board
complies.

A board that declares `conforms_to: [GRP-…]` gets the same four stages
computed again for each member of that group, counting only that board's own
satisfiers.

`coverage-<board>.html` grows a **Conforming contracts** table, and a row on
`coverage.html` gains `not yet satisfied on boards: board-b`. A satisfier
with no board counts toward no board's per-board result, while still
satisfying the item for the project as a whole. See
[multiple boards](multi-board.md#conforming-to-a-shared-contract).

## Warnings

Two of the five stages are individually uninteresting at scale. A project
early in its life is mostly `open`, and "satisfied but not verified" is
routine noise before a test plan exists. The build collapses each into one
summary line instead of one warning per item:

```
WARNING <project> — 3 item(s) with no coverage — see coverage.html
WARNING <project> — 2 requirement(s) satisfied but not verified — see coverage.html
```

`coverage.html` carries the per-item detail; the summary line just tells you
there is some. "Satisfied but not verified" is suppressed entirely when the
project has no `test` items at all — the moment the first one is added, these
become real findings again and start appearing.

`claimed` — an unsettled log entry or component (`status` not yet in
`satisfying_statuses:`) — stays a **per-item** warning, because it is the one
class here that actually names something to act on:

```
WARNING items/requirements/power.yaml:20 [REQ-PWR-006] — claimed but not
        verified (no test links to it)
```

These are warnings, not errors — a mid-project board legitimately has all
three. Use `refdes check` in CI and decide for yourself whether to gate on
warnings.

Diagnostics also have an `info` level, for the routine state of an
incomplete project — hidden by default, shown with `-v`/`--verbose` on
`check` or `build`. The [`blocked_by:` stale check](links.md#blocked_by-and-the-cascade-report)
is the one thing in this area that's `info`. Nothing else coverage produces
is, but `-v` is worth knowing about even if you came here for coverage.

## When the claimer is blocked

If a `claimed` item's claiming log entry itself declares `blocked_by:`, the
per-item warning names the blocker chain, resolved all the way to its root:

```
WARNING items/main-io/requirements.md:40 [REQ-IO-CONN-002] — claimed but not verified
  (no test links to it); claimed by LOG-IO-016, which is blocked_by LOG-IO-003 <-
  LOG-IO-001 (on_hold)
```

When several `claimed` items trace to the same single root blocker, a
second summary line groups them — this is the sentence coverage exists to
produce: not just "unsettled," but *why*:

```
WARNING <project> — 2 requirement(s) unsettled because LOG-IO-001 is on_hold — see coverage.html
```

Deliberately conservative: an item is only folded into this line when its
claim traces to **exactly one** root. An item whose claimer has no
`blocked_by` chain at all, or whose several claimers trace to *different*
roots, keeps its ordinary per-item warning instead — a misleading one-line
summary would be worse than not summarizing it.

`coverage.html` shows the same chain inline next to every claimed item's
row. See [`blocked_by:`](links.md#blocked_by-and-the-cascade-report) for the
edge itself and the rest of its surfaces (`refdes audit`, the item page).

## Which statuses count as satisfying

By default, any log entry or component linked with `satisfies:` counts as
satisfying — the item's own `status` field is not consulted. That is the
behavior every project already has, and it stays exactly that way on upgrade.

To have coverage respect settlement, declare `satisfying_statuses:` on the type:

```yaml
types:
  component:
    fields:
      status: { type: enum, choices: [candidate, selected, obsolete] }
    links:
      satisfies: [requirement]
    satisfying_statuses: [selected]   # only a `selected` component satisfies
```

An item whose `status` is not in that list still records the link — it shows
up as `claimed_by` on the requirement's coverage, and the requirement's stage
caps at `claimed` instead of `satisfied`. Declaring `satisfying_statuses:`
requires the type to have a `status` field; the project fails to load otherwise.

For a thread entry that declares `satisfies:` but not `status:`, coverage
uses the thread's current status. A `status:` inherited from the file's
`defaults:` block is likewise not a declaration. An unmerged fork has no
current status, so its claim remains `claimed`, never `satisfied`. The same
rule applies to a verifier type's `verifying_statuses:`.

| `satisfying_statuses:` | Behavior |
|---|---|
| not declared *(default)* | Every `satisfies:` link counts as satisfying, regardless of status — unchanged from before this existed |
| a list of status values | Only a link whose `status` is in the list counts as satisfying; the rest count as `claimed` |

## Which statuses count as verifying

The same idea, for `verified` instead of `satisfied`. By default, any test (or
other type declaring a `verifies`-family link) linked with `verifies:` counts
as verifying, regardless of its own `status`:

```yaml
types:
  test:
    fields:
      status: { type: enum, choices: [planned, passing, failing, blocked], default: planned }
    links:
      verifies: [requirement, bound]
    verifying_statuses: [passing]   # only a passing test actually verifies
```

Without `verifying_statuses:`, a `planned` or `failing` test still counts as
having verified the requirement it links to — which is what let a merely-linked
test hide behind a green coverage page.

With it, only a `passing` test does. The rest leave the requirement at
whatever stage it would otherwise reach (typically `satisfied`, if something
has claimed it, or `addressed`/`open` otherwise). The
[standard library](standard-library.md) sets this on `test`.

| `verifying_statuses:` | Behavior |
|---|---|
| not declared *(default)* | Every `verifies:` link counts as verifying, regardless of status — unchanged from before this existed |
| a list of status values | Only a link whose `status` is in the list counts as verifying |

## Closing the gaps

| To move from | to | do this |
|---|---|---|
| `open` | `addressed` | write a log entry with `addresses: [REQ-X]` |
| `addressed` | `claimed`/`satisfied` | write a log entry or component with `satisfies: [REQ-X]` |
| `claimed` | `satisfied` | move its `status` into the type's `satisfying_statuses:` list |
| `satisfied` | `verified` | write a test with `verifies: [REQ-X]` |

Any of these edges may be declared from either end — see [links](links.md).

## `stub-tests`

`refdes stub-tests` writes a starter test for every coverable item with no
verifying test yet, `verifies:` already pointing at it — the last row of
the table above, without hand-typing each one:

```bash
refdes stub-tests
refdes id   # allocate ids for the new items
```

Writes one multi-item markdown file per board (or workspace), not one file
per item — a whole board's worth of gaps closes as a single, reviewable
diff. Deduplicates by the declared `verifies:` edge itself, not by text: an
item that already has a test (`planned` or otherwise, allocated an id or not)
is skipped.

Running it again after adding new requirements is safe, and only ever adds
what's newly missing. A prior run's file is appended to, never overwritten.

**The prerequisite is `verifying_statuses:`, already covered
[above](#which-statuses-count-as-verifying).** A generated stub's `status:`
is the type's own declared default (`planned` in the bundled standard),
deliberately not one of `verifying_statuses:`. So a fresh stub never
retroactively marks its target `verified`, and coverage stays exactly as
honest immediately after a `stub-tests` run as it was the moment before.

**A generated stub takes the type's default prefix**, not one built from the
board it lands on. In a project whose boards declare `token:` (see [multiple
boards](multi-board.md#naming-the-boards)), the standard's `TST` will not
contain that token, so each stub trips the token lint until you edit its
`prefix:`:

```
WARNING items/product-a/board-a/stub-tests.md:2 [TST-002] — item is on board
        'board-a' (token 'A'), but its id prefix 'TST' does not contain that token
```

Set `prefix:` on the generated items (or in a `defaults:` block at the top of
the file) *before* running `refdes id` — an id is frozen once allocated, so
this is much cheaper to fix beforehand than after.

**Refdes does not own test items once they're written.** One test often
verifies several requirements at once (a single thermal soak covering five
thermal requirements), and one requirement often needs several tests at
different corners.

The generated one-test-per-requirement file is a starting point for exactly
that reason — restructure it, merge stubs together, split one apart, however
the real test plan actually needs to work. See
[CLI reference](cli-reference.md#refdes-stub-tests).

## In `items.json`

```json
"coverage": {
  "REQ-PWR-003": {
    "stage": "satisfied",
    "addressed_by": ["LOG-A-003", "LOG-A-004", "LOG-A-006"],
    "claimed_by": [],
    "satisfied_by": ["LOG-PWR-001"],
    "verified_by": []
  }
}
```

This is the export to build a burndown chart, a status report, or a gate in CI
from. Read `items.json`, never scrape the HTML.
