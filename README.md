# Refdes

Reference documentation for hardware design decisions. Typed, linked items like
sphinx-needs; authoring ergonomics closer to Quarto; a Doxygen-shaped reference
site. The part that is neither: the math in a document is *evaluated*, carries
units, and is checked against your constraints at build time.

A spec change propagates through the arithmetic and tells you which decisions it
just invalidated.

**Full documentation is in [`docs/`](docs/index.md)** — and it is built with
Refdes itself:

```bash
cd docs-site && refdes build   # -> _docs/index.html
```

Start with [getting started](docs/getting-started.md) for a ten-minute tutorial, or
[concepts](docs/concepts.md) for the model behind it. What follows is a summary.

## Install

```bash
python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e .
```

## Commands

```bash
refdes build     # render _site/ and items.json
refdes check     # validate without rendering; non-zero exit on errors
refdes index     # print items.json to stdout, for tooling
refdes id        # allocate IDs for items that have none, writing them back
refdes audit     # list suppressed fields, resealed entries, and imports
```

## Editor support

A VS Code extension lives in [`editors/vscode/`](editors/vscode/README.md) —
inline calc results, live diagnostics, ID completion, hover previews, and
go-to-definition. Open that folder and press <kbd>F5</kbd>; there is no build step.

For squiggles without installing anything, [`.vscode/tasks.json`](.vscode/tasks.json)
carries problem matchers that work out of the box.

## Authoring

One object model, two serializations. Rich items get a file; bulk items get a list.

**`items/**/*.md`** — front-matter plus a markdown body, for decisions and anything
with prose, calcs, or options.

**`items/**/*.yaml`** — a list sharing `defaults:`, for bulk requirements:

```yaml
defaults:
  type: requirement
  prefix: REQ-PWR
  owner: J. Bin
items:
  - text: The unit shall operate from 9 V to 36 V.
  - text: Converter efficiency shall exceed 90 % at half load.
```

Leave the `id:` off. `refdes id` allocates the next free number and writes it
into the file. IDs are never derived from position, so inserting a requirement at
the top does not shift anything below it.

## Math

Restricted expression DSL — assignments, arithmetic, units, and a whitelist of
functions. No loops, conditionals, imports, or attribute access, so a document
cannot execute code and every result is deterministic.

````markdown
```calc
V_out            = 3.3 V
I_load           = 1.2 A
eff              = 0.93
P_diss  : W      = V_out * I_load * (1/eff - 1)
A_board          = 1.4 inch * 0.9 inch
P_dens  : W/in^2 = P_diss / A_board
```
````

Reference a result inline with `{{P_diss}}`. Units are the type system: `V * A`
yields watts, and `V + A` is a build error rather than a silent wrong answer.

Tolerances propagate as intervals:

```
V_in = 12 V ± 5%     ->   12 V   (11.4 V … 12.6 V)
```

### Writing units

A bare token after a number is always read as a unit. Write them without internal
spaces (`2 W/in^2`, `9.81 m/s^2`) and use `·` for products (`N·m`).

**Brackets are the escape hatch.** `0.5 [h]` is unambiguously half an hour even
when a variable named `h` is in scope, and anything goes inside them, including
`*`:

```
tq = 2 [N*m]
```

Single-letter variables collide with SI units constantly — `A` for area, `C` for
capacitance, `L` for inductance, `R` for resistance. That is normal engineering
notation, so a collision is a **warning, not an error**: juxtaposition never means
multiplication, so `1.2 A` has exactly one parse and the unit reading always wins.
The warning exists only in case you meant `1.2 * A`. Brackets silence it.

Units a compound like `W/h` contains are never flagged — a segment inside a
compound cannot be anything but a unit.

### Unit assertions

`name : unit = expression` declares what the result should be, and fails the build
if the algebra drifts:

```
P : W = V_out / I_load     ->  error: declared as W but the expression evaluates to V/A
```

It also pins the display unit, which is why `P_dens : W/in^2` reports
`0.2366 W/in²` rather than `236.6 mW/in²` — matching the constraint it is checked
against. Annotations are optional; use them where getting the dimension wrong would
be expensive.

## Checks

A constraint declares a limit; a decision declares what it is checking:

```yaml
# in the constraint
limit: "<= 0.15 W/in^2"

# in the decision
checks:
  - value: P_dens
    against: CON-THM-001
```

`refdes check` fails the build when the value violates the limit, evaluated at
the **worst-case tolerance bound**, not the nominal.

## Change tracking

Every field declares what a change to it means:

| mode | timeline | baseline diff | invalidates downstream |
|---|---|---|---|
| `invalidate` | yes | yes | yes |
| `log` | yes | no | no |
| `ignore` | no | no | no |

Set per field in `refdes.yaml`, overridable per item (with a required
`reason:`). The content hash is computed over `invalidate` fields only, which is
what stops an owner change from marking fifty links suspect.

`refdes audit` lists everything currently suppressed. Suppression is allowed;
invisible suppression is not.

## The design log

A dated, append-only record of how the design actually got where it is — the
measurements, the dead ends, the reasoning between a requirement being handed to
you and a decision being made. A `decision` is the settled conclusion; a `log`
entry is a step on the way to one.

```yaml
defaults:
  type: log
  prefix: LOG-A
  board: board-a
  author: J. Bin
items:
  - id: LOG-A-005
    date: 2026-03-16
    summary: Thermal check fails; power stage is over the density budget.
    addresses: [CON-THM-001]
    body: |
      Three ways out, none chosen yet: widen the allocation, improve efficiency,
      or renegotiate the 0.15 W/in² figure...
```

Entries are **sealed on first build**. Editing one afterwards fails the build:

```
ERROR  LOG-A-003 is append-only and has been modified since it was sealed.
       Append a new entry with `amends: [LOG-A-003]` instead, or run with
       --reseal if the edit is deliberate.
```

Corrections are appended, exactly as in a paper notebook where you strike through
and initial rather than erase. `--reseal` exists for deliberate overrides and is
reported by `refdes audit`, so an override is always visible.

This cannot *prevent* an edit — no file-based tool can. It detects one, which is
what actually matters.

## Coverage

Three separate questions, deliberately not collapsed into one flag:

| stage | meaning |
|---|---|
| `open` | nothing references it at all |
| `addressed` | a log entry works on it |
| `satisfied` | a decision claims to meet it |
| `verified` | a test proves it |

A requirement can be satisfied without being verified, and addressed without being
satisfied. Collapsing those is how open work goes missing. `coverage.html` sorts
the least-covered first, and the same data is in `items.json` under `coverage`.

## Multiple boards

For a family of boards in one repo, use folders and per-board prefixes
(`REQ-A-PWR`, `REQ-B-PWR`, `IFC-*` for anything shared). Links, checks, and
back-links all work across folders with no extra machinery.

When boards need to ship, version, or be owned separately, split them into projects
and import the shared one:

```yaml
imports:
  - name: platform
    items: ../platform-interfaces/_site/items.json
    version: "2026.3"
```

You import the built **artifact**, not the source tree, because a shared interface
spec is a dependency with a version — you qualify a board against rev C and upgrade
deliberately. Reading a live source folder gives you a spec that shifts under you
between builds.

Imported items are read-only: you link to them, check against their limits, and get
a reference page showing which of *your* items depend on them. They are excluded
from your coverage and validation, and they keep the content hash their own project
computed. A version mismatch or an ID collision is a hard error.

**IDs must be unique across every project you import.** Give each project its own
prefix. If you may ever split boards apart, adopt board-token prefixes now
(`REQ-A-PWR-001`) — it costs nothing today and IDs are frozen once baselined.

## Output

`_site/` is static HTML — no server, no build step for the reader, works with JS
disabled. Cross-references get hover previews (keyboard-accessible, Escape to
dismiss, tap on touch) showing the target's fields and current check state.

`_site/items.json` is the machine-readable export. Anything downstream should read
that, not the HTML.

## Not built yet

- **Git history layer** — field-level diffs, item timelines, suspect links,
  baselines. The `on_change` policy and content hash it depends on are wired and
  tested; the git reader is not written. Imported items already carry their
  upstream hash, so cross-project suspect links drop in with it.
- **Workspace view** — one combined site across several projects, with
  cross-project back-links and an interface-compliance matrix. Individual projects
  import and build correctly today; the federated view does not exist.
- **Solving for unknowns** — `sympy` symbolic solve. Forward evaluation only today.
- **Client-side search** and query blocks in narrative pages.
- **Typeset math** — calc blocks render as clean tables; KaTeX can be vendored later.
- **Spreadsheet import**, KiCad/BOM extraction, Monte Carlo, trig functions.

## Known limitations

- **Torque reads as energy.** `N·m` and `J` are dimensionally identical, so a
  torque collapses to joules on display. Pin it with an assertion (`tq : N*m = …`)
  if it matters. Every units library has this problem; none solve it without a
  separate notion of quantity kind.
- **Interval widths are conservative.** A variable appearing more than once in an
  expression is treated as independent at each occurrence, so `x - x` reports a
  non-zero width. Exact for monotonic expressions, loose otherwise.

## Tests

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

The suite covers the invariants that must not quietly break: IDs never shift or get
reused, the DSL cannot execute code, the content hash follows the `on_change`
policy exactly, and checks use the worst-case bound.
