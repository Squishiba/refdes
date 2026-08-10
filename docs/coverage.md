# Coverage

Coverage answers "what still needs doing" with three separate questions rather than
one done/not-done flag.

## The four stages

| Stage | Means | Produced by |
|---|---|---|
| `open` | Nothing references it at all | — |
| `addressed` | Somebody has worked on it | a **log** entry `addresses` it |
| `satisfied` | A decision claims to meet it | a **decision** `satisfies` it |
| `verified` | A test proves it | a **test** `verifies` it |

The stage shown is the highest reached. They are cumulative in intent but not
required to be in practice — a requirement can be verified without any log entry
ever mentioning it.

## Why three and not one

Because these fail differently:

- **Satisfied but not verified** is the dangerous one. A decision says the design
  meets the requirement; nothing has proven it. This is normal mid-project and
  catastrophic at ship time, and a single "done" flag hides it completely.
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

The build warns about anything not fully verified:

```
WARNING items/constraints/thermal.yaml:17 [CON-THM-002] — nothing addresses,
        satisfies, or verifies this yet
WARNING items/requirements/power.yaml:20 [REQ-PWR-003] — satisfied but not
        verified (no test links to it)
```

These are warnings, not errors — a mid-project board legitimately has both. Use
`refdes check` in CI and decide for yourself whether to gate on warnings.

## Closing the gaps

| To move from | to | do this |
|---|---|---|
| `open` | `addressed` | write a log entry with `addresses: [REQ-X]` |
| `addressed` | `satisfied` | write a decision with `satisfies: [REQ-X]` |
| `satisfied` | `verified` | write a test with `verifies: [REQ-X]` |

Any of these edges may be declared from either end — see [links](links.md).

## In `items.json`

```json
"coverage": {
  "REQ-PWR-003": {
    "stage": "satisfied",
    "addressed_by": ["LOG-A-003", "LOG-A-004", "LOG-A-006"],
    "satisfied_by": ["DEC-PWR-001"],
    "verified_by": []
  }
}
```

This is the export to build a burndown chart, a status report, or a gate in CI
from. Read `items.json`, never scrape the HTML.
