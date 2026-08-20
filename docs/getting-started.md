# Getting started

We will build a small but complete project: two requirements, a thermal
constraint, a decision with real arithmetic, a test, and a log entry. By the end
the build will catch a genuine design problem.

## Install

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

On macOS or Linux the interpreter is `.venv/bin/python`. Everything below assumes
`refdes` is on your path; if it isn't, use
`./.venv/Scripts/python.exe -m refdes.cli` instead.

## 1. Create the project

A project is any folder containing `refdes.yaml`.

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
  version: 2

id:
  width: 3
  ledger: .refdes/ids.yaml
```

That's the whole file `refdes init` writes — rename the title to taste.
`version: 2` is whatever the installed `refdes` currently bundles as newest,
never the literal word `"latest"` — a later `refdes` may write a higher
number here; that's expected, not a sign this page is out of date. Nothing
here defines a `requirement` or a `link_types:` block — that all comes from
the pinned standard, resolved live from the installed `refdes` package. See
[the standard library](standard-library.md) for what it covers, and `refdes
init --standard none` if you'd rather author every type by hand, as every
project did before this existed. `init` also writes `.vscode/settings.json`,
wiring up field/link completion for `items/**/*.yaml` files if you're using
VS Code — see [editor
support](standard-library.md#editor-support-json-schema-emission).

```
my-board/
  refdes.yaml
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
  - text: The unit shall operate from an input supply of 9 V to 36 V.
    source: Customer spec rev D, §3.1

  - text: The 3V3 rail shall supply 1.2 A continuous.
    source: Customer spec rev D, §3.4
```

No IDs yet. Allocate them:

```bash
refdes id
```

```
allocated REQ-PWR-001  (items/requirements/power.yaml:9)  The unit shall operate...
allocated REQ-PWR-002  (items/requirements/power.yaml:12) The 3V3 rail shall supply...
allocated 2 id(s)
```

The IDs are now written into your file. They will never change. See [IDs](ids.md).

## 3. Add a constraint with a real limit

`items/constraints/thermal.yaml`

```yaml
defaults:
  type: constraint
  prefix: CON-THM
  status: active

items:
  - id: CON-THM-001
    text: Board power density
    limit: "<= 0.15 W/in^2"
    rationale: >
      Natural convection only — the enclosure is sealed, with no vents and no fan.
    source: Enclosure spec rev C, p.14
```

`limit` is a real field type. `<= 0.15 W/in^2` is parsed into a quantity, not
stored as a string, which is what makes the next step possible.

## 4. Write a decision that does arithmetic

Items with a body go in their own markdown file. Not sure what fields a
decision takes? `refdes new decision` prints a starter with every field
commented in, generated from the same resolved schema an editor's
completion reads — no trip back to this page needed.

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
constrained_by: [CON-THM-001]
options:
  - name: LDO (TPS7A4700)
    verdict: rejected
    because: Dissipates 10.4 W at full load — roughly seventy times the budget.
  - name: Synchronous buck (TPS62913)
    verdict: chosen
    because: 93 % efficiency at half load, ripple within spec with a 2nd-stage LC.
checks:
  - value: P_dens
    against: CON-THM-001
---

The 3V3 rail draws up to 1.2 A in a sealed enclosure. REQ-PWR-002 sets the load;
CON-THM-001 sets what we may dissipate getting there.

```calc
V_out            = 3.3 V
I_load           = 1.2 A
eff              = 0.93
P_diss  : W      = V_out * I_load * (1/eff - 1)
A_board          = 1.4 inch * 0.9 inch
P_dens  : W/in^2 = P_diss / A_board
```

The converter loses {{P_diss}} over {{A_board}} of board, so the power stage runs
at {{P_dens}}.
````

Three things are happening:

- The `calc` block evaluates with **real units**. `V * A` yields watts; `V + A`
  would be a build error.
- `P_diss : W` is a **unit assertion** — if the algebra drifted dimensionally, the
  build fails at that line.
- `checks:` compares `P_dens` against `CON-THM-001`'s limit.

## 5. Build

```bash
refdes build
```

```
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens
        violates CON-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING <project> — 2 item(s) with no coverage — see coverage.html
4 items, 1 errors, 1 warnings
site written to _site
```

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
    method: Sweep 9 V to 36 V at full load; log rail regulation.
    verifies: [REQ-PWR-001]
```

Note the test declares `verifies`. The requirement does not need to mention the
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
    addresses: [CON-THM-001]
    body: |
      Three ways out, none chosen: widen the allocation, improve efficiency, or
      renegotiate the 0.15 W/in² figure. Flagging rather than quietly widening,
      because option three changes a constraint other decisions depend on.
```

Log entries are **append-only**. Once built, editing this entry fails the build;
corrections are appended with `amends:`. See [the design log](design-log.md).

## Where to go next

- [Concepts](concepts.md) for the model behind all of this
- [Math](math.md) for units, tolerances, and the full calc syntax
- [Coverage](coverage.md) for tracking what still needs doing
- [Multiple boards](multi-board.md) when a second board appears
