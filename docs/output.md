# Output formats

`refdes build` writes everything into `site.out` (default `_site/`).

## The site

| File | Contents |
|---|---|
| `index.html` | Counts, failing checks, outstanding work, tables per type, diagnostics |
| `summary.html` | The whole project at a glance: margins, every computed value, gaps |
| `coverage.html` | The full [coverage](coverage.md) table, least-covered first |
| `log.html` | The [design log](design-log.md) timeline, oldest first |
| `document.html` | Every item in one page, in reading order — the printable record |
| `<id>.html` | One page per item, lowercased ID (`req-pwr-002.html`) |
| `items.json` | The machine-readable export |
| `assets/` | One stylesheet, one script |

Static files. No server, no build step for the reader, no network calls. Hover
previews are inlined at build time; with JavaScript disabled every reference is
still a working link.

### Per-board pages

A project with a `boards:` registry additionally gets `document-<board>.html`,
`coverage-<board>.html`, `log-<board>.html`, and `summary-<board>.html` for each
registered board, scoped to that board's own items — everything above unaffected.
See [multiple boards](multi-board.md). With no `boards:` registry, none of these
are written.

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

**Not linked to anything.** Items with no links in either direction. A constraint that
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

## An item page

- Type badge, ID, check state, and — where relevant — `imported` or `append-only`
- Coverage strip for requirements and constraints
- Field table, with each field's `on_change` mode shown
- Rendered body, with calc blocks as evaluated tables and IDs autolinked
- Options-considered panel for decisions, chosen and rejected
- Checks table with pass/fail and the worst-case detail
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
      "links": { "satisfies": ["REQ-PWR-002"], "constrains": ["CON-THM-001"] },
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
        { "value": "P_dens", "against": "CON-THM-001", "ok": false,
          "actual": "0.2366 W/in²", "limit": "<= 0.15 W/in^2",
          "detail": "worst case 0.2366 W/in² vs <= 0.15 W/in^2" }
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

### What it is good for

- Feeding a dashboard, burndown, or status report
- Gating CI on coverage or failing checks
- Syncing to an issue tracker
- **Being imported by another project** — see [multiple boards](multi-board.md)
- Editor tooling: IDs, titles, and source locations are all here

Because it carries `source`, `content_hash`, and per-item calc results, it is a
complete index of the project — which is why it is the right thing to build
tooling against.
