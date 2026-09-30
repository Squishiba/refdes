# Workspaces

Boards ([multiple boards](multi-board.md)) group items by hardware. A
**workspace** groups boards one level higher — an ownership boundary, not a
hardware one.

## Why

`items/` is scanned recursively, but board derivation only ever reads *one*
path segment: `items/<board>/`, flat by construction. There is no way to say
"these three boards are one product; these other two are a different one" —
every board sits at the same level, forever.

A workspace is that missing level. It's meant to hold **everything used only
by that workspace** — the seam along which a project would later split.
Drawing that boundary early means extracting a workspace into its own project
is a folder move, not a renumbering.

## Declaring workspaces

```yaml
workspaces:
  platform:
    label: "Shared Platform"
    shared: true       # any workspace may depend on this one
  product-a:
    label: "Product A"
  product-b:
    label: "Product B"
```

| Key | Default | Purpose |
|---|---|---|
| `label` | the key | Display name |
| `shared` | `false` | Other workspaces may link into this one without tripping the cross-workspace lint (below) |
| `path` | the key | Alias for the `items/` path segment, if spelled differently |

`workspaces:` is entirely opt-in, exactly like `boards:` — with no block,
nothing here does anything.

### Workspace names share one namespace with board names

A workspace key and a board key are two different things — one is an ownership
boundary, the other a hardware grouping — but they land in **one filename
namespace**: both are substituted into the same generated report names —
`coverage-<key>.html`, `document-<key>.html`, `log-<key>.html`,
`references-<key>.html`, `summary-<key>.html` are written once per board and
once per workspace (`src/refdes/render.py:1124-1265`, the two loops that name
each file after its registry key) — so one name used for both would leave two
reports fighting for the same file. The collision is therefore refused at
load:

```console
$ refdes check
configuration error: 'power' is declared as both a board and a workspace — boards
and workspaces share one namespace for generated report names (e.g.
coverage-power.html); rename one of them
```

Exit code 2, nothing built. The beat this costs is the ordering: nothing warns
while you write the two blocks, so the error arrives after both are already
in the file. Read your `boards:` block before naming a workspace — and note
that `path:` aliases do **not** dodge this. `path:` renames the `items/`
segment; the namespace that collides is the **key**.

## The two-level layout

```yaml
# refdes-project.yaml
item_layout: workspace
```

`item_layout` is a **fixed choice**, `flat` or `workspace` — not a path
template. A pattern like `layout: "<workspace>/<board>/"` would imply
arbitrary nesting depth this tool isn't willing to promise; two named,
specific layouts is the whole surface:

| `item_layout` | Path shape | Board read from | Workspace read from |
|---|---|---|---|
| `flat` *(default)* | `items/<board>/` | 1st segment | — (override only) |
| `workspace` | `items/<workspace>/<board>/` | 2nd segment | 1st segment |

```
items/
  platform/
    shared/interfaces.yaml       IFC-CAN-001
  product-a/
    board-a/requirements.yaml    REQ-A-PWR-001
  product-b/
    board-b/requirements.yaml    REQ-B-PWR-001
```

A project with no `workspaces:` block and `item_layout: flat` (the default)
behaves **exactly** as it did before this feature existed — that combination
is never a behavior change.

## Overriding the derived value

Same precedence as `board:` — item's own `workspace:`, then the file's
`defaults.workspace`, then the path:

```yaml
items:
  - id: IFC-CAN-001
    workspace: platform   # lives in a folder that predates the registry
```

Unlike the path fallback, the `workspace:` override works under **either**
layout — a project that wants the cross-workspace lint without reorganizing
every folder into `items/<workspace>/<board>/` can tag items by hand instead.
An override naming an unregistered workspace is a build error, the same as an
unregistered `board:`.

## The cross-workspace reference lint

This is the payoff. An **authored** link from one workspace's item into
another workspace's item — one that isn't marked `shared: true` — is flagged:

```
WARNING items/product-b/board-b/decisions.yaml:5 [DEC-B-014] — satisfies
        points at REQ-A-009, in workspace 'product-a', which is not marked
        shared: true -- workspace 'product-b' would gain a hidden dependency
        on it
```

That dependency is exactly what makes a workspace hard to extract later —
Product B's project can't build without Product A's items once this exists,
whether or not anyone meant to create that coupling.

**Exempt:** a link within the same workspace, and a link into any workspace
declared `shared: true` — the platform workspace above is meant to be
depended on by everyone, so links into it never trip the lint.

**Never trips on a derived relationship.** Only `item.links` — what an
author actually typed — is walked, never a computed backlink, coverage, or
any future aggregate view (a parts index spanning workspaces, say). Two
boards in different workspaces happening to use the same MCU is a
coincidence of the bill of materials, not a claimed dependency, and this
lint has no way to see it even in principle.

**Severity is configurable**, in `refdes-project.yaml`:

```yaml
cross_workspace_severity: warning   # error | warning | info -- default warning
```

Default `warning` so adopting workspaces never breaks an existing build; set
it to `error` once a project wants the boundary enforced for real.

**Scope:** local items only, on both ends. An imported item's `workspace`
(if it resolves to anything) describes the *upstream* project's own
structure, not a dependency inside this one — crossing a project boundary is
already `imports:`'s concern ([multiple boards](multi-board.md#separate-projects-with-imports)),
which is a different, stricter kind of dependency than this lint tracks.

## Drift

`.refdes/boards.yaml` — the same file board drift uses — carries a second
section. In an adopted project both sections use the item's surrogate key:

```yaml
boards:
  k7f3m2q9x4a:
    id: DEC-A-001
    board: board-a
workspaces:
  k7f3m2q9x4a:
    id: DEC-A-001
    workspace: product-a
```

Legacy `DEC-A-001: product-a` scalars remain readable, and non-adopted
projects keep writing that legacy shape. Moving a file across a workspace
boundary warns exactly like a board move does, including when its display id
is renamed in the same change. `refdes build --accept-board-move` accepts
both kinds together — there is no separate `--accept-workspace-move` flag,
since they share one manifest and the same "moving this is an ordinary thing
to do on purpose" posture. `refdes audit` lists workspace moves in their own
section, next to board moves. A project that has never declared `workspaces:`
never gets a `workspaces:` section written into the manifest at all.

## Rendered pages and nav

Each registered workspace gets its own scoped `document-<workspace>.html`,
`coverage-<workspace>.html`, `log-<workspace>.html`, `references-<workspace>.html`,
and `summary-<workspace>.html`, exactly like a board does. The sidebar nests
each board's group inside its workspace's group, derived from which boards
actually have items resolving into that workspace — a board with no items
yet (or items outside any workspace) falls back to a top-level group, same
as it would with no `workspaces:` registry at all.

Tag a hand-written overview page into a workspace's group the same way a
page joins a board's:

```yaml
---
title: Product A overview
workspace: product-a
---
```

## Reviewing one workspace

```bash
refdes check --workspace product-a
refdes ls --workspace product-a
```

`ls` takes the flag for the same reason: "what's in product-a?" is the first
question a workspace invites, and the listing command could previously ask
about a board, a type, a file or a tag — but not a workspace, even though
`index --compact` had been exporting one per item all along.

Same report-filter posture as `--board`, and combinable with it: the whole
project still parses and every link still resolves — a decision in one
workspace that (legitimately) satisfies a shared requirement still checks
correctly — only what gets *printed* is narrowed to that workspace's own
items.
