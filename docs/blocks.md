# Generated blocks

A generated block is a directive that appears alone on its own line in a
**narrative page** and is replaced, at build time, with HTML computed from
the current state of the project — a table, a list, a small tree. It exists
so a page never has to hand-maintain something the project already knows:
which decisions land on which schematic page, what a requirement's
traceability graph looks like today.

**Scope: narrative pages only, not items.** An item is one typed record; a
block is a cross-item survey with no single item that would naturally own
it. [Calc blocks](math.md) are the mirror-image case — they belong on items
(a calc is something *this* item computes) and are meaningless on a page.
Item-scoped generation lives on items; project-scoped generation lives on
pages. Neither is legal in the other kind of document.

## Syntax

```markdown
{{index by="schematic_page" type="decision"}}
```

The directive must sit alone on its own line. The first token is the block
name; everything after it is `key="value"` pairs, the same attribute
microsyntax already used for image `{width=... caption="..."}` suffixes. A
name that doesn't match a known block is left completely untouched, as
literal text — a note to yourself like `{{TBD}}` keeps working. Once a name
*does* match, its parameters are validated strictly: an unknown parameter or
a missing required one is a build error naming the exact fix, matching every
other diagnostic this tool produces.

## `{{index}}`

Groups every local item of one type by the current value of a field,
rendered as one table per group.

```markdown
{{index by="schematic_page" type="decision"}}
```

| Parameter | Required | Meaning |
|---|---|---|
| `type` | yes | The item type to list. Must be a declared type. |
| `by` | yes | The field to group by. Must be a `text`, `enum`, `date`, `person`, `list`, or `quantity` field declared on `type`. |
| `board` | no | Scope to one board's items only. Must be a declared board. |

Each distinct value of `by` becomes its own `<h4>` heading and a two-column
table (ID, Title) beneath it, items sorted by ID within a group. A list-valued
field puts an item under every value it holds, not just the first. An item
with no value in the `by` field (missing, empty, or an empty list) is grouped
under `(unset)`, which always sorts last. Otherwise: an `enum` field with
declared `choices:` orders groups in that declared order; everything else
sorts lexicographically. Only local items are considered — an imported item
from another board's project is never listed, matching this feature's whole
purpose of keeping *this* project's own page in sync with *this* project's
own items.

No `sort=` or `limit=` parameter exists, and none is planned: an index is
meant to be exhaustive and to answer one question — "what are the current
values of this field?" — not to be a general reporting tool with a query
language bolted on.

## `{{cascade}}`

Renders a bounded, rooted walk of the traceability graph starting from one
item — "what does this decision ultimately satisfy, going up its links" or
"what is downstream of this requirement, going down its backlinks."

```markdown
{{cascade from="DEC-PWR-014" direction="up"}}
```

| Parameter | Required | Meaning |
|---|---|---|
| `from` | yes | The root item's ID. Must exist. |
| `direction` | yes | `up` (follow the root's own declared links), `down` (follow backlinks — what points at the root), or `both` (both, rendered as two separate labeled subtrees). |
| `depth` | no | How many hops to walk. A positive integer; defaults to `3`. |
| `via` | no | A comma-separated list of link type names to follow. Defaults to every link type whose schema declares it `trace: true` (every starter link except `amends`, `records`, `supersedes`, and `addresses`, which describe process rather than "this item's correctness rests on that one"). |

The walk stops expanding a node it has already visited on this walk — a
revisited node renders once more, as a leaf marked "(already shown above)",
rather than looping. This handles both a genuine cycle in the graph and a
legitimate diamond (two paths reconverging on the same item) with the same
rule. Reaching `depth` also stops expansion. A root with nothing to show at
the requested `direction` renders the root alone with a "nothing found"
note, not an error — an item legitimately having no outgoing (or incoming)
links of the traced types is a normal, valid state.

### Relationship to the `blocked_by:` cascade report

A separate, not-yet-implemented feature ([the standard library
design](design/standard-library.md) §9) walks `blocked_by:` links the same
rooted, bounded way, to compute a project's stale-blocker diagnostics. That
report and `{{cascade}}` are **two features sharing one walk primitive, not
one mechanism** — the report is automatic and always-on, tied into coverage
and `refdes audit`, with a cycle in it treated as a hard build error since a
`blocked_by` graph is asserted acyclic; `{{cascade}}` only renders where an
author places it, and treats a cycle as a normal, renderable reconvergence
since it can't assume acyclicity from an arbitrary `via=`. Once `via=` and
`blocked_by:` links both exist, nothing stops an author from writing
`{{cascade from="DEC-IO-005" direction="up" via="blocked_by"}}` for an ad
hoc rendering of one blocker chain — that's a convenience overlap, not a
substitute for the dedicated report, which computes staleness and feeds
coverage in a way the block does not.

## Failure modes

Both blocks validate strictly and name the specific fix, the same bar every
other refdes diagnostic holds to:

```
{{index by="pageno" type="decision"}} — type 'decision' has no field 'pageno'.
    Declared fields: schematic_page, status, title.
```

```
{{index by="status" type="decisoin"}} — unknown type 'decisoin'.
    Did you mean 'decision'?
```

```
{{cascade from="DEC-PWR-014" direction="sideways"}} — unknown direction
    'sideways'. cascade accepts: down, up, both.
```

```
{{index by="status" type="decision" sortt="asc"}} — unknown parameter
    'sortt'. index accepts: by, type, board.
```

A block that fails validation renders a visible `⚠` marker in its place on
the page — the build still stops with a nonzero exit, but the broken
directive isn't silently swallowed while you're reading the diagnostic.

## The non-goal

Refdes's generated blocks take **parameters, never expressions.** `index`,
`cascade`, and whatever joins them are a small, closed family — each
accepts a small, closed set of named parameters, each with one fixed
meaning, validated against the resolved schema at build time. There is no
comparison operator, no `and`/`or`, no wildcard, and no nesting one block
inside another. A block only ever selects and arranges items that already
exist in the project; it cannot decide that something exists, is true, or
is correct, and it cannot be composed into an expression the tool would have
to parse and evaluate. That is what keeps a generated index or cascade as
auditable as the hand-maintained table or diagram it replaces: anyone who
can read `by="schematic_page" type="decision"` or `from="REQ-IO-001"
direction="down"` already knows exactly what will appear on the page, with
no interpreter and no query language standing in between the source and the
number.

This is a design decision, not a current limitation — a future filter,
comparison, or wildcard parameter is not on the roadmap.
