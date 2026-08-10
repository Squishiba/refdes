# Concepts

## Items

Everything is an **item**: a requirement, a constraint, a decision, a component, a
test, a log entry. An item has

- a stable **ID** (`REQ-PWR-002`) that never changes,
- a **type**, which decides what fields and links are legal,
- **fields** (typed values from the schema),
- **links** to other items,
- an optional **markdown body**.

Item types are not hard-coded. They are declared in `refdes.yaml`, so adding a
`thermal_zone` type is a config change, not a code change. See the
[schema reference](schema-reference.md).

## Links are edges, declarable from either end

`verified_by` and `verifies` are the same edge seen from opposite ends. Declare it
once, from whichever end is natural, and the reverse direction is computed:

```yaml
# in the test — natural, because the test knows what it covers
verifies: [REQ-PWR-002]
```

`REQ-PWR-002` now shows `verified_by: [TST-PWR-002]` without mentioning the test.
Declaring both ends is allowed but redundant.

## Units are the type system

Inside a `calc` block, `3.3 V * 1.2 A` is 3.96 W because it cannot be anything
else. `3.3 V + 1.2 A` is a build error, not a silent wrong answer. Tolerances
propagate as intervals, so `12 V ± 5%` carries 11.4 V to 12.6 V through every
subsequent expression.

This is what makes constraint checking possible: a limit of `<= 0.15 W/in^2` and a
computed `0.2366 W/in²` are comparable quantities, not strings.

## Checks are evaluated at the worst case

When a value has a tolerance, a check uses the bound that is hardest to satisfy —
the upper bound for `<=`, the lower bound for `>=`. A nominal that passes while a
tolerance corner fails is reported as a failure, because that is what it is.

## The three notions of "done"

The most important idea in the tool. These are separate questions and collapsing
them is how open work goes missing:

| Stage | Means | Comes from |
|---|---|---|
| `open` | Nothing references it | — |
| `addressed` | Somebody has worked on it | a **log** entry `addresses` it |
| `satisfied` | A decision claims to meet it | a **decision** `satisfies` it |
| `verified` | A test proves it | a **test** `verifies` it |

A requirement can be satisfied on paper and completely unverified. Another can be
addressed for weeks with no decision reached. One "done" flag hides both. See
[coverage](coverage.md).

## Decisions vs. log entries

A **decision** is a settled conclusion, with the options considered and why the
rejected ones lost. It is a reference document — you read it later to find out why
the board is the way it is.

A **log entry** is a dated step on the way to a conclusion, including the
measurement that surprised you and the approach that failed. It is a narrative — you
read it in order to understand how the design got here.

Decisions are edited as understanding improves. Log entries are **append-only**: a
correction is a new entry that `amends` the old one, never an edit. That is the
paper-notebook convention, and it is enforced by the build.

## Change is classified, not just recorded

Every field declares what a change to it means:

| `on_change` | Timeline | Baseline diff | Invalidates downstream |
|---|---|---|---|
| `invalidate` | yes | yes | yes |
| `log` | yes | no | no |
| `ignore` | no | no | no |

The **content hash** of an item is computed over its `invalidate` fields only. That
is what stops a change of owner from marking fifty links suspect, and it is the
hook the git history layer plugs into. See [change tracking](change-tracking.md).

## Two serializations, one model

Rich items — decisions, anything with prose or math — get their own markdown file.
Bulk items — requirements, log entries — go in list files sharing `defaults:`.
Both produce identical items. Neither is a lesser form, and
`refdes promote` (not yet built) is intended to move an item between them.

## What is deliberately not here

- **No code execution.** The calc DSL has no loops, conditionals, imports, or
  attribute access. Documents cannot run code, so results are deterministic and
  untrusted input is safe.
- **No database.** Files are the source of truth, git is the history.
- **No server.** The output is static HTML that works with JavaScript disabled.
