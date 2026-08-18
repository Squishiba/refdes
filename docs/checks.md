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

If the text that failed to parse looks like it is naming more than one bound, the
error grows a second line:

```
note: if this limit describes more than one bound, split it into separate
      constraint items
```

## One `limit`, one bound

`limit` takes a single scalar comparison or range — never a list of them. A spec
sentence that reads naturally as "X, with Y, across Z" is not one constraint with
three clauses; it is three constraints that happen to share a paragraph in the
datasheet.

A real case that stalled a project: a sensor spec reading "±1 % of full scale
across 0–60 °C, with 12 V TVS protection". Written as a single `limit`, none of the
three numbers has anywhere to go — `limit` is `required: true`, so the field can't
be left off, and packing all three into one string fails to parse (the field is
scalar, not a list). The fix is not a bigger `limit` syntax; it's to notice that
"accuracy", "temperature range", and "clamp voltage" are three different
engineering arguments wearing one sentence, and give each its own item:

```yaml
- id: CON-SNS-010
  title: Sensor accuracy
  limit: "<= 0.01"   # 1 % of full scale, as a dimensionless fraction -- % is not a unit
  rationale: Control loop tolerance budget assumes 1 % worst case.

- id: CON-SNS-011
  title: Operating temperature
  limit: "0 degC .. 60 degC"
  rationale: Enclosure is rated for this range; the sensor must not be the
    limiting part.

- id: CON-SNS-012
  title: Input clamp voltage
  limit: "<= 12 V"
  rationale: TVS clamp voltage margin against the input's absolute max rating.
```

This is strictly more useful than the merged version: each constraint now checks
independently, gets its own page and its own row in the coverage table, and
carries the one rationale that actually explains it — the three reasons were
never the same reason, they were only ever the same string.

If a spec relates *several already-declared values* — not one value against a
fixed number, but an arithmetic relationship between them, e.g. "the sum of the
slot current limits shall not exceed the rail's rated capacity" — that is not a
gap in `limit` either. Compute the relation in a [calc block](math.md) and check
the result against an ordinary scalar constraint:

```calc
I_total = I_slot1 + I_slot2 + I_slot3
```

```yaml
checks:
  - value: I_total
    against: CON-PWR-020   # limit: "<= 25 A"
```

The relation (`+`) lives in the calc expression; the constraint stays a single
number. There is no `checks:` form for "sum against limit" because none is
needed — arithmetic is calc's job, and a `limit` only ever compares one value.

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
ERROR items/decisions/dec-pwr-001-regulator-topology.md:2 [DEC-PWR-001] —
      P_dens violates CON-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
```

The message leads with the worst-case bound that was actually checked. `P_dens`
here has no tolerance, so worst case and nominal are the same number and there
is nothing to disambiguate. A value that does carry a tolerance gets a
`(nominal X)` suffix instead, since the number that failed and the number an
author typed can differ — see [worst case, not nominal](#worst-case-not-nominal)
above:

```
ERROR items/decisions/dec-io-002.md:2 [DEC-IO-002] — CLIM violates CON-IO-004:
      worst case 0.697 A vs <= 600 mA (nominal 0.6061 A)
```

The item's page shows a `fail` badge, the check table gives the same detail,
and the failure is listed on the site index. `refdes check` exits non-zero, so
CI catches it.

Tip: use a [unit assertion](math.md) matching the constraint's units
(`P_dens : W/in^2`) so both sides of the comparison read in the same unit.

## Candidates vs. decisions

A failing check being a build error assumes the item is a decision: the design
either meets the constraint or it doesn't. That's the wrong reading for an item
that is still a *candidate* — comparing several microcontrollers against a
shared `CON-IO-008 (>= 2 DACs)`, two of them lacking an on-chip DAC is the
finding you're building the comparison to surface, not a defect to fix before
the build can pass.

Set `check_severity: info` on the type to change what a failing check is
reported as:

```yaml
types:
  option:
    check_severity: info      # candidates are scored, not asserted
```

| `check_severity` | A failing check is... |
|---|---|
| `error` (default) | a build error — unchanged from every project today |
| `warning` | a warning — visible by default, does not fail the build |
| `info` | an info diagnostic — hidden unless `-v`/`--verbose`, does not fail the build |

This only changes the diagnostic for a check that *ran and failed*. The item
page's `fail` badge and the check table's detail string are unaffected — a
candidate that fails a criterion still shows `fail`, exactly as a decision
would, because a comparison table needs every row read the same way.

Checks that could not be evaluated at all (below) are always errors,
regardless of `check_severity`: a typo'd value name or a missing target is an
authoring mistake, not a finding about the design.

## Checks that cannot be evaluated

These are errors too, not silent passes:

| Message | Cause |
|---|---|
| `check refers to 'X', which no calc block defines` | typo, or the calc line failed |
| `check against 'CON-X', which does not exist` | wrong ID, or a failed import |
| `check against CON-X, which declares no limit` | target has no `limit` field |
| `check ... cannot compare: ...` | dimensional mismatch between value and limit |

## How close was it?

Passing is not the same as passing comfortably. Every evaluated check also records a
**margin** — its worst-case slack relative to the limit — and `summary.html` sorts all
of them tightest-first so a check that scrapes through by 3% sits at the top of the
page instead of hiding among the greens.

Negative means violated, positive means slack, and the sign always agrees with the
pass/fail verdict. See [output formats](output.md) for the details, including the
cases where a margin is genuinely undefined.

## Why this matters across projects

A constraint owned by a shared platform project can be checked by every board that
imports it. Tighten the shared limit, rebuild, and each board's own arithmetic is
re-evaluated against it — the boards that no longer comply fail their builds
without anyone editing them. See [multiple boards](multi-board.md).
