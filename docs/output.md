# Output formats

`refdes build` writes everything into `site.out` (default `_site/`).

## The site

| File | Contents |
|---|---|
| `index.html` | Counts, failing checks, outstanding work, tables per type, diagnostics |
| `summary.html` | The whole project at a glance: margins, every computed value, gaps |
| `coverage.html` | The full [coverage](coverage.md) table, least-covered first |
| `log.html` | The [design log](design-log.md) timeline, oldest first |
| `references.html` | Every [citation](markdown.md#citing-a-datasheet) in the project, grouped by url |
| `parts.html` | Every [part number](parts.md), exact-string indexed, with where-used backlinks |
| `document.html` | Every item in one page, in reading order — the printable record |
| `<id>.html` | One page per item, lowercased ID (`req-pwr-002.html`) |
| `items.json` | The machine-readable export |
| `assets/` | The stylesheet and script, plus every local image, `site.assets:` directory, and vendored citation your project references — see [images and other local files](markdown.md#images-and-other-local-files) |

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

Ranges measure to the nearer edge, since that is what fails first. An `==` limit has
no margin — it is met or it is not — and neither does a limit of zero, so both show
`—` rather than a fabricated number. The sign always agrees with pass/fail.

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

## Site navigation

Every page carries the same **sidebar**, generated from the project's own
structure — there is nothing to hand-maintain and no `nav:` tree to write.

- Narrative [pages](pages.md) that belong to no board or workspace come
  first, then the project-wide generated reports.
- Once a `boards:` or `workspaces:` registry exists, each one becomes a
  collapsible group holding its own pages and its own scoped reports, with
  boards nesting inside the workspace their items resolve into. A group
  renders already open when the page you are reading lives inside it.
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
- Citations table for any `citations`-typed field — pinned/vendored state, rev, page, part number
- Traceability: outgoing and incoming links
- Provenance: source `file:line`, and the content hash

## `items.json`

The interchange format. **Anything downstream should read this, not the HTML.**

```json
{
  "title": "Example Board — Design Reference",
  "version": "2026.3",
  "coverage": {
    "REQ-PWR-003": {
      "stage": "satisfied",
      "addressed_by": ["LOG-A-003", "LOG-A-004", "LOG-A-006"],
      "satisfied_by": ["DEC-PWR-001"],
      "verified_by": []
    }
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
        "datasheets": [
          { "url": "https://www.ti.com/lit/ds/symlink/tps62913.pdf",
            "state": "ok", "pinned": true, "vendored": false,
            "sha256": "9f2c...", "fetched": "2026-03-01T12:00:00Z",
            "local_path": "", "detail": "" }
        ]
      },
      "links": { "satisfies": ["REQ-PWR-002"], "constrained_by": ["BND-THM-001"] },
      "backlinks": { "recorded_by": ["LOG-A-004"] },
      "content_hash": "673e6ba11269f350",
      "external": false,
      "origin": "",
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

`items[].fields` is authored intent only — for a `citations:`-typed field, each
entry is just what was written in the item (`url`, `rev`, `page`, `part_number`,
`vendor:`). What it *resolved to* is a separate, parallel structure,
`items[].citations`, keyed by field name and ordered to match `fields[fname]`:

```json
"citations": {
  "datasheets": [
    { "url": "...", "state": "ok", "pinned": true, "vendored": false,
      "sha256": "9f2c...", "fetched": "2026-03-01T12:00:00Z",
      "local_path": "", "detail": "" }
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
vendored" are each an explicit `state`, not something inferred from an absent
key:

| `state` | Meaning |
|---|---|
| `"ok"` | Resolved — hash on file, and vendored locally if `vendor: true` was declared |
| `"unpinned"` | No lockfile entry yet — `refdes fetch` has not run for this url |
| `"cache_missing"` | Pinned and vendored, but the local blob is gone |
| `"hash_mismatch"` | Vendored blob's hash no longer matches the pinned sha256 (always an error) |

`pinned` is `state != "unpinned"` — the one field to check "is this dependency
tree fully pinned for a release" without enumerating `state` values yourself.
`vendored` and `sha256` distinguish hash-only pins (`vendored: false`, `sha256`
set) from vendored ones (`vendored: true`) — vendoring is opt-in per citation,
so a fully-pinned project can still be `vendored: false` throughout.

### What it is good for

- Feeding a dashboard, burndown, or status report
- Gating CI on coverage or failing checks
- Syncing to an issue tracker
- **Being imported by another project** — see [multiple boards](multi-board.md)
- Editor tooling: IDs, titles, and source locations are all here

Because it carries `source`, `content_hash`, and per-item calc results, it is a
complete index of the project — which is why it is the right thing to build
tooling against.
