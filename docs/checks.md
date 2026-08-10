# Checks

A check compares a computed value against a constraint's declared limit, at build
time. This is the mechanism that turns a document into something that can be wrong.

## Declaring a limit

Any item with a `limit` field can be checked against. In the starter schema that is
the `constraint` type:

```yaml
- id: CON-THM-001
  title: Board power density
  limit: "<= 0.15 W/in^2"
  rationale: Natural convection only — the enclosure is sealed.
```

Supported forms:

| Form | Example | Passes when |
|---|---|---|
| `<=` | `<= 0.15 W/in^2` | worst-case upper bound ≤ limit |
| `<` | `< 85 degC` | worst-case upper bound < limit |
| `>=` | `>= 0.90` | worst-case lower bound ≥ limit |
| `>` | `> 1 MHz` | worst-case lower bound > limit |
| `==` | `== 50 ohm` | value is exactly this, with no tolerance width |
| range | `9 V .. 36 V` | entire tolerance interval sits inside |

In a range, the lower bound may omit the unit: `9 .. 36 V` works.

A limit that cannot be parsed is a build error, caught at validation rather than at
check time:

```
ERROR items/constraints/thermal.yaml:8 [CON-THM-001] — limit: could not read limit
      'somewhere under 2 watts'; expected a comparison such as '<= 2 W/in^2' or a
      range such as '9 V .. 36 V'
```

## Declaring a check

In the item doing the work — usually a decision — name a calc value and the item to
check it against:

```yaml
checks:
  - value: eff
    against: CON-THM-002
  - value: P_dens
    against: CON-THM-001
```

`value` must be a variable defined by a `calc` block in the **same item**.
`against` must be an item with a `limit`, and may be
[imported from another project](multi-board.md).

## Worst case, not nominal

When a value carries a tolerance, the check uses the bound hardest to satisfy:

```calc
V = 10 V ± 20%
```

against `<= 11 V` **fails**, because the interval reaches 12 V, even though the
nominal 10 V passes. This is the whole reason tolerances propagate.

## What a failure looks like

```
ERROR items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001]
      P_dens = 0.2366 W/in² violates CON-THM-001 (<= 0.15 W/in^2)
```

The item's page shows a `fail` badge, the check table gives the detail
(`worst case 0.2366 W/in² vs <= 0.15 W/in^2`), and the failure is listed on the
site index. `refdes check` exits non-zero, so CI catches it.

Tip: use a [unit assertion](math.md) matching the constraint's units
(`P_dens : W/in^2`) so both sides of the comparison read in the same unit.

## Checks that cannot be evaluated

These are errors too, not silent passes:

| Message | Cause |
|---|---|
| `check refers to 'X', which no calc block defines` | typo, or the calc line failed |
| `check against 'CON-X', which does not exist` | wrong ID, or a failed import |
| `check against CON-X, which declares no limit` | target has no `limit` field |
| `check ... cannot compare: ...` | dimensional mismatch between value and limit |

## Why this matters across projects

A constraint owned by a shared platform project can be checked by every board that
imports it. Tighten the shared limit, rebuild, and each board's own arithmetic is
re-evaluated against it — the boards that no longer comply fail their builds
without anyone editing them. See [multiple boards](multi-board.md).
