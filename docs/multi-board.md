# Multiple boards

Two approaches. Start with the first; move to the second when you have a concrete
reason.

## One project, folders per board

Everything under `items/` is scanned recursively, so a board family works with no
extra machinery:

```
items/
  shared/interfaces.yaml     IFC-CAN-001, IFC-PWR-002
  board-a/requirements.yaml  REQ-A-PWR-001
  board-a/decisions/...
  board-b/requirements.yaml  REQ-B-PWR-001
```

Give each board its own prefix via `defaults.prefix`. Links, checks, back-links,
coverage, and previews all work across folders. A shared constraint checked by two
boards shows both in its incoming links:

```
IFC-CAN-001 backlinks: {'constrained_by': ['DEC-A-001', 'DEC-B-001']}
```

Tighten that shared limit and each board's own arithmetic is re-checked against it.

### Naming the boards

None of the above needs a `boards:` block — folders are just organisation until you
register them. Once you want board-scoped pages, or a warning when a file lands in
the wrong folder, add one:

```yaml
boards:
  board-a:
    label: "Board A"
    token: A          # optional; checked against item id prefixes
  board-b:
    label: "Board B"
    token: B
    path: brd-b        # optional; use when the folder is spelled differently
```

A board is the first path segment under `items/`, matched against this registry —
`items/board-a/requirements.yaml` is on `board-a`. A segment that is not registered
(`shared/` above) gets no board; that is not an error, since shared items
legitimately belong to none.

`boards:` is entirely opt-in. **With no `boards:` block, nothing here does
anything** — every item's board stays unset and the site is unaffected. Adding the
block later does not change any ID.

Two boards mapping to the same `items/` path segment — whether from a repeated
`path:` or a `path:` that collides with another board's key — is a hard error at
project-load time, not a silent overwrite. It fails before any item is even
parsed:

```
configuration error: boards.board-b and boards.board-a both map to
                      items/board-a/ — path segments must be unique
```

Override the path for one item with `board:`, the same way `prefix:` overrides a
file's default prefix:

```yaml
items:
  - id: IFC-CAN-001
    board: board-a   # this one lives in shared/ but is board-a's concern
    ...
```

Precedence is the item's own `board:`, then the file's `defaults.board`, then the
path. An override must name a registered board; a typo is a build error, not a
silent no-op.

**IDs stay independent of boards.** Nothing here changes an ID's prefix
automatically. If a board declares `token:`, the build warns when an item's own id
prefix does not contain it — a lint, not a rename:

```
WARNING items/board-b/requirements.yaml:9 [REQ-PWR-004] — item is on board
        'board-b' (token 'B'), but its id prefix 'REQ-PWR' does not contain that
        token
```

**Per-board pages.** Each registered board gets its own scoped
`document-<board>.html`, `coverage-<board>.html`, `log-<board>.html`, and
`summary-<board>.html`, alongside the unchanged project-wide versions. Handing
`document-board-a.html` to Board A's team shows only their items. The nav bar
gets a group per board linking to that set automatically — see
[pages](pages.md#grouping-a-page-under-a-board) for tagging a hand-written
overview page into the same group instead of hand-linking it.

**Reviewing one board.** `refdes check --board board-a` still parses and
resolves the whole project — a decision on one board that satisfies a
requirement on another still checks correctly — it just only *reports*
board-a's own diagnostics, so a team can review their own board without
someone else's unrelated warning in the way. See [CLI reference](cli-reference.md).

**Seals are per board too.** An append-only [log entry](design-log.md)'s seal
lives in `.refdes/log-seal-<board>.yaml` once it resolves onto a board — items
with no board keep using `.refdes/log-seal.yaml`, same as before boards
existed. `refdes build --reseal board-a` accepts an edit only to board-a's own
sealed entries.

**Drift is a warning, not silent.** `.refdes/boards.yaml` records which board each
item was on at the last build — commit it, the same as `.refdes/ids.yaml`. Move a
file to a different board's folder and the next build warns:

```
WARNING items/board-b/requirements.yaml:9 [REQ-PWR-004] — REQ-PWR-004 moved from
        board 'board-a' to 'board-b' since the last build. Run 'refdes build
        --accept-board-move' if this is deliberate, or move the file back.
```

Run `refdes build --accept-board-move` to accept it; `refdes audit` lists every
accepted and outstanding move. Unlike a sealed log entry, a board move is never a
build error — moving a file is an ordinary thing to do on purpose.

### When this stops working

- **A board ships to a different customer** — you cannot hand over the site without
  handing over every other board.
- **You need to pin a version** — Board A was qualified against interface rev C,
  Board B is on rev D. One repo holds one revision.
- **Different teams own different boards** and a typo in one should not fail the
  other's build.
- **The site becomes unusable** at four or five boards.

Before reaching for separate projects, consider **[workspaces](workspaces.md)**
— an ownership boundary one level above boards, still inside one project. It
doesn't solve version pinning, but it does group boards by product, add a
lint that catches a board quietly depending on another product's items, and
lay out `items/` so that splitting later, when you actually need to, is a
folder move rather than a renumbering.

## Separate projects with imports

Split into projects, each with its own `refdes.yaml`, and import the shared one:

```yaml
# board-a/refdes.yaml
imports:
  - name: platform
    items: ../platform-interfaces/_site/items.json
    version: "2026.3"
```

The upstream project declares its version:

```yaml
# platform-interfaces/refdes.yaml
site:
  title: "Platform Interfaces"
  out: _site
  version: "2026.3"
```

Then build upstream first, downstream second:

```bash
cd platform-interfaces && refdes build
cd ../board-a          && refdes build
```

### Why import the artifact, not the source

You import a built `items.json`, not a source folder, because a shared interface
spec is **a dependency with a version**. You qualify a board against rev C and
upgrade to rev D deliberately. Pointing at a live source tree gives you a spec that
shifts under you between builds — which is how boards end up qualified against
something that no longer exists.

### What imported items can and cannot do

| Can | Cannot |
|---|---|
| Be linked to | Be edited or renumbered |
| Be checked against (`limit` works) | Be validated by your schema |
| Show a reference page | Appear in your coverage |
| Show *your* incoming links | Show other projects' incoming links |

They keep the content hash their own project computed, which is what makes
cross-project suspect links work once the history layer lands.

### Version pinning

If the pin and the artifact disagree, the import is refused:

```
ERROR refdes.yaml — import 'platform' is pinned to version '2026.3' but the
      artifact declares '2026.4'. Rebuild the upstream project or update the pin
      deliberately.
```

Omit `version:` to accept whatever is there. Pin it for anything you have qualified
against.

Expect cascading errors after a refused import — the items it would have provided
are genuinely absent, so links to them fail too. Fix the import first.

### A change upstream fails the board

This is the payoff. Platform tightens the connector rating:

```yaml
- id: IFC-CAN-001
  limit: "<= 2 A"      # was <= 3 A
```

Board A, unchanged, now fails:

```
ERROR items/decisions/pins.md:2 [DEC-A-001] — I_pin violates IFC-CAN-001:
      worst case 2.4 A vs <= 2 A
```

Nobody had to remember which boards were affected.

## ID uniqueness

**IDs must be unique across every project you import.** A collision is a hard
error:

```
ERROR refdes.yaml — import 'platform' defines 'IFC-CAN-001', which already
      exists (items/interfaces/local.yaml:4). IDs must be unique across every
      imported project — give each project its own prefix.
```

Give each project its own prefix namespace: `IFC-*` for platform, `REQ-A-*` for
board A, `REQ-B-*` for board B. Refdes deliberately does not qualify references
(`platform:IFC-CAN-001`) — that would tax every reference forever to solve a
problem that is cheap to prevent.

**If there is any chance of splitting boards later, adopt board-token prefixes
now.** It costs nothing today, and IDs freeze once baselined. See [IDs](ids.md).

## Not built yet

The **federated view**: one combined site across several *projects* (not to be
confused with [workspaces](workspaces.md), which group boards inside one
project), with cross-project back-links and an interface-compliance matrix
("which of our seven boards violate the connector derating?"). Individual
projects import and build correctly today; the federated view does not exist.
