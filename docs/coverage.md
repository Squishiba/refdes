# Coverage

Coverage answers "what still needs doing" with several separate questions rather
than one done/not-done flag.

## The five stages

| Stage | Means | Produced by |
|---|---|---|
| `open` | Nothing references it at all | — |
| `addressed` | Somebody has worked on it | a **log** entry `addresses` it |
| `claimed` | A decision or component says it meets it, but that claim hasn't settled | a **decision**/**component** `satisfies` it, with a `status` not (yet) in the type's `satisfying_statuses:` |
| `satisfied` | A settled decision or component claims to meet it | a **decision**/**component** `satisfies` it, with a `status` in `satisfying_statuses:` |
| `verified` | A test proves it | a **test** `verifies` it |

The stage shown is the highest reached. They are cumulative in intent but not
required to be in practice — a requirement can be verified without any log entry
ever mentioning it.

`claimed` only appears for types that declare `satisfying_statuses:` — see
[below](#which-statuses-count-as-satisfying). A type that doesn't declare it never
produces a `claimed` requirement: every linked decision or component counts as
satisfying immediately, exactly like before this existed.

## Why several and not one

Because these fail differently:

- **Claimed but not settled** is the one that bit a real migration: a `status:
  on_hold` (or `proposed`) decision was being read as fully satisfying, silently.
  A decision that hasn't settled is a claim, not a fact yet.
- **Satisfied but not verified** is the next most dangerous. A settled decision
  says the design meets the requirement; nothing has proven it. This is normal
  mid-project and catastrophic at ship time, and a single "done" flag hides it
  completely.
- **Addressed but not satisfied** is work in progress. Somebody has been at it for
  three weeks and no decision has landed. Worth seeing.
- **Open** is untouched. Sometimes fine, sometimes a requirement everyone forgot.

## What gets coverage

Requirements and constraints, unless their `status` is `retired`. Imported items
are excluded — an upstream project's coverage gaps are that project's problem.

## The coverage page

`coverage.html` lists everything least-covered first:

```
open       CON-THM-002   Minimum converter efficiency      addr=—
open       REQ-PWR-004   3V3 regulation during input step  addr=—
open       REQ-PWR-005   40 V input transient tolerance    addr=—
addressed  CON-THM-001   Board power density               addr=LOG-A-005
satisfied  REQ-PWR-003   Efficiency > 90 % at half load    sat=DEC-PWR-001, ver=—
verified   REQ-PWR-001   Input supply 9 V to 36 V          ver=TST-PWR-001
verified   REQ-PWR-002   3V3 rail, 1.2 A, < 50 mV ripple   ver=TST-PWR-002
```

Counts by stage appear at the top, and the site index carries an **Outstanding
work** panel with the same rows. Each item's own page shows a coverage strip.

## Warnings

Two of the five stages are individually uninteresting at scale — a project
early in its life is mostly `open`, and "satisfied but not verified" is
routine noise before a test plan exists — so the build collapses each into
one summary line instead of one warning per item:

```
WARNING <project> — 3 item(s) with no coverage — see coverage.html
WARNING <project> — 2 requirement(s) satisfied but not verified — see coverage.html
```

`coverage.html` carries the per-item detail; the summary line just tells you
there is some. "Satisfied but not verified" is suppressed entirely when the
project has no `test` items at all — the moment the first one is added, these
become real findings again and start appearing.

`claimed` — an unsettled decision or component (`status` not yet in
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
`check` or `build`. Nothing coverage produces is `info` today; it's used
elsewhere (an unpinned citation, for instance) but shares the same flag, so
`-v` is worth knowing about even if you came here for coverage.

## Which statuses count as satisfying

By default, any decision or component linked with `satisfies:` counts as
satisfying — the item's own `status` field is not consulted. That is the
behavior every project already has, and it stays exactly that way on upgrade.

To have coverage respect settlement, declare `satisfying_statuses:` on the type:

```yaml
types:
  decision:
    fields:
      status: { type: enum, choices: [proposed, accepted, superseded, rejected],
                default: proposed }
    links:
      satisfies: [requirement]
    satisfying_statuses: [accepted]   # only an `accepted` decision satisfies
```

A decision whose `status` is not in that list still records the link — it shows
up as `claimed_by` on the requirement's coverage, and the requirement's stage
caps at `claimed` instead of `satisfied`. Declaring `satisfying_statuses:`
requires the type to have a `status` field; the project fails to load otherwise.

| `satisfying_statuses:` | Behavior |
|---|---|
| not declared *(default)* | Every `satisfies:` link counts as satisfying, regardless of status — unchanged from before this existed |
| a list of status values | Only a link whose `status` is in the list counts as satisfying; the rest count as `claimed` |

## Closing the gaps

| To move from | to | do this |
|---|---|---|
| `open` | `addressed` | write a log entry with `addresses: [REQ-X]` |
| `addressed` | `claimed`/`satisfied` | write a decision or component with `satisfies: [REQ-X]` |
| `claimed` | `satisfied` | move its `status` into the type's `satisfying_statuses:` list |
| `satisfied` | `verified` | write a test with `verifies: [REQ-X]` |

Any of these edges may be declared from either end — see [links](links.md).

## In `items.json`

```json
"coverage": {
  "REQ-PWR-003": {
    "stage": "satisfied",
    "addressed_by": ["LOG-A-003", "LOG-A-004", "LOG-A-006"],
    "claimed_by": [],
    "satisfied_by": ["DEC-PWR-001"],
    "verified_by": []
  }
}
```

This is the export to build a burndown chart, a status report, or a gate in CI
from. Read `items.json`, never scrape the HTML.
