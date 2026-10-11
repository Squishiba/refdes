# Concepts

## Items

Everything is an **item**: a requirement, a bound, a component, a test,
a log entry, a group. An item has

- a stable **ID** (`REQ-PWR-002`) that never changes,
- a **type**, which decides what fields and links are legal,
- **fields** (typed values from the schema),
- **links** to other items,
- an optional **markdown body**.

The type is `component`, the world calls it a part, and the site's
[Parts page](parts.md) is the components page: `parts.html` indexes every field
literally named `part_number` (plus the part numbers inside `citations:`
entries) instead of adding a second type called `part`.

Item types are not hard-coded. They are declared in `refdes-schema.yaml`, so
adding a `thermal_zone` type is a config change, not a code change. See the
[schema reference](schema-reference.md).

## Which grouping?

Five of these file an item somewhere; the sixth is a view of the lot. They are
not interchangeable, and the difference is not visible in the word — which is
why they are in one table instead of five paragraphs:

| | What it is for | Data or path? | In coverage? |
|---|---|---|---|
| **`board`** | One physical board in a family of boards sharing a project. Registered in `boards:` — opt-in, and an item-level `board:` override naming a board that is not registered is a build error. | Path: the first segment under `items/` (the second under `item_layout: workspace`), overridable by the reserved `board:` key. | Yes, as a scope: each board with items gets `coverage-<board>.html`, and a board declaring `conforms_to:` gets the stages computed again for each member of that group, counting only that board's own satisfiers. |
| **`workspace`** | The ownership boundary one level above boards: the seam along which a project would later split. Registered in `workspaces:`; the cross-workspace link lint is what it buys. | Path when `item_layout: workspace` (`items/<workspace>/<board>/`); under `flat`, only what a `workspace:` key says. | Yes, as a scope only: `coverage-<workspace>.html` filters the same rows to that workspace's items. Nothing is recomputed per workspace — the per-board recomputation has no workspace equivalent. |
| **`group`** | A named collection of items — "the PCIe interface spec" — that can be pointed at without standing in for its members. | Data: an item type (`GRP`) with members pointing at it via `part_of:`; the group never lists its own members. | No. `coverable: false`, and it is absent from every `satisfies:` target list, so nothing may claim it. It touches coverage only indirectly: `conforms_to:` names a group, and its *members* are what the per-board rows are about. |
| **`section`** | Nothing outside the file that contains it. A `- section: <type>` entry in a list file — or a `section:` marker block in Markdown — asserts the **type** of every item below it until the next marker; an item that disagrees is an error naming both. | Neither: file-local authoring syntax. It is not a field on the item (`items.json` carries no `section`), and it is not a path segment. | No. |
| **`tag`** (`tags:`) | Finding items again: `refdes ls --tag io`, the free-text `refdes ls` query (which matches tags as well as titles), and `tag=` on the `{{index}}` and `{{compare}}` blocks. | Data: a `tags:` list field, part of the `provenance` set, `on_change: ignore` — so retagging marks nothing suspect. | No. Coverage reads `coverable:`, statuses, and verifier links; tags are none of those. |
| **`{{tree}}`** | The nesting every item has without the author declaring anything: workspace, then board, then `part_of` group, then item — as the `tree.html` report, or `{{tree}}` inside a body. | Neither: it is a rendered view of the two path levels and the one link above. | No. It displays items; it computes nothing that coverage reads. |

So: if you only want to find those items again, that is a **tag**, not a group —
a group is an item with an id, and every member has to say `part_of:` to belong.
If you want a folder the build checks against a registry, that is a **board**,
not a group. And if you are typing `section:` to group things project-wide,
you are not: it only ever says what type the next lines are.

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

This is what makes checking possible: a limit of `<= 0.15 W/in^2` and a
computed `0.2366 W/in²` are comparable quantities, not strings.

## Checks are evaluated at the worst case

When a value has a tolerance, a check uses the bound that is hardest to satisfy —
the upper bound for `<=`, the lower bound for `>=`. A nominal that passes while a
tolerance corner fails is reported as a failure, because that is what it is.

## The five coverage stages

The most important idea in the tool. Three of these — `addressed`, `satisfied`
and `verified` — are separate senses of "done", and collapsing them is how open
work goes missing. `claimed` is a satisfied claim that has not settled; `open`
is the absence of all of them:

| Stage | Means | Comes from |
|---|---|---|
| `open` | Nothing references it | — |
| `addressed` | Somebody has worked on it | a **log** entry `addresses` it |
| `claimed` | A verdict or component says it meets it, but that claim hasn't settled | a **log**/**component** `satisfies` it, with a `status` not (yet) in the type's `satisfying_statuses:` |
| `satisfied` | A settled verdict or component claims to meet it | a **log**/**component** `satisfies` it, with a `status` in `satisfying_statuses:` |
| `verified` | A test proves it | a **test** `verifies` it |

A requirement can be satisfied on paper and completely unverified. Another can be
addressed for weeks with no decision reached. One "done" flag hides both. See
[coverage](coverage.md).

## Verdicts and running notes

A **log entry** is one entry in the design's story: either a running note —
the measurement that surprised you, the approach that failed — or a **verdict**,
a settled conclusion with the options considered and why the rejected ones lost.
An entry that just narrates sets `summary` and a body; an entry that also reaches
a verdict adds a `status` to the same type, and an `accepted` one closes coverage
on what it `satisfies`. Read a verdict later to find out why the board is the way
it is; read the entries in order to understand how the design got here.

Log entries are **append-only**: a correction is a new entry that `amends` or
`supersedes` the old one, not a rewrite of it. That is the paper-notebook
convention, but under `hardware@3` the build does not enforce it — an edit is
not a build error, and once an entry's history is captured, a later edit is
flagged with a warning (`hardware@1` and `hardware@2` kept settled conclusions
in a separate `decision` type; `hardware@3` merged it into `log` — see the
[standard library](standard-library.md#versioning-and-pinning) and the
[design log](design-log.md#append-only).)

## Change is classified, not just recorded

Every field declares what a change to it means:

| `on_change` | Timeline | Baseline diff | Invalidates downstream |
|---|---|---|---|
| `invalidate` | yes | yes | yes |
| `log` | yes | no | no |
| `ignore` | no | no | no |

The last two columns are behaviour today; the timeline column is design
intent for the parked git-history layer, so `log` and `ignore` are currently
indistinguishable in every observable way. See [change
tracking](change-tracking.md#the-three-modes).

The **content hash** of an item is computed over its `invalidate` fields only. That
is what stops a change of owner from marking fifty links suspect, and it is the
hook the git history layer plugs into. See [change tracking](change-tracking.md).

## Two serializations, one model

Rich items — verdict entries, anything with prose or math — get their own markdown file.
Bulk items — requirements, log entries — go in list files sharing `defaults:`.
Both produce identical items. Neither is a lesser form, and
`refdes promote` (not yet built) is intended to move an item between them.

A markdown file is not limited to one item, either: a further `---` starts a new
item's front-matter, and an optional leading `defaults:` block applies to every
item that follows, the same way it does in a list file. See [several items in
one file](authoring.md#several-items-in-one-file).

## What is deliberately not here

- **No code execution.** The calc DSL has no loops, conditionals, imports, or
  attribute access. Documents cannot run code, so results are deterministic and
  untrusted input is safe.
- **No database.** Files are the source of truth, git is the history.
- **No server.** The output is static HTML that works with JavaScript disabled.
