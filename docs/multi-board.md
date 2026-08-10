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

### When this stops working

- **A board ships to a different customer** — you cannot hand over the site without
  handing over every other board.
- **You need to pin a version** — Board A was qualified against interface rev C,
  Board B is on rev D. One repo holds one revision.
- **Different teams own different boards** and a typo in one should not fail the
  other's build.
- **The site becomes unusable** at four or five boards.

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
ERROR items/decisions/pins.md:2 [DEC-A-001] — I_pin = 2.4 A violates
      IFC-CAN-001 (<= 2 A)
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

The **workspace view**: one combined site across several projects, with
cross-project back-links and an interface-compliance matrix ("which of our seven
boards violate the connector derating?"). Individual projects import and build
correctly today; the federated view does not exist.
