# Refdes documentation

Reference documentation for hardware design decisions. Typed, linked items with
units-aware math that is evaluated and checked against your constraints at build
time.

## Start here

1. **[Getting started](getting-started.md)** — build a working project from an empty
   folder in about ten minutes.
2. **[Concepts](concepts.md)** — the object model, and the three notions of "done"
   the whole tool is organised around.

## Guides

| Guide | Covers |
|---|---|
| [The standard library](standard-library.md) | The bundled types and links every project starts with, and how to override or extend them |
| [Authoring items](authoring.md) | The two file formats, fields, bodies, when to use which |
| [Pages](pages.md) | Narrative markdown alongside your items — and pages-only sites |
| [Markdown reference](markdown.md) | Every formatting feature that works in an item body |
| [Generated blocks](blocks.md) | `{{index}}` and `{{cascade}}` on narrative pages, and the parameters-not-expressions non-goal |
| [IDs](ids.md) | Allocation, prefixes, why numbers are never reused |
| [Links and traceability](links.md) | Link types, back-links, cross-references, hover previews |
| [Math](math.md) | Calc blocks, units, tolerances, brackets, unit assertions |
| [Checks](checks.md) | Limits, worst-case evaluation, failing the build |
| [The design log](design-log.md) | Append-only entries, amendments, sealing |
| [Coverage](coverage.md) | Open → addressed → satisfied → verified |
| [Change tracking](change-tracking.md) | `on_change`, content hashes, auditing suppression |
| [Multiple boards](multi-board.md) | Folders, separate projects, imports, version pinning |
| [Workspaces](workspaces.md) | Grouping boards by product, the two-level layout, the cross-workspace lint |
| [Project lifecycle](lifecycle.md) | draft → `revision` → `release`, the readiness gate, baselines, the diff |
| [Parts](parts.md) | The parts page, exact-string indexing, `equivalent`/`alternate` |

## Reference

| Reference | Covers |
|---|---|
| [Schema reference](schema-reference.md) | Every key in `refdes.yaml` |
| [CLI reference](cli-reference.md) | Every command and flag |
| [Output formats](output.md) | The generated site and `items.json` |
| [Troubleshooting](troubleshooting.md) | Error messages and what to do about them |

## The one-paragraph version

You write requirements, constraints, decisions, tests, and log entries as small
files with YAML front-matter. Each gets a stable ID and typed links to the others.
Decisions can contain `calc` blocks whose arithmetic carries real units and
tolerances, and can declare `checks` against a constraint's limit. `refdes build`
validates everything, evaluates the math, verifies the checks at the worst-case
tolerance bound, and renders a static HTML site plus a machine-readable
`items.json`. When someone tightens a constraint, the build tells you which
decisions just stopped being true.
