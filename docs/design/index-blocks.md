# Generated blocks and figure references — design spec

## Decision

Decisions carry a `schematic_page` field. Today, if a narrative page wants a
page-number-to-decision table, someone hand-writes it — and it's stale from
the moment it's typed, because nothing regenerates it and nothing notices
when a decision's `schematic_page` changes. The same shape recurs for
by-owner, by-status, and by-date views, and will keep recurring. Separately,
a design record printed or archived as `document.html` has no way to say
"see Figure 3" — images have no identity, so they can't be numbered or
cross-referenced.

Refdes will add **`{{index by="<field>" type="<type>"}}`** — a directive
that appears alone on its own line in a narrative page and is replaced, at
build time, with a table grouping every local item of `type` by the current
value of its `by` field — and **`{{cascade from="<id>" direction="<dir>"}}`**
(§6), a directive that renders a bounded, rooted walk of the traceability
graph from one item. These are the **first two members of a small, fixed
family** of named query blocks. There will never be a member of this family
that lets an author write a comparison, a boolean expression, a wildcard, or
nesting — every block takes a small set of named parameters, each with one
fixed meaning, and answers exactly the question its name says it answers.
§8 states why, in words meant to be lifted into the docs.

Alongside the block family, this document also specs **figure identity and
numbering** (§9–§10) — a separate but related gap: today's `{width=
caption="..."}` image syntax has no notion of a stable figure identity, so
nothing can say "Figure 3" and mean it, or link to it from prose.

**Scope: narrative pages only, not items.** An item is one typed record; an
index or a cascade is a cross-item survey with no single item that would
naturally own it. Calc blocks are the mirror-image precedent — they belong
on items (a calc is something *this* item computes) and are meaningless on a
page (there is no "this" to compute against). The split is: item-scoped
generation lives on items, project-scoped generation lives on pages. Neither
kind of block is legal in the other kind of document.

**Implemented**, as of v0.5.0 (unreleased) — `{{index}}` and `{{cascade}}`
(`refdes/blocks.py`) and figure identity/numbering (`build.py`'s
`_apply_figure_attrs`/`resolve_figures`, the `fig:` reference namespace).
This header is stale from an earlier draft; the document's prose describes
the landed shape accurately — verify specifics against `blocks.py`/`build.py`
rather than assuming this file is current.

---

## 1. Block syntax and where it's allowed

### Delimiter

Reuses the `{{...}}` envelope already established for inline calc-value
substitution (`INLINE_VALUE_RE`, `src/refdes/build.py:22`) rather than
inventing a second bracket convention — one delimiter family to learn, not
two. Inside the braces, the first token is the block name; everything after
it is `key="value"` pairs, parsed with the same attribute microsyntax
already used for figure captions (`FIGURE_ATTR_RE`,
`src/refdes/build.py:37`: `([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|(\S+))`).
No new parser — the tool already owns a regex for exactly this shape.

```markdown
{{index by="schematic_page" type="decision"}}
```

Must sit alone on its own line (its own markdown paragraph). This isn't an
arbitrary restriction — it's what lets the block reuse the *exact* placement
trick calc blocks already use: a token alone on a line renders, through
`markdown-it`, as `<p>{{index ...}}</p>`, the same shape a calc placeholder
renders as (`f"<p>{token}</p>"`, `src/refdes/build.py:559`), and gets found
and swapped the same way. A block name that isn't recognized, or text that
merely starts with `{{` but doesn't parse as `<known-name> key="value" ...`,
is left completely alone — same posture `_apply_figure_attrs`
(`src/refdes/build.py:490`) already takes toward any paragraph that isn't
*exactly* one image plus one attribute suffix: touch only the shape you
recognize, pass everything else through untouched. This means `{{TBD}}` or
`{{some note to self}}` typed as ordinary prose renders as literal text, not
an error — only a first token matching a real block name commits to being a
directive, and from that point on its parameters are validated strictly.

### Where extraction happens, relative to the existing regex passes

`render_pages` (`src/refdes/build.py:571`) today runs, in order:

```
html = md.render(page.body)
html = _process_images(html, ...)
html = _apply_figure_attrs(html)
html = _linkify(html, ...)
page.body_html = pages_mod.rewrite_page_links(html, known)
pages_mod.add_heading_anchors(page)
```

Index blocks add one step **before** `md.render` and one **immediately
after** it, mirroring exactly how `render_bodies` (`src/refdes/build.py:521`)
already handles calc blocks — extract from raw markdown source before the
parser sees it, render, then swap a placeholder token for real HTML:

1. **Before `md.render`**: scan `page.body` for `{{index ...}}` lines,
   validate each (§5), and replace each with a plain-text placeholder token
   (`xxrefdesindexNxx`, following the existing `_placeholder()` convention at
   `src/refdes/build.py:397`) so markdown can't mangle it.
2. `html = md.render(source)` — unchanged.
3. **Immediately after render**, swap each `<p>xxrefdesindexNxx</p>` for the
   generated `<table>` (or empty-state `<p>`, §5) — the same swap
   `render_bodies` performs for calc tables at `src/refdes/build.py:559-562`.
4. *Then* `_process_images`, `_apply_figure_attrs`, `_linkify`,
   `rewrite_page_links`, `add_heading_anchors`, unchanged and in the same
   order as today.

The reason step 3 has to land **before** `_linkify` is the one placement
decision in this document that isn't just "match the existing precedent" —
it's load-bearing. An index table's cells are, overwhelmingly, item IDs. If
the generated `<table>` is injected before `_linkify` runs, `_linkify`'s
existing regex pass over the *whole* rendered page (it already treats
`<pre>`/`<code>` as the only protected region — `PROTECTED_RE`,
`src/refdes/build.py:24`) picks up every ID cell for free and turns it into
a real cross-reference link with the standard hover preview, `data-ref`
attribute, and "missing" styling if the target vanished — identical to a
hand-typed `[[DEC-PWR-002]]` anywhere else on the page. The block itself
never builds an `<a>` tag; it emits bare ID text and lets the page's normal
linkify pass do what it already does. This is the whole reason index-table
injection is sequenced as "step 3 of render_pages," not tacked on as a
separate post-processing pass after `_linkify` — doing it after would mean
either duplicating `_linkify`'s link-building logic inside the index block
(two places that can drift) or shipping an index whose entries don't behave
like every other reference on the page.

`_process_images` and `_apply_figure_attrs` are unaffected either way —
neither touches table markup — so their relative order versus the table
swap doesn't matter; step 3 is placed right after render purely to keep the
"placeholder swap happens in one place, right after render" invariant
`render_bodies` already established, rather than inventing a second point in
the pipeline where placeholders get resolved.

### Line numbers for diagnostics

Page-level diagnostics today have a real gap worth naming here rather than
discovering it during implementation: `_linkify` is called for pages with no
`where_line` (`_linkify(html, project, page.source_file)`,
`src/refdes/build.py:580` — the four-argument call, versus items' five-argument
call that passes `item.source_line`), so a bad cross-reference on a page
reports `file`, no line. Narrative pages can be long, and "name the specific
fix" (§5) is weaker without a line number pointing at which of possibly
several index blocks on the page is wrong. The extraction pass in step 1
above operates directly on raw source text and can count newlines up to each
match's offset itself — same as any regex-driven line lookup elsewhere in
the tool — so index-block diagnostics should carry a real line number even
though today's page-level `_linkify` diagnostics don't. This is a one-block
fix, not a prerequisite refactor of `_linkify` itself.

---

## 2. Parameters

Three, each a single fixed knob:

| Parameter | Required | Meaning |
|---|---|---|
| `by` | yes | Field name to group items by |
| `type` | yes | The one item type to index |
| `board` | no | Restrict to one board's local items |

### `type` is required, and singular

`by` cannot resolve a field's meaning without knowing which type's `by`
field is meant — the standard-library design (`docs/design/standard-library.md`
§1) is explicit that a field with the same *name* can carry a different
*meaning* per type ("`status` means something structurally different on a
`requirement` than on a `decision`"), which is exactly why that document
only shares a `field_sets:` entry across types when the field is
byte-identical. Letting `type` be a list, or omitting it and indexing every
type that happens to declare the named field, would silently paper over that
same hazard inside one block. If a project wants decisions and components
indexed by the same field, that's two `{{index}}` blocks, not one — the
family's whole premise (Decision, above) is that the cost of one more block
call is linear and acceptable; the cost of teaching one block to reason
about multiple types at once is not.

### `board`, argued in — not deferred

Every other generated report in this tool already takes an optional board
scope the same way: `_document_sections(project, board=None)`,
`_coverage_rows(project, board=None)`, `_log_entries(project, board=None)`
(`src/refdes/render.py:40,71,83`) all filter with the identical
`board is None or i.board == board` test, and `render_site` already produces
a `-{board}` suffixed variant of every one of those reports
(`src/refdes/render.py:621-692`). An index block with no way to scope to one
board would be the only generated view in the whole tool that can't be
narrowed that way — and unlike those other reports, an index block lives
*inside* a hand-placed narrative page, so there's no automatic per-board
variant being generated on its behalf. Add it now, at the cost of one
parameter with an already-fully-defined meaning, rather than shipping a v1
that multi-board projects hit a real gap in immediately. Validated the same
way as every other board reference: unknown value is a difflib-suggested
error against `project.boards` (§5), same posture as an unknown `type`.

**`workspace` is dropped.** Nothing in this codebase defines a "workspace"
concept distinct from a board — inventing one here to satisfy the brief's
"argue for or against" would be adding a concept the rest of the tool
doesn't have, which is the opposite of what this design is supposed to do.

### No `sort` parameter

Item order within a group is fixed: ascending by item ID — the same rule
`_document_sections` already applies to every non-`log` section
(`src/refdes/render.py:59`) and `_coverage_rows` uses as its tie-break
(`src/refdes/render.py:79`). A `sort=` parameter would be the first
parameter anywhere in this family whose *value* names another field to
reason about — a small crack that points straight at the expression-grammar
door this document exists to keep shut (§8). Group *ordering* (as opposed to
item ordering within a group) is likewise fixed, not configurable — see §4.

### No `limit` parameter

`summary_payload` does truncate one table today —
`"log_entries": log_entries[:10]` (`src/refdes/render.py:197`) — but that's
a "recent activity" widget where the 11th-oldest entry genuinely doesn't
matter to the question being asked. An index block exists specifically to
*replace* a hand-maintained table that was wrong because it silently drifted
out of date; a `limit=` that silently drops rows past a cutoff would
reintroduce the same failure in a new form — a table that looks complete but
isn't. An index always renders every matching local item. If a resulting
table is too large to be useful, that's a signal to reconsider the `by`
field or split the page, not something a truncation knob should paper over.

---

## 3. Rendering

**Always a table. Never adapts by field type.** Branching the rendering
shape on whether `by` names an enum, a date, a person, or a list field is
exactly the kind of per-type special-casing "fewer concepts" argues against
— it would mean an author has to remember which of five renderings a given
field type produces before they can predict what their page looks like. One
shape, always, is simpler to learn and simpler to build.

### Grouping is headings, not a repeated column

Each distinct value of `by` becomes its own heading, followed by a small
table of the items carrying that value — mirroring how the tool already
groups things it groups at all: `_document_sections` returns
`list[tuple[label, list[Item]]]`, one heading-and-table pair per type
(`src/refdes/render.py:40-68`), not one flat table with a repeated type
column. An index block follows the same shape rather than inventing a new
one. This also answers the list-valued-field question for free (below) —
appearing under two headings is just what "group by value" means when an
item has two values, no special bookkeeping required.

Group headings render as **`<h4>`**, deliberately one level below what
`add_heading_anchors` treats as an on-page table-of-contents entry — its
`HEADING_RE` only matches `<h2>`/`<h3>` (`src/refdes/pages.py:97`). An index
grouped by `schematic_page` on a large board could produce dozens of
headings; letting every one of them flood the page's on-page contents list
would make the *page's* navigation worse in the process of making the
*data* more current. `<h4>` passes through `add_heading_anchors` unanchored,
which is also simply less to build — no id-collision handling needed for
machine-generated headings.

### Columns

Each group's table has exactly two columns: **ID**, **Title** — `item.id`
and the existing `item.title` property (`src/refdes/model.py:201-211`,
which already falls back through `title → text → summary → name → id`).
These are the two facts every item type can supply regardless of which
fields it declares, so the column set never has to change per `type=`. No
third "value" column, because the value is already the heading.

### Items missing the `by` field

Grouped under a visible **`(unset)`** heading, not omitted. An index exists
to be the authoritative view; an item silently missing from it because a
field was never filled in is the exact failure mode this feature is meant
to eliminate, just moved one level down. This matches the tool's existing
posture toward gaps generally — `summary_payload`'s orphans table
(`src/refdes/render.py:149-158`) surfaces items connected to nothing rather
than leaving them out of every table that would otherwise show them.
`(unset)` always sorts last (§4), regardless of what ordering the rest of
the field's values use.

### List-valued fields

An item whose `by` field is `type: list` (e.g. `refdes`, `tags`) appears
under every value it holds, once per value, as a direct consequence of
"group by value" applied to a multi-valued field — not a special case, and
not a parameter (`list_mode=` or similar) that would need documenting on
top of the three in §2.

### Field types the block will and won't index

`by` may name a field of type `text`, `enum`, `date`, `person`, `list`, or
`quantity` (docs/schema-reference.md's field-type list, minus the three
excluded below) — anything that resolves to a groupable scalar or list of
scalars. It rejects `checks`, `citations`, and `limit` — see §5 for the
diagnostic. Those three are structured records (a list of check results, a
list of citation entries, a comparison expression), not values with a
"current reading" a heading could name.

---

## 4. Ordering

**Groups**, by field value:

| `by` field type | Group order |
|---|---|
| `enum` | The type's declared `choices:` order (already a meaningful sequence — e.g. `draft, active, retired` is a lifecycle, not an alphabet) |
| `date` | Chronological |
| `text`, `person`, `list`, `quantity` | Lexicographic (plain string sort — the same default `sorted()` behavior the rest of the codebase already relies on everywhere else, e.g. `sorted(project.coverage.items())`) |
| *(missing)* | `(unset)`, always last, regardless of the field's type |

Reusing `choices:` order for enums costs nothing new to build — it's
information the schema already declares — and it's the one case where plain
lexicographic order would visibly misorder something a reader already knows
the "real" order of (nobody reads `active, draft, retired` as the intended
progression).

**Items within a group**, by item ID ascending — no new rule; this is
exactly the ordering `_document_sections` already applies to every
non-`log` section (`src/refdes/render.py:59`) and `_coverage_rows` already
uses as its own tie-break (`src/refdes/render.py:79`). Free text has no
natural order beyond lexicographic, and grouping *items* by ID rather than
by anything else keeps that answer the same in every group, in every index,
regardless of `by`.

---

## 5. Failure modes and diagnostics

Matches the bar `docs/checks.md` and the standard-library design already
set: name the specific fix, not a generic "invalid" message.

**Unknown type:**

```
ERROR pages/schematic.md:12 — {{index type="decison"}} — unknown type
      'decison'. Did you mean 'decision'?
```

Same difflib-suggestion machinery `validate_items`
(`src/refdes/build.py:58-62`) already uses for a bad enum value.

**Field not declared on the named type:**

```
ERROR pages/schematic.md:12 — {{index by="schematic_page" type="decision"}}
      — type 'decision' has no field 'schematic_page'. Declared fields:
      title, status, rationale, date, options, checks, source, note, owner,
      last_reviewed.
```

Lists the type's actual resolved fields (`spec.fields`, `src/refdes/model.py:96`)
the same way the standard-library design's `required_when` error lists a
field's actual `choices:` rather than just saying "invalid"
(`docs/design/standard-library.md` §2). This also catches, for free and with
no special-casing, an author trying to index a computed property that isn't
a real field at all — `by="id"` or `by="title"` fail exactly this same
check, because neither is a key in `spec.fields`.

**Field exists but isn't a groupable type:**

```
ERROR pages/schematic.md:12 — {{index by="checks" type="decision"}} —
      'checks' is type 'checks', not a groupable field. index supports
      text, enum, date, person, list, and quantity fields.
```

**Unknown parameter:**

```
ERROR pages/schematic.md:12 — {{index by="schematic_page" type="decision"
      sort="date"}} — unknown parameter 'sort'. index accepts: by, type,
      board.
```

**Missing required parameter:**

```
ERROR pages/schematic.md:12 — {{index type="decision"}} — index is missing
      required parameter 'by'.
```

**Unknown board:**

```
ERROR pages/schematic.md:12 — {{index by="schematic_page" type="decision"
      board="powr"}} — unknown board 'powr'. Did you mean 'power'?
```

**Index matches nothing** — not a build error. A type with zero local items
yet is the normal state of an early-stage board, the same posture
`summary_payload`'s empty tables already take. But rendering literally
nothing would leave an author staring at a blank stretch of page wondering
whether their directive even ran, so it renders one visible line instead of
either a build failure or silence:

```html
<p class="index-empty">No decision items.</p>
```

**Scope of "matches nothing" / "matches something": local items only.**
Imported items are excluded from every group, the same way
`_document_sections` corrals them into their own separate "Imported
references" section rather than folding them into a type's own section
(`src/refdes/render.py:62-68`) — an index reflects this project's own
record, not an upstream project's, matching the same local/imported split
every other cross-item view in the tool already makes.

---

## 6. The cascade view

The second member of the family, and the one that proves the conventions in
§1–§5 generalise rather than being accidental properties of grouping-by-field.

A whole-project link diagram is a hairball nobody uses for real work — this
codebase's own sample project has on the order of 65 items, and every one of
its ten link verbs (`docs/design/standard-library.md` §1) drawn at once would
be unreadable and, worse, wouldn't answer any question anyone actually has.
The question that's actually asked is always rooted: "show me everything
that traces from this requirement downward," or "show me everything this
decision depends on upward." `{{cascade}}` answers exactly that — a bounded
walk starting at one named item, never the whole graph.

```markdown
{{cascade from="REQ-IO-001" direction="down"}}
```

### Parameters

| Parameter | Required | Meaning |
|---|---|---|
| `from` | yes | The root item's id |
| `direction` | yes | `down`, `up`, or `both` |
| `depth` | no, default `3` | Maximum number of hops from the root |
| `via` | no, default: every `trace`-enabled link type (below) | Comma-separated list of link type names to follow |

`from` and `direction` are required, with no default, for the same reason
`index`'s `by`/`type` are (§2) — a query that silently assumed a direction
would be surprising exactly when it matters most: "why didn't my decision's
dependencies show up" is a worse failure mode than a build-time reminder to
say which way to walk.

### Direction: which edge, in which sense

An edge in this schema is always declared on one end and computed as a
backlink on the other — `resolve_links` (`src/refdes/build.py:90-114`) walks
every item's own `links:` and appends the reverse onto the target's
`backlinks:`. `item.html.j2` already renders this as two separate panels,
**Outgoing** (the item's own declared `links:`, looked up by `label` —
`src/refdes/templates/item.html.j2:130-140`) and **Incoming** (its
`backlinks:`, shown by their raw inverse name —
`src/refdes/templates/item.html.j2:143-154`). `direction` is exactly this
split, applied recursively instead of one hop deep:

- **`direction="down"`** walks **backlinks** — what points *at* the current
  node, recursively. Starting from a requirement, this is everything that
  satisfies, verifies, refines, or otherwise claims to trace to it: the
  concrete artifacts that "hang off" a requirement, which is what "traces
  downward from this requirement" means in practice.
- **`direction="up"`** walks the current node's own **declared `links:`**,
  recursively. Starting from a decision, this is what *it* points at —
  `constrained_by`, `satisfies`, `selects` — the things it depends on or is
  justified by, which is "what this decision depends on" read literally.
- **`direction="both"`** renders **two independent subtrees** under the root
  — an "Upward" one and a "Downward" one, each walked and cycle-checked with
  its own separate visited-set (below) — rather than one merged tree. A
  merged tree would leave a reader unable to tell, at a glance, whether a
  given line is something the root depends on or something that depends on
  the root; two clearly labeled subtrees answers that for free and needs no
  new tree-merging logic beyond running the down-walk and the up-walk once
  each.

### Which link types participate: a schema flag, not a hardcoded list

Mixing `satisfies`, `amends`, and `supersedes` in one cascade is close to
useless — `amends` is a log correction chain and `supersedes` is a
replacement chain; neither is "this item's correctness is justified by
that one," which is what a traceability cascade is for. The tempting fix is
a hardcoded list of "spine" verb names inside refdes itself, but that only
helps a project using the shipped standard (`docs/design/standard-library.md`
§1) — a `standard: none` project's own bespoke verbs would get no benefit
and would have to pass `via=` on every single cascade in the project to get
a useful result.

Instead, `LinkType` (`src/refdes/model.py:66-70`) gains one more flag,
alongside `inverse` and `label`:

```yaml
link_types:
  amends:      { inverse: amended_by,    label: "Amends",      trace: false }
  records:     { inverse: recorded_by,   label: "Records",     trace: false }
  supersedes:  { inverse: superseded_by, label: "Supersedes",  trace: false }
  addresses:   { inverse: addressed_by,  label: "Addresses",   trace: false }
  satisfies:   { inverse: satisfied_by,  label: "Satisfies" }               # trace: true, the default
```

`trace` defaults to `true` — every link participates in a cascade's default
`via` set unless its schema explicitly opts it out. This is schema-declared
metadata, exactly like `check_severity` and `satisfying_statuses` already
are (`src/refdes/model.py:104-110`) — a fact about the verb, set once, not
something an author composes per-block — so it stays firmly on the
parameters side of §8's line, not the expressions side. If
`docs/design/standard-library.md` adopts this, its own §1 would want
`trace: false` on `amends`, `records`, `supersedes`, and `addresses` — a
forward pointer, not a change made in this document, since this document
doesn't own that file's §1.

`via="satisfies,verifies"` overrides the default set explicitly, for the
rarer case an author wants exactly one or two verbs rather than the whole
trace-enabled set — validated the same way an unknown `type` is (§5):
unrecognized names are difflib-suggested against `project.link_types`.

### Depth

Unbounded is the wrong default for a feature whose entire premise is "not a
global project graph... rooted at one item, bounded" (this section's own
opening). `depth` defaults to `3` and can be set higher for a deliberately
wide view — three hops covers the overwhelming majority of "does this trace
to something" questions without an explicit ask. There is no enforced upper
bound: an author asking for `depth="10"` gets a bigger block, not an error —
the tool doesn't need to protect against a choice that's visible and
reversible in the source, only against the *default* being unreadable by
accident.

### Cycle and diamond handling

Unlike `blocked_by:` (`docs/design/standard-library.md` §9), which asserts
its edges form a DAG and treats a cycle as a hard build error, a general
cascade walks an arbitrary mix of link types across arbitrary items — nothing
asserts *that* graph is acyclic, and a `direction="both"` walk in particular
can legitimately reconverge (two paths reaching the same item) without any
edge being wrong. `{{cascade}}` therefore has to degrade gracefully, not
error, and one rule handles both a true cycle and an ordinary diamond:

Each subtree walk keeps a `visited: set[item_id]`, seeded with the root's own
id. Following an edge to a target already in `visited` renders that target
once more, as a terminal leaf, and does not recurse into its own edges again
— annotated `(already shown above)`. A target not yet in `visited` is added
and recursed into normally, up to `depth`. This is the same shape a cycle
takes (A → B → A: B's second edge back to A renders A as a leaf, the walk
stops) and a diamond takes (A → B → D, A → C → D: D renders once expanded
under B, once as a marked leaf under C) — no special-casing needed for
"is this actually a cycle," because bounding on *node*, not *edge*, already
answers both.

### Rendering

A nested `<ul>` — a tree is what this is, and a printed design record is a
stated primary output (this document's own framing, and `document.html`'s
own header already says "the form to print or archive,"
`src/refdes/templates/document.html.j2:13`). A table would need a repeated
depth/parent column and reads far worse across a page break; an indented
list reads correctly both on screen and on paper with no extra column at
all.

The root renders unindented, with no verb label (nothing pointed it here —
it's the anchor): `<ID> — <title>`. Each child renders one level deeper,
labeled with the verb that reached it, matching exactly how `item.html.j2`
already labels its own two panels: an **up**-direction hop (a declared
link) shows `project.link_types[name].label` the same way the Outgoing
panel does (`item.html.j2:133`); a **down**-direction hop (a backlink) shows
the raw inverse name the same way the Incoming panel does
(`item.html.j2:147`) — reusing the exact label convention each direction
already has elsewhere on the site, not inventing a third one for this block.

```html
<ul class="cascade">
  <li>REQ-IO-001 — Connector pinout stability
    <ul>
      <li>Satisfied by DEC-IO-016 — Lock connector pinout for rev B
        <ul>
          <li>Constrained by CON-IO-004 — Pin count budget</li>
        </ul>
      </li>
      <li>Verified by TST-IO-002 — Pinout continuity test</li>
    </ul>
  </li>
</ul>
```

Item ids in the generated markup are bare text, not pre-built links — the
same reasoning as §1's index tables: insertion happens before `_linkify`
(§1), so every id gets the standard hover-preview link for free, with no
duplicated link-building logic inside the block.

**Imports are included when reached**, unlike `index` (§5). An index asks
"what does this project itself declare of type X" and excludes imports on
purpose; a cascade asks "what does the graph reachable from this item look
like," and an edge is an edge regardless of which project authored the item
on the other end — the same posture `docs/design/standard-library.md` §9
already takes for `blocked_by` chains crossing an import boundary ("resolves
the same way a local one does, with no special-casing needed").

### Failure modes

Matching §5's bar:

```
ERROR pages/schematic.md:8 — {{cascade from="REQ-IO-999" direction="down"}}
      — REQ-IO-999 does not exist.

ERROR pages/schematic.md:8 — {{cascade from="REQ-IO-001" direction="sideways"}}
      — unknown direction 'sideways'. cascade accepts: down, up, both.

ERROR pages/schematic.md:8 — {{cascade from="REQ-IO-001" direction="down"
      via="satisfies,implements"}} — unknown link type 'implements'.
      Did you mean 'satisfies'?

ERROR pages/schematic.md:8 — {{cascade from="REQ-IO-001" direction="down"
      depth="0"}} — depth must be a positive integer.
```

An empty result — the root has no edges at all in the requested direction —
is not an error, matching `index`'s empty-state posture (§5): the root still
renders, with one line noting nothing was found, rather than a bare `<ul>`
with a single item and no explanation:

```html
<ul class="cascade">
  <li>REQ-IO-042 — Standalone note
    <p class="cascade-empty">nothing found (direction="down")</p>
  </li>
</ul>
```

### Relationship to the `blocked_by:` cascade report

`docs/design/standard-library.md` §9 specs a *different* feature that walks
the *same shape* — a rooted, bounded, cycle-aware graph walk, one hop at a
time, back to a root. They should stay **two features sharing one walk
primitive, not one mechanism** — trying to collapse them loses real
behavior on both sides:

- The `blocked_by` report is **automatic and always-on**: it appears in
  `refdes audit`, on the blocked item's own page, and inside
  `coverage.html`'s per-item rows, computed on every build whether or not
  any narrative page exists. `{{cascade}}` only renders where an author
  places it.
- The `blocked_by` report is **tightly integrated with coverage** — the
  stale-blocker `info` diagnostic and the aggregate "N requirements
  unsettled because DEC-IO-001 is on_hold" line
  (`docs/design/standard-library.md` §9) are coverage-domain computations, not
  something a page-rendering block's job description covers.
- The `blocked_by` report's cycle handling is **deliberately a hard build
  error**, not a rendered marker — because a `blocked_by` graph is
  specifically asserted to be a DAG (that document's own §9 reasoning), and a cycle in it
  is a real authoring bug, not a legitimate reconvergence the way a mixed
  general cascade's can be. `{{cascade}}`'s graceful `(already shown above)`
  handling (above) is the right behavior for a block that can't assume
  acyclicity from an arbitrary `via=`; it would be the *wrong* behavior for
  `blocked_by`, which specifically wants that cycle to stop the build.

What *should* be shared is the walk itself: seed a visited set with the
root, follow declared-links or backlinks per direction, stop expanding a
revisited node, cap at a depth. `docs/design/standard-library.md` §9's own
walk (root-finding through `blocked_by` edges, path-to-root formatting) is a
specialization of exactly this primitive — direction fixed to `up`, `via`
fixed to `{blocked_by}`, and its cycle policy overridden from "render a
marker" to "hard error." This document owns the general primitive and the
`{{cascade}}` block built on it; `docs/design/standard-library.md` §9 keeps
owning `blocked_by`-specific policy (the stale diagnostic, the coverage
aggregate line, the audit/item-page/coverage.html surfacing) and should, if
this document lands first, be updated to say it reuses this walk rather than
reimplementing cycle detection independently — not done here, since the
brief scopes this document to `docs/design/index-blocks.md` only.

One free consequence worth naming: once `via=` exists, an author can drop
`{{cascade from="DEC-IO-005" direction="up" via="blocked_by"}}` onto a page
for an ad hoc, on-demand rendering of one specific blocker chain. That's a
convenience overlap, not a substitute for that document's §9 dedicated
report — the block
only renders where placed, computes no staleness, and feeds no coverage
warning.

---

## 7. Conventions the family inherits

These are the pieces this design deliberately sets up so a second and third
block don't each reinvent their own version:

- **Envelope**: `{{<name> key="value" ...}}`, alone on its own source line,
  parsed with the existing `key="value"`/`key=bareword` microsyntax
  (`FIGURE_ATTR_RE`). Every future block uses this same envelope — no block
  gets its own delimiter.
- **Parameter naming**: short, lowercase, no punctuation, one obvious
  meaning each — `by`, `type`, `board`. A future block's parameters follow
  the same register; `by` in particular should mean "group by this field"
  everywhere it appears, not something else in a different block.
- **Unknown block name**: not an error, not silently swallowed — if the
  first token inside `{{...}}` doesn't match a name in the fixed dispatch
  table, the whole thing is left as literal text, on the theory that it was
  never meant as a directive (§1). Once the name *does* match, everything
  past that point is validated strictly (§5) — there is no partial-credit
  state where a recognized block silently ignores a bad parameter.
- **"Nothing matched"**: render one visible, unambiguous line
  (`<p class="index-empty">...</p>`) rather than empty output or a build
  failure. Every future block reports its own empty state the same way,
  with its own wording.
- **Local items only**: every block in the family reads `project.local_items`,
  never imported items, without needing a parameter to say so — consistent
  with how every other cross-item view in the tool already treats imports.
- **Documentation**: one new doc, following the shape `docs/checks.md`
  already uses for the `checks:` mechanism — what it's for, its parameters
  in a table, a worked example, and its error messages verbatim. As the
  family grows, each block gets its own section in that same document
  rather than a scattered doc per block.

`{{cascade}}` (§6) is the second member, already fully specified rather than
sketched — it reuses this same envelope, the same "unknown parameter is an
error, unknown name is literal text" split, and its own empty-state
convention, which is the evidence these conventions actually generalise and
not just a design intention. Two more, sketched only to push that a step
further:

- **`{{count by="status" type="requirement"}}`** — same grouping engine as
  `index`, but each group renders as a count instead of a listing: `12
  active, 3 draft, 1 retired` instead of naming every item. Tests that the
  shared grouping/ordering/failure-mode plumbing (§4, §5) generalizes to a
  different rendering, not just a different filter.
- **`{{list type="test" board="power"}}`** — a flat listing of one type,
  optionally board-scoped, with no `by=` at all. Tests that `by` is
  optional *per block* — some blocks group, some just enumerate — without
  needing a fourth "grouping mode" parameter bolted onto `index` itself to
  cover the no-grouping case.

Neither is specified further here; both exist only to show that `by`,
`type`, `board`, the envelope, and the failure-mode conventions above
survive contact with a third and fourth block unchanged.

---

## 8. The non-goal, stated for the docs

Refdes's markdown blocks take **parameters, never expressions.** Every
block in this family — `index`, `cascade`, and whatever joins them —
accepts a small, closed set of named parameters, each with one fixed
meaning, validated against the resolved schema at build time. There is no
comparison operator, no `and`/`or`, no wildcard, and no nesting one block
inside another. A block only ever selects and arranges items that already
exist in the project; it cannot decide that something exists, is true, or
is correct, and it cannot be composed into an expression the tool would
have to parse and evaluate. That is what keeps a generated index or cascade
as auditable as the hand-maintained table or diagram it replaces: anyone who
can read `by="schematic_page" type="decision"` or `from="REQ-IO-001"
direction="down"` already knows exactly what will appear on the page, with
no interpreter and no query language standing in between the source and the
number.

---

## 9. Figure identity, numbering, and cross-references

Not a block — an extension of two mechanisms that already exist: the
`{width=... caption="..."}` image-attribute suffix
(`docs/markdown.md` §"Width and captions") and the `[[...]]` cross-reference
syntax (`EXPLICIT_REF_RE`, `src/refdes/build.py:18`). `docs/markdown.md`
already names the gap plainly: "Figure numbering is not automatic — write
`Figure 3 —` as literal caption text" (`docs/markdown.md:101-102`). That's
fine for a document nobody else refers to by number; it breaks the moment
prose anywhere wants to say "see Figure 3" and mean a specific figure rather
than a string someone typed and now has to keep in sync by hand — the exact
staleness problem §1's `{{index}}` exists to solve, recurring in a different
place.

### Identity: an explicit `id=`, not derived

A figure needs a stable key before it can be numbered or referenced. Two
ways to get one were considered and rejected in favor of an explicit
attribute:

- **Derived from the file path** — fragile twice over: a rename of the
  source image (routine — datasheet revisions, cleaned-up filenames) would
  silently break every existing reference with no diagnostic, and two items
  legitimately using the same leaf filename in different directories
  (`figures/curve.png` under two different item folders) would collide the
  moment paths are flattened into one global key space.
- **Derived from position** (Figure 1, 2, 3 in document order) — this
  *is* the number, not an identity independent of it, and the numbering
  section below is precisely about why the number itself can't be stable
  enough to serve as identity: the same figure gets a different number in
  every rendered document it appears in.

So: an explicit `id=` in the same attribute suffix that already carries
`width=` and `caption=`, parsed by the same `FIGURE_ATTR_RE`
(`src/refdes/build.py:37`) with no new microsyntax:

```markdown
![TPS62913 efficiency vs. load current, half-load point marked](figures/curve.png){id="fig-curve" width=60% caption="Efficiency vs. load current"}
```

`id=` is optional, exactly like `width=` and `caption=` already are — a
figure with no `id=` renders exactly as it does today, numbered nowhere,
referenced by nobody. Nothing about the common case changes.

**Scope: unique across the whole project**, the same posture item ids
already have — a figure can be referenced from any item's prose or any
narrative page, not just the one it's embedded in, so one flat namespace,
checked once, is simpler than a scoping rule an author has to learn (per
item? per page? per document?) before writing a reference. A duplicate is a
build error, naming both locations, matching the tool's existing
"name both sides" posture for collisions
(`docs/design/standard-library.md` §8's preset-collision error is the same
shape):

```
ERROR items/power/dec-001.md:14 [DEC-PWR-001] — figure id 'fig-curve' is
      already used by CMP-PWR-002 (items/power/cmp-002.md:9). Figure ids
      must be unique across the project.
```

### Numbering scope: per rendered document, not per project

This is the crux, so the resolution has to be stated plainly: **there is no
single "Figure 3."** The same figure can appear in up to three different
rendered documents — its owning item's own `item.html.j2` page, the
project-wide `document.html`, and a per-board `document-{board}.html`
(`src/refdes/render.py:628-641`) — and each is a different reading order
with a different set of figures on it. A figure that's the third one on its
own item's page is very unlikely to also be the third one in the full,
multi-item `document.html`. Trying to force one number to survive every
context means either picking one canonical document to be numbering
authority (confusing everywhere else — "Figure 7" alone on a one-figure item
page reads as broken) or refusing to number anywhere but that one document
(defeating half the reason to do this at all, since the printed
`document.html` — "the form to print or archive,"
`src/refdes/templates/document.html.j2:13` — is exactly where the numbers
matter most).

The tool already has a precedent for exactly this shape of problem, and the
resolution here matches it rather than inventing a second policy:
`_anchorize` (`src/refdes/render.py:22-38`) rewrites the *same* cross-item
`href` differently depending which rendered view it appears in — a
multi-page site link becomes an in-document anchor specifically because
"the same reference has to become an anchor... which is exactly what breaks
when you print a page-per-item site." Figure numbering takes the identical
stance: **each rendered document computes its own figure numbers, fresh, in
its own reading order**, independently of every other document that might
also contain the same figure:

- `item.html.j2` numbers only that item's own figures, starting at 1.
- `document.html` numbers every figure across every section, in
  `_document_sections`' own reading order (`src/refdes/render.py:40-68`),
  starting at 1.
- Each `document-{board}.html` numbers only that board's figures, in that
  board's own document ordering, starting at 1.
- A narrative page numbers only its own embedded figures, starting at 1 —
  pages are never combined the way item bodies are, so this case has no
  cross-document complication to resolve.

### Cross-reference syntax: `[[fig:<id>]]`

Reuses the existing `[[...]]` envelope (`EXPLICIT_REF_RE`,
`src/refdes/build.py:18`) rather than inventing a second bracket syntax — one
delimiter, dispatched by a `fig:` prefix, the same way `{{index}}` and
`{{cascade}}` share one envelope dispatched by block name (§7). Today's
captured-id character class (`[A-Za-z0-9\-_]+`) doesn't include `:`; it
widens to `[A-Za-z0-9\-_:]+` to admit the prefix. This is safe with no
ambiguity: item ids are allocated as `PREFIX-BOARD-NNN` and never contain a
colon, so the widened pattern only ever matches the new namespace on real
projects, never an existing item id.

```markdown
See [[fig:fig-curve]] for the efficiency curve at half load.
See [[fig:fig-curve|the efficiency curve above]] instead, with custom text.
```

With no `|label`, `[[fig:fig-curve]]` resolves to `Figure N`, linked to
`#fig-curve`, where `N` is *this rendered document's own* number for that
figure (above) — resolved at the same point `_linkify` already resolves
`[[REQ-PWR-002]]`, reusing the same explicit/bare dispatch, just routed to a
figure lookup instead of an item lookup when the id starts with `fig:`. With
a `|label`, exactly like an item reference, the custom text replaces `Figure
N` as the visible text; the link still points at `#fig-curve`.

**A same-item figure reference always resolves**, in every document that
item's body ever renders into, because an item's own figures are always in
the same document as its own body in every one of the three views above.
**A cross-item figure reference is inherently document-scoped** — it only
resolves in a document that happens to contain both items' bodies at once
(`document.html` or a `document-{board}.html`, never a standalone
`item.html.j2`). This is a real, visible consequence of the per-document
numbering above, not a bug to work around: the natural place for a
cross-item figure reference is a narrative page or `document.html` itself,
and an author who tries it from inside one item's own body, pointing at
another item's figure, finds out exactly where it doesn't work from the
diagnostic below, on the page where it fails.

### Failure modes

Matching §5's bar — name the specific fix:

**Figure id doesn't exist anywhere in the project** (most likely a typo):

```
WARNING items/power/dec-001.md:22 [DEC-PWR-001] — reference to figure 'fig-curv',
        which does not exist. Check the figure's {id="..."} attribute.
```

**Figure id exists, but not in the document currently being rendered** (the
cross-item, wrong-view case above) — same severity and the same
`ref-missing` visual treatment `_linkify` already gives a dangling item
reference, but naming the actual gap instead of a bare "not found":

```
WARNING items/power/dec-001.md:22 [DEC-PWR-001] — reference to figure
        'fig-curve', which exists on CMP-PWR-002 but is not rendered on this
        page — figure references only resolve within the same rendered
        document.
```

Both stay `warning`, matching `_linkify`'s existing severity for a dangling
`[[ITEM-ID]]` — a figure reference going stale is the same class of problem
a stale item reference already is, not a new severity tier.

---

## 10. Content-hashed asset filenames

Deferred at the same time as the rest of the asset pipeline
(`docs/markdown.md` §"Images and other local files") and worth closing now:
`_process_images` (`src/refdes/build.py:451-487`) resolves a local `<img
src>`, registers it in `project.assets`, and rewrites `src` to
`assets/<project-root-relative path>` — the *same* path on every build,
regardless of whether the file's bytes changed. `_copy_project_assets`
(`src/refdes/render.py:389-415`) then copies it into `_site/assets/` with
`shutil.copy2`, verbatim. Editing `figures/curve.png` in place and
rebuilding produces new bytes at the *same* URL — exactly the shape of bug a
browser cache, or worse a CDN in front of a hosted `_site/`, is built to get
wrong: nothing about the URL changed, so nothing tells the cache to refetch.

**Worth fixing, and the tool already has the pattern for it.**
`.refdes/vendor/<sha256><ext>` (`docs/markdown.md:174`) already
content-addresses vendored citation bytes for exactly this reason — this is
extending an idea already proven in the codebase to a second asset class,
not introducing a new one. And the mechanism needed to make a filename
change *safe* — pruning whatever the previous build wrote under the old
name — already exists too: `_prune_stale_output`
(`src/refdes/render.py:418-431`) deletes anything in the manifest-tracked
`written` set from a previous build that the current build didn't
reproduce. A hash-suffixed filename simply falls out of `written` the moment
the source bytes change, and the next build prunes it automatically, with no
new cleanup logic.

**Scope: `<img src>` only, not `site.assets:` directories.**
`docs/markdown.md` already draws the exact boundary this decision needs:
"Only `<img src>` goes through the resolve-and-copy pipeline... an ordinary
`[text](file.pdf)` link to a local file is **not** touched"
(`docs/markdown.md:108-111`). For `<img src>`, refdes owns both ends — it
resolves the source path *and* writes the `src=` attribute that points at
the copy — so appending a hash to the *output* filename is completely
transparent; an author still writes `![alt](figures/curve.png)` exactly as
today, unchanged, and never types the hashed name anywhere. A
`site.assets:`-registered file linked by hand
(`[Full schematic (PDF)](assets/figures/schematic.pdf)`,
`docs/markdown.md:113-125`) is the opposite case: the author's literal
`href` *is* the output path, unrewritten by the tool
(`docs/markdown.md:108-111` again). Hashing that filename would silently
break every hand-typed link with no way for refdes to catch it, since by
that point the href is opaque prose text, not something the tool resolves.
So: hash the pipeline the tool already fully owns; leave untouched the one
it explicitly documents as author-controlled and unrewritten. Extending
hashing to `site.assets:` files later would first require refdes to rewrite
hand-typed local links at all, which it deliberately doesn't do today
(`docs/markdown.md:108-111`) — a separate, larger feature, not a corollary
of this decision.

**Shape:** `assets/figures/curve.<hash>.png` — source directory structure
preserved, hash and extension appended to the leaf filename. `hash` is a
short prefix of the file's sha256, matching the truncation convention
`item.content_hash` already uses (`hashlib.sha256(...).hexdigest()[:16]`,
`src/refdes/build.py:350`) rather than a full 64-character digest bloating
every asset filename.

**Where it's computed:** at `_process_images` time, when the source file is
already being opened to check it resolves
(`os.path.isfile(full_path)`, `src/refdes/build.py:477`) — reading it once
more to hash costs one read on an already-open path, not a new I/O pass.
`project.assets` (today a bare `set[str]` of source-relative paths) becomes
a mapping from source-relative path to its hashed output path, and
`_copy_project_assets` copies from the recorded source to the recorded
hashed destination instead of mirroring the source path verbatim. The same
source image referenced from multiple items or pages hashes once, to the
same output path, for free — the mapping is keyed by source path, so a
shared logo doesn't get copied or hashed twice.

**Default-on, no config flag.** Nothing legitimately hand-constructs the
hashed URL — the tool is the only writer of every `src=` attribute that
points at one — so there's no compatibility hazard a toggle would be
protecting anyone from, and a flag whose only job is "opt out of a pure bug
fix nobody depends on the old behavior for" is exactly the kind of surface
this document's own conventions (§7) argue against adding without a
concrete need.
