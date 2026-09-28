# Getting started

We will build a small but complete project: two requirements, a thermal
bound, a decision with real arithmetic, a test, and a log entry. By the end
the build will catch a genuine design problem.

## Install

```bash
python -m venv .venv
```

Then install into it with your venv's own interpreter. That path differs by
platform — use the one that matches your machine:

Linux and macOS:

```bash
./.venv/bin/python -m pip install -e .
```

Windows (PowerShell):

```bat
.\.venv\Scripts\python.exe -m pip install -e .
```

Everything below assumes `refdes` is on your path. If it isn't, run the module
through the venv interpreter instead — `./.venv/bin/python -m refdes.cli` on
Linux and macOS, `.\.venv\Scripts\python.exe -m refdes.cli` on Windows.

## 1. Create the project

A project is any folder containing `refdes-project.yaml` — the file is the
project marker, and it holds every project setting.

```bash
mkdir my-board && cd my-board
refdes init
```

```yaml
site:
  title: "New Project — Design Reference"
  out: _site

standard:
  base: hardware
  version: 3
  presets: []

id:
  width: 3
  ledger: .refdes/ids.yaml
```

That's the whole file `refdes init` writes. Rename the title to taste.

`version: 3` is whatever the installed `refdes` currently bundles as newest —
never the literal word `"latest"`. A later `refdes` may write a higher number
here; that is expected, and not a sign this page is out of date. When you need
to know which `refdes` you are holding, ask it: `refdes --version` (or `-V`)
prints the installed version and exits — see [the CLI
reference](cli-reference.md).

Nothing here defines a `requirement` or a `link_types:` block. That comes from
the pinned standard, resolved live from the installed `refdes` package. See
[the standard library](standard-library.md) for what it covers. If you would
rather author every type by hand, as every project did before this existed,
`refdes init --standard none` starts you there instead. Types you define
yourself go in an optional `refdes-schema.yaml` beside this file — that one
holds only `types:`, `link_types:`, and `sets:`.

`init` also writes `.vscode/settings.json`, wiring up field/link completion for
`items/**/*.yaml` files if you're using VS Code — see [editor
support](standard-library.md#editor-support-json-schema-emission).

`items/` is not created for you. Make it, and any folders under it, yourself:

```
my-board/
  refdes-project.yaml
  .vscode/settings.json
  items/
```

Everything under `items/` is scanned recursively. The folder layout is yours to
choose; it has no meaning to the tool.

## 2. Write two requirements

Bulk items go in a list file. Shared values live in `defaults:` so you write them
once.

`items/requirements/power.yaml`

```yaml
defaults:
  type: requirement
  prefix: REQ-PWR
  owner: J. Bin
  tags: [power]
  status: active

items:
  - body: The unit shall operate from an input supply of 9 V to 36 V.
    source: Customer spec rev D, §3.1

  - body: The 3V3 rail shall supply 1.2 A continuous.
    source: Customer spec rev D, §3.4
```

No IDs yet. Allocate them:

```bash
refdes id
```

```
allocated REQ-PWR-001  (items/requirements/power.yaml:9) The unit shall operate from an input supply of 9 V to 36 V.
allocated REQ-PWR-002  (items/requirements/power.yaml:13) The 3V3 rail shall supply 1.2 A continuous.
allocated 2 id(s)
```

The IDs are now written into your file. They will never change. See [IDs](ids.md).

## 3. Add a bound with a real limit

A **bound** is a machine-checkable limit — the type that makes the next step
possible. (It was called `constraint` in `hardware@1`, before the rename; see
[the standard library](standard-library.md#versioning-and-pinning).)

`items/bounds/thermal.yaml`

```yaml
defaults:
  type: bound
  prefix: BND-THM
  status: active

items:
  - id: BND-THM-001
    body: Board power density
    limit: "<= 0.15 W/in^2"
    rationale: >
      Natural convection only — the enclosure is sealed, with no vents and no fan.
    source: Enclosure spec rev C, p.14
```

`limit` is a real field type. `<= 0.15 W/in^2` is parsed into a quantity, not
stored as a string.

## 4. Write a decision that does arithmetic

Items with a body go in their own markdown file. Not sure what fields a
decision takes? `refdes new decision` prints a starter with every field
commented in, generated from the same resolved schema an editor's
completion reads.

```bash
refdes new decision > items/decisions/dec-pwr-001-regulator.md
```

`items/decisions/dec-pwr-001-regulator.md`

````markdown
---
id: DEC-PWR-001
type: decision
title: 3V3 rail regulator topology
status: accepted
date: 2026-03-14
satisfies: [REQ-PWR-002]
constrained_by: [BND-THM-001]
options:
  - name: LDO (TPS7A4700)
    verdict: rejected
    because: Dissipates 10.4 W at full load — roughly seventy times the budget.
  - name: Synchronous buck (TPS62913)
    verdict: chosen
    because: 93 % efficiency at half load, ripple within spec with a 2nd-stage LC.
checks:
  - value: P_dens
    against: BND-THM-001
---

The 3V3 rail draws up to 1.2 A in a sealed enclosure. REQ-PWR-002 sets the load;
BND-THM-001 sets what we may dissipate getting there.

```calc
V_out            = 3.3 V
I_load           = 1.2 A
eff              = 0.93
P_diss           = V_out * I_load * (1/eff - 1) | W
A_board          = 1.4 inch * 0.9 inch
P_dens           = P_diss / A_board | W/in^2
```

The converter loses {{P_diss}} over {{A_board}} of board, so the power stage runs
at {{P_dens}}.
````

Three things are happening:

- The `calc` block evaluates with **real units**. `V * A` yields watts; `V + A`
  would be a build error.
- `P_diss ... | W` is a **unit assertion** — if the algebra drifted dimensionally,
  the build fails at that line.
- `checks:` compares `P_dens` against `BND-THM-001`'s limit.

## 5. Build

```bash
refdes build
```

```
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING <project> — 2 item(s) with no coverage — see coverage.html
4 items, 1 errors, 1 warnings
site written to /path/to/my-board/_site
build completed with errors (use --keep-going to exit 0)
```

Errors go to stderr and everything else to stdout, so the two streams may
interleave differently in your terminal than they do above.

That is the point of the tool. Nobody typed 0.2366; the build computed it and
compared it to the budget. Open `_site/index.html`.

## 6. Add a test and close the loop

`items/tests/power.yaml`

```yaml
defaults:
  type: test
  prefix: TST-PWR

items:
  - id: TST-PWR-001
    title: Input range sweep
    status: passing
    body: Sweep 9 V to 36 V at full load; log rail regulation.
    verifies: [REQ-PWR-001]
```

The test declares `verifies`. The requirement does not need to mention the
test — back-links are computed. `REQ-PWR-001` now shows as **verified** on
`coverage.html`, while `REQ-PWR-002` shows as **satisfied** but not verified.

## 7. Record how you got here

`items/log/board.yaml`

```yaml
defaults:
  type: log
  prefix: LOG
  author: J. Bin

items:
  - id: LOG-001
    date: 2026-03-16
    summary: Thermal check fails; the power stage is over the density budget.
    addresses: [BND-THM-001]
    body: |
      Three ways out, none chosen: widen the allocation, improve efficiency, or
      renegotiate the 0.15 W/in² figure. Flagging rather than quietly widening,
      because option three changes a bound other decisions depend on.
```

Log entries are **append-only**. Once built, editing this entry fails the build;
corrections are appended with `amends:`. See [the design log](design-log.md).

**Nothing above turns the build green, and superseding the decision will not
either.** Write a passing decision that carries `supersedes: [DEC-PWR-001]`, set
`DEC-PWR-001`'s status to `superseded`, and `refdes check` still reports the
old failure. That is history, not a bug — the decision's own numbers stay on
the record, and a superseded decision still shows as having missed the bound.
`decision` ships `check_severity: error` for every status, so nothing about the
walkthrough clears it for you.

To let settled history drop to a non-blocking level, map the statuses in
`refdes-schema.yaml`:

```yaml
types:
  decision:
    check_severity:
      default: error
      superseded: info
      rejected: info
```

`default:` is required — omit it and the project refuses to load with
`types.decision.check_severity does not cover status 'proposed'`. Statuses you
do not map keep `default:`, so a decision that is still `accepted` and still
failing remains a build error. A demoted failure is not gone either; it moves
to `refdes check -v`. `component` ships a mapping like this already. See
[candidates vs. decisions](checks.md#candidates-vs-decisions) and the
[types reference](schema-reference.md#types).

## Where to go next

- [Concepts](concepts.md) for the model behind all of this
- [Math](math.md) for units, tolerances, and the full calc syntax
- [Coverage](coverage.md) for tracking what still needs doing
- [Multiple boards](multi-board.md) when a second board appears
