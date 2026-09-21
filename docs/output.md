# Output formats

`refdes build` writes everything into `site.out` (default `_site/`).

## The site

| File | Contents |
|---|---|
| `index.html` | Counts, failing checks, outstanding work, tables per type, diagnostics |
| `summary.html` | The whole project at a glance: margins, every computed value, gaps |
| `coverage.html` | The full [coverage](coverage.md) table, least-covered first |
| `log.html` | The [design log](design-log.md) timeline, oldest first — log entries are sorted by their `date:` field parsed using the project's `date_format:` (default `YYYY-MM-DD`) |
| `references.html` | Every [citation](markdown.md#citing-a-datasheet) in the project, grouped by path |
| `parts.html` | Every [part number](parts.md), exact-string indexed, with where-used backlinks |
| `document.html` | Every item in one page, in reading order — the printable record |
| `tree.html` | Every item in one view, filed by workspace, board, `part_of` group — see [the project tree](#the-project-tree) |
| `vocabulary.html` | Every term the project's schema resolves to, with definitions — see [the vocabulary page](#the-vocabulary-page) |
| `<id>.html` | One page per item, lowercased ID (`req-pwr-002.html`) |
| `items.json` | The machine-readable export |
| `assets/` | The stylesheet and script, plus every local image, `site.assets:` directory, and kept citation copy your project references — see [images and other local files](markdown.md#images-and-other-local-files) |
| `assets/theme.css` | Generated only when the project sets `site.theme:` overrides or `site.tokens:` — the token overrides, and nothing else. See [theming](#theming) |

## Theming

The site's look is a set of design tokens declared on `:root` in
`assets/style.css`: colours (`--bg`, `--fg`, `--accent`, …), type (`--sans`,
`--text-base`, `--weight-semibold`), spacing (`--space-4`) and radii
(`--radius-md`). A theme is two flat lists of `--token: value` pairs — one
palette for light mode, one for dark — configured under `site:`. There is no
theme file format, no selector, and no remote theme, so a theme cannot change
layout, hide a section, or fetch anything:

```yaml
site:
  theme: paper
  tokens:
    --accent: "#b3541e"      # both palettes
    light:
      --bg: "#fffdf7"        # light mode only
    dark:
      --bg: "#17140f"        # dark mode only
```

`site.theme:` selects a built-in — `default`, `high-contrast`, `paper`, or
`slate`, each documented with its token tables on the [themes](themes.md)
page — and `refdes build` merges the project's `site.tokens:` over it and
emits the result as `assets/theme.css`, linked after `assets/style.css` on
every page. A bare `--token` pair applies to both palettes; a `light:` or
`dark:` heading targets one. The generated file redefines tokens and nothing
else, and it is tracked in `.refdes-manifest.json` like any other output, so
removing the theme removes the file. With no theme configured no file is
written and no `<link>` is emitted: an un-themed build is byte-for-byte what
it was before theming existed.

Validation is strict because CSS is not. An unknown theme name or an unknown
token name is a build error — with a *Did you mean* hint — since a mistyped
custom property is otherwise "invalid at computed-value time", which renders as
*unset* and leaves the site half-themed with no diagnostic anywhere. A token
value must be one plain CSS value: `;`, `{`, `}`, `<`, `@import`, `url(`, a
comment opener or an escape is refused, which is what keeps a value from
turning into a rule.

`--good`, `--bad`, `--warn` and `--claim` are verdict colours, not decorative
ones, so reassigning them runs the contrast checks: every semantic pair
(foreground, muted, accent and each verdict colour against `--bg` and
`--panel`) must clear a 4.5:1 WCAG AA minimum, and `--bad` must stay
distinguishable from `--good` — a 90-degree hue separation or 4.5:1 between
them, so a colour-blind reader can tell a fail from a pass. A failing pair is a
**warning** naming the pair, the two values and the measured ratio; the build
still produces the site, because the threshold is a floor and not a law.
Values the checker cannot parse — a named colour, `rgb()`, another `var()` —
are skipped rather than guessed at. The built-in themes are held to the same
checks with no warning allowed: a built-in palette that fails is a test
failure.

Dark mode follows the reader's OS preference, and a light-mode override no
longer bleeds into it: when the two palettes disagree, the generated stylesheet
re-asserts the effective dark palette inside the dark blocks. A host page that
wants to pin one mode regardless of the OS sets `data-theme="light"` or
`data-theme="dark"` on `<html>`; matching attribute blocks are emitted for
exactly that.

Static files. No server, no build step for the reader, no network calls. Hover
previews are inlined at build time; with JavaScript disabled every reference is
still a working link.

### Per-board pages

A project with a `boards:` registry additionally gets `document-<board>.html`,
`coverage-<board>.html`, `log-<board>.html`, `summary-<board>.html`,
`references-<board>.html`, and `parts-<board>.html` for each registered
board, scoped to that board's own items — everything above unaffected. See
[multiple boards](multi-board.md). With no `boards:` registry, none of these
are written.

### Per-workspace pages

The same six pages, `-<workspace>` instead of `-<board>`, for each
registered [workspace](workspaces.md) — `document-<workspace>.html`,
`coverage-<workspace>.html`, `log-<workspace>.html`,
`summary-<workspace>.html`, `references-<workspace>.html`, and
`parts-<workspace>.html`, scoped to that workspace's own items. A board and
workspace key never collide (schema.py validates this at load), so the two
sets of pages coexist without fighting over a filename. With no
`workspaces:` registry, none of these are written.

Serve it locally with:

```bash
python -m http.server -d _site 8000
```

## The summary

`summary.html` is the design-review page. `index.html` tells you what exists;
`summary.html` tells you what to worry about.

**Margins.** Every evaluated check, sorted by worst-case slack against its limit,
tightest first. Pass and fail is a blunt instrument — a design that clears a thermal
limit by 3% and one that clears it by 200% both read as "pass", and only one of them
survives a tolerance stack-up or a hot day. Margin is measured relative to the limit,
so it is comparable across unrelated quantities:

| Limit | Value | Margin |
|---|---|---|
| `<= 0.15 W/in^2` | `0.10 W/in^2` | +33.3% |
| `<= 0.15 W/in^2` | `0.2366 W/in^2` | −57.7% |
| `>= 0.90` | `0.93` | +3.3% |
| `9 V .. 36 V` | `35 V` | +3.7% |

Ranges measure to the nearer edge, since that is what fails first.

Three cases show `—` rather than a fabricated number: an `==` limit (it is met
or it is not, with no notion of "how close"), a limit of zero (nothing to take
a fraction of), and a one-sided comparison against an **offset temperature
unit** — `<= 85 degC`. A fraction of a `degC` reading depends entirely on where
you put zero: 45 °C of slack under an 85 °C limit is 53% on the Celsius scale
and 13% in kelvin, so there is no honest number to print. The check itself is
unaffected — comparing two temperatures is perfectly well-defined — and a limit
written on an absolute scale (`<= 350 K`), or as a range (`0 degC .. 60 degC`,
which measures against its own span), still gets a real margin.

A negative margin always means the check failed. The converse is *almost*
always true: a margin of exactly `0` means the worst case landed precisely on
the limit, which `<=`/`>=` pass and `<`/`>` fail.

Margins are in `items.json` too, as `checks[].margin`, a fraction rather than a
percentage.

**Computed values.** Every value every calc block produces, in one table. If a number
in the design is wrong, it is on this page.

**Not linked to anything.** Items with no links in either direction. A bound that
something is *checked against* counts as traced even though a check creates no link
edge, so it will not appear here. Being listed is not an error — a standalone
component is legitimate — but it is where traceability quietly stops.

## The full record

`document.html` is a separate render of the same model: every item as a section on
one page, with a table of contents, grouped by type in schema order and log entries
by date. Cross-references are rewritten from `href="con-thm-001.html"` to
`href="#con-thm-001"`, so they stay live within the document.

This is the form to print or archive. The per-item site is for navigating; this is
for reading cover to cover, and it is what a browser's Print-to-PDF should be
pointed at. A print stylesheet hides the navigation and avoids breaking items
across pages.

It is also the intended input for real PDF generation later — the anchor rewriting
and linear ordering are the parts that would otherwise break.

## The project tree

`tree.html` is the whole project in one view: every item, filed by the
containment spine — workspace, then board, then `part_of` group, then item.
It answers "what is in this project, grouped how, and what is floating"
— orientation, not a report; coverage and trace questions stay with
`coverage.html` and `{{cascade}}`.

- **Every item appears exactly once, expanded, and never missing from
  its own board.** The primary home of an item that has a board is that
  board: directly under it when the item has no group, or inside a group
  node when one of its groups shares the board. When all of a boarded
  item's groups live elsewhere, a node for its first group by id appears
  inside the board branch holding that board's members, and the group
  itself expands once, under its own board or under `Project-wide`. A
  group node may therefore appear in several board branches, each showing
  only that board's members. Board-less items keep the old rule: first
  group by id, else `Project-wide`. Every other group lists the item as a
  reference leaf linking back to where it is expanded — the rule
  `{{cascade}}` uses for revisited nodes. The choice is id-based, so it
  is the same on every build.
- **Nothing is silently dropped.** Items with no board and no group —
  shared components, projects that have never used `part_of` — land in a
  visible **Project-wide** bucket, rendered last with a count. Two counts
  hold mechanically on every build: expanded nodes equal the project's
  item count, and every boarded item appears in its board's branch,
  expanded or as a reference.
- **Collapse is plain `<details>`,** opened to depth two (workspaces and
  boards open, groups collapsed to counts). No JavaScript is involved;
  every reference is still a working link with scripting off, and the
  print stylesheet expands the whole tree so nothing hides on paper.

- **The same forest, scoped.** `tree-<board>.html` and
  `tree-<workspace>.html` show one board's or one workspace's items under
  exactly the rules above, and appear in the sidebar of that scope beside
  Summary and Coverage. A board's tree holds the items it displays —
  owned plus the members of its `includes:` groups — so nothing on the
  page is missing from it; those shared members hang under a node for the
  group that shares them, marked **shared, via GRP-…**, and stay counted
  by their own board everywhere numbers are produced — on this page too:
  the board node counts what it owns, shared members counted apart
  ("1 own, 2 shared"). Group nodes keep their plain counts. A scope with
  nothing in it gets no page. The invariant becomes per-scope: expanded
  nodes equal the items that scope displays.

The same forest is also a block: `{{tree}}` in a page, optionally
`board=`, `workspace=` or `depth=`. See [blocks](blocks.md).

## The vocabulary page

`vocabulary.html` is the project's vocabulary in one place: every **item
type**, **link verb**, **set**, and **engine-reserved key** the
resolved schema knows about, each with its definition, its scope, where it
points and what points at it, and its fields.

- **It is generated from the resolved schema, not from any one file.**
  Base standard, then presets, then the project's own overlay — so the page
  says what the build actually means. A preset that is not enabled is not on
  the page; a type the project adds of its own is, with the project's own
  `doc:` for it.
- **A term with no definition says so.** `doc:` is optional on project
  terms, so an undefined one renders as "No definition" rather than being
  dropped: the page is complete over the schema, and completeness is the
  point. Engine-reserved keys (`id`, `type`, `key`, `body`, `history`, …)
  are not author-declared at all, so their definitions live in
  `refdes/vocabulary.py` — one place, cited by the page.
- **Direction is computed, not restated.** "Pointed at by" for a type comes
  from every declaration that may target it, including a verb declared under
  its **inverse** name (`decision: {links: {recorded_by: [log]}}` is
  `log --records--> decision`), and a verb with an empty target list says it
  points at any type rather than showing nothing.
- **It opens with the graph.** Item types as nodes and every declared link
  verb as a labelled arrow to each type it may target — `group` included,
  `part_of` included, and a verb with no declared target list drawn as one
  arrow to a single *any type* node. The layout is layered and computed from
  the schema, so the same schema draws the same bytes every time; each node
  is an anchor into its entry below, and the colours are the site's own CSS
  variables, so the picture follows dark mode and prints. It is inline SVG
  with no script in it, and `refdes schema --graph` writes the identical
  file.
- **It is static and printable.** Plain headings, definition lists, and
  tables: no script of its own, no handler attributes, every anchor a plain
  `id` — the page works offline, with JavaScript disabled, and on paper.

Like the tree, the vocabulary page is project-wide only: a schema does not
narrow to a board, so there is one page and no `vocabulary-<board>.html`.

## Site navigation

Every page carries the same **sidebar**, generated from the project's own
structure — there is nothing to hand-maintain and no `nav:` tree to write.

- Narrative [pages](pages.md) that belong to no board or workspace come
  first, then the project-wide generated reports.
- Once a `boards:` or `workspaces:` registry exists, each one becomes a
  collapsible group holding its own pages and its own scoped reports, with
  boards nesting inside the workspace their items resolve into. A group
  renders already open when the page you are reading lives inside it.
- A scope with no items of its own gets no group and no report pages — a
  board can be registered before anything is in it. Within a populated
  scope, only the reports that have something to show are written and
  linked: no `log-<board>.html` without log entries, no
  `references-<board>.html` without citations.
- The link to the current page is marked `aria-current="page"`, so screen
  readers and the stylesheet agree on where you are.
- Below a narrow viewport the whole tree collapses behind a single
  "☰ Navigation" line, so page content starts at the top of a phone screen
  instead of several hundred pixels down. It is a CSS-only toggle — no
  JavaScript is involved, and it works with JavaScript disabled.

A page with more than two `##` headings additionally gets an on-page contents
list built from those headings. Where JavaScript is available, it highlights
the section currently in view as you scroll; without it, it stays an ordinary
list of working anchors.

The print stylesheet hides all of this.

## An item page

- Type badge, ID, check state, and — where relevant — `imported` or `append-only`
- Coverage strip for requirements and bounds
- Field table, with each field's `on_change` mode shown
- Rendered body, with calc blocks as evaluated tables and IDs autolinked
- Options-considered panel for decisions, chosen and rejected
- Checks table with pass/fail and the worst-case detail
- Citations table for any `citations`-typed field — pinned/kept state, rev, page, part number. The page is the authored `page:`, or the page a `section:` resolved to at fetch time
- Traceability: outgoing and incoming links
- Provenance: source `file:line`, and the content hash

## `items.json`

The interchange format. **Anything downstream should read this, not the HTML.**

Four keys follow the registries they come from, and are absent entirely
without them rather than present and empty: top-level `boards` and a
per-item `board` for a [`boards:`](multi-board.md) registry, top-level
`workspaces` and a per-item `workspace` for a
[`workspaces:`](workspaces.md) one. Everything else below is always present.

```json
{
  "title": "Example Board — Design Reference",
  "version": "2026.3",
  "coverage": {
    "REQ-PWR-003": {
      "stage": "satisfied",
      "addressed_by": ["LOG-A-003", "LOG-A-004", "LOG-A-006"],
      "claimed_by": [],
      "satisfied_by": ["DEC-PWR-001"],
      "verified_by": []
    }
  },
  "boards": {
    "board-a": { "label": "Board A", "token": "", "path": "" }
  },
  "types": {
    "requirement": {
      "label": "Requirement",
      "prefix": "REQ",
      "fields": { "owner": { "type": "person", "on_change": "log" } }
    }
  },
  "items": [
    {
      "id": "DEC-PWR-001",
      "type": "decision",
      "title": "3V3 rail regulator topology",
      "fields": { "status": "accepted", "options": [ ... ] },
      "citations": {
        "citations": [
          { "path": "https://www.ti.com/lit/ds/symlink/tps62913.pdf",
            "state": "ok", "pinned": true, "kept_copy": false,
            "sha256": "9f2c...", "fetched": "2026-03-01T12:00:00Z",
            "local_path": "", "section_page": "14", "detail": "" }
        ]
      },
      "links": { "satisfies": ["REQ-PWR-002"], "constrained_by": ["BND-THM-001"] },
      "backlinks": { "recorded_by": ["LOG-A-004"] },
      "content_hash": "673e6ba11269f350",
      "external": false,
      "origin": "",
      "board": "board-a",
      "former_ids": [],
      "source": { "file": "items/decisions/dec-pwr-001-regulator.md", "line": 2 },
      "calcs": [
        { "name": "P_diss", "expression": "P_out * (1/eff - 1)",
          "result": "0.2981 W", "bounds": "", "error": null }
      ],
      "checks": [
        { "value": "P_dens", "against": "BND-THM-001", "ok": false,
          "actual": "0.2366 W/in²", "limit": "<= 0.15 W/in^2",
          "detail": "worst case 0.2366 W/in² vs <= 0.15 W/in^2",
          "margin": -0.5773 }
      ]
    }
  ],
  "diagnostics": [
    { "level": "error", "message": "...", "file": "...", "line": 2,
      "item": "DEC-PWR-001" }
  ]
}
```

### Field notes

| Field | Notes |
|---|---|
| `version` | From `site.version`; what downstream imports check |
| `coverage` | Local items only; imported items are excluded |
| `content_hash` | Over `invalidate` fields only — see [change tracking](change-tracking.md) |
| `external` / `origin` | True and named for imported items |
| `source` | `file:line` of the item's definition; enough for go-to-definition |
| `calcs[].bounds` | Empty unless the value carries a tolerance |
| `checks[].ok` | `true`, `false`, or `null` when it could not be evaluated |
| `boards` / `items[].board` | Only present when the project declares a `boards:` registry |
| `types[].fields[].type` | The field's declared type (`text`, `citations`, ...) — how a consumer finds "which field is my citations field" without being told out of band |
| `items[].citations` | Resolved provenance, keyed by field name — local items only; empty `{}` for items with no `citations:`-typed field |
| `citations[].section_page` | The page a `section:` resolved to, recorded by `refdes fetch` and read straight out of the lockfile — builds never open a PDF. Empty when the citation cites no section, or the section was never resolved, or it was resolved against bytes other than the ones now pinned (either of which `build` warns about); an authored `page:` still wins wherever both exist |

`items[].fields` is authored intent only — for a `citations:`-typed field, each
entry is just what was written in the item (`path`, `rev`, `page`, `section`,
`part_number`, `keep_copy:`, `id`). What it *resolved to* is a separate, parallel
structure,
`items[].citations`, keyed by field name and ordered to match `fields[fname]`:

```json
"citations": {
  "citations": [
    { "path": "...", "state": "ok", "pinned": true, "kept_copy": false,
      "sha256": "9f2c...", "fetched": "2026-03-01T12:00:00Z",
      "local_path": "", "section_page": "14", "detail": "" }
  ]
}
```

They're kept apart because they change for different reasons: `fields` changes
when someone edits the item; `citations` changes when someone runs `refdes
fetch`, independent of the item's content hash. See
[citations.py](../src/refdes/citations.py) for why that separation exists at
the model level, and [citing a datasheet](markdown.md#citing-a-datasheet) for
the authoring side.

Every entry always has the same keys, so "not yet pinned" and "pinned but not
kept" are each an explicit `state`, not something inferred from an absent
key:

| `state` | Meaning |
|---|---|
| `"ok"` | Resolved — hash on file, and kept locally if `keep_copy: true` was declared |
| `"unpinned"` | No lockfile entry yet — `refdes fetch` has not run for this path |
| `"cache_missing"` | Pinned and kept, but the local blob is gone |
| `"hash_mismatch"` | Kept blob's hash no longer matches the pinned sha256 (always an error), or a cited local file changed since it was pinned (warning, error with `--require-citations`) |
| `"missing"` | A cited local file does not exist (always an error) |
| `"invalid"` | The `path:` itself is refused (escapes the project, drive letter, backslash, …) — validation already reported it with `file:line`; the citation is skipped, not resolved |

`pinned` is `state != "unpinned"` — the one field to check "is this dependency
tree fully pinned for a release" without enumerating `state` values yourself.
`kept_copy` and `sha256` distinguish hash-only pins (`kept_copy: false`, `sha256`
set) from kept ones (`kept_copy: true`) — keeping a copy is opt-in per citation,
so a fully-pinned project can still be `kept_copy: false` throughout.

### What it is good for

- Feeding a dashboard, burndown, or status report
- Gating CI on coverage or failing checks
- Syncing to an issue tracker
- **Being imported by another project** — see [multiple boards](multi-board.md)
- Editor tooling: IDs, titles, and source locations are all here

Because it carries `source`, `content_hash`, and per-item calc results, it is a
complete index of the project — which is why it is the right thing to build
tooling against.
