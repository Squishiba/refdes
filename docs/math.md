# Math

Calc blocks are a restricted expression language: assignments, arithmetic, units,
and a whitelist of functions. No loops, conditionals, imports, attribute access, or
I/O. A document cannot execute code, so results are deterministic and untrusted
input is safe to build.

## A calc block

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

Renders as a table of expression and evaluated result:

```
V_out             = 3.3 V                        → 3.3 V
P_diss  : W       = V_out * I_load * (1/eff - 1) → 0.2981 W
A_board           = 1.4 inch * 0.9 inch          → 1.26 in²
P_dens  : W/in^2  = P_diss / A_board             → 0.2366 W/in²
```

Variables are visible to later lines in the same item, across multiple blocks.
They are **not** shared between items.

## Referencing results in prose

```markdown
The converter loses {{P_diss}} over {{A_board}} of board.
```

→ "The converter loses 0.2981 W over 1.26 in² of board."

A `{{name}}` that does not match a calc value in the same item is a warning and is
left as written.

## Writing units

A bare token after a number is always read as a unit. Units contain no internal
whitespace:

| Write | Not |
|---|---|
| `2 W/in^2` | `2 W / in^2` |
| `9.81 m/s^2` | `9.81 m / s^2` |
| `47 uF` | `47 micro farad` |
| `N·m` | `N*m` (outside brackets) |

Separators inside a unit are `/` for division, `·` for product, and `^` for
exponent. `µ`, `μ`, and `u` all work as the micro prefix; `Ω` and `ohm` both work.

### `mil` and house units

`mil` and `mils` mean 0.001 inch, as they do on every PCB. The underlying units
library reads a bare "mil" as the *angular* mil — a dimensionless artillery unit —
so Refdes aliases it. They display as `th` (thou), which is the same unit under its
unambiguous name.

Add your own aliases in `refdes.yaml`:

```yaml
units:
  aliases:
    sq: inch**2
```

Verified working out of the box: `thou`, `degC`, `delta_degC`, `dBm`, `ppm`, `uF`,
`uH`, `GHz`, `mAh`, `oz`, `ohm`, `kWh`. **`AWG` is not a unit** — it is a gauge
scale, not a measure, so write the actual diameter or area.

### Brackets are the escape hatch

`[...]` makes a unit explicit, and anything goes inside — including `*`:

```calc
t  = 0.5 [h]        # half an hour, even if a variable `h` exists
tq = 2 [N*m]
```

### Unit / variable collisions

Single-letter variables collide with SI units constantly — `A` for area, `C` for
capacitance, `L` for inductance, `R` for resistance. This is normal engineering
notation, so a collision is a **warning, not an error**:

```
WARNING calc P: `1.2 A` reads 'A' as a unit, but a variable of that name is also
        defined here. Write `1.2 [A]` to silence this, or rename the variable if
        you meant to multiply.
```

The unit reading always wins, because juxtaposition never means multiplication in
this language — `1.2 A` has exactly one parse. The warning exists only in case you
believed it meant `1.2 * A`. Brackets silence it.

A unit inside a compound is never flagged: `5 W/h` cannot mean anything but watts
per hour.

## Unit assertions

`name : unit = expression` declares what the result must be:

```calc
P : W = V_out / I_load
```

```
ERROR calc P: declared as W but the expression evaluates to V/A
```

Assertions also **pin the display unit**, which is why `P_dens : W/in^2` reports
`0.2366 W/in²` rather than `236.6 mW/in²` — matching the bound it is checked
against. Use them wherever getting the dimension wrong would be expensive.

## Tolerances

```calc
V_in = 12 V ± 5%          # or +/- for ASCII
V_ref = 2.5 V ± 10 mV     # absolute tolerance
```

Both forms produce an interval carried through every later expression:

```
V_in = 12 V ± 5%   →  12 V      11.4 V … 12.6 V
P    = V_in * 2 A  →  24 W      22.8 W … 25.2 W
```

Only one `±` per assignment, and it may not be applied to a value that already has
a tolerance.

**Interval widths are conservative.** A variable appearing more than once in an
expression is treated as independent at each occurrence, so `x - x` reports a
non-zero width. This is exact for monotonic expressions — most power and thermal
arithmetic — and loose otherwise.

## Display units

Derived results collapse to named units where that is clearer:

| Computed | Displayed |
|---|---|
| `volt * ampere` | `3.96 W` |
| `millivolt / ampere` | `41.67 mΩ` |
| `1 / microsecond` | `454.5 kHz` |

But a unit you wrote yourself is never rewritten. `1.4 inch` stays inches,
`0.5 h` stays hours, `W/in^2` stays per square inch. Only compound and reciprocal
results are candidates for renaming, and only sub-products are collapsed — in
`volt*ampere/inch**2`, the `volt*ampere` becomes `W` and your `inch**2` is left
exactly as written.

Which units are candidates is set by `units.preferred` in
[`refdes.yaml`](schema-reference.md). Only single-symbol units belong there.

## Functions

`sqrt`, `abs`, `min`, `max`, `exp`, `ln`, `log10`.

`exp`, `ln`, and `log10` require dimensionless arguments. `min` and `max` take two
or more. Trigonometric functions are **not** available — intervals through
non-monotonic functions need range analysis that is not implemented, and silently
under-wide bounds would be worse than no support.

## Errors you will see

```
cannot add V and A — the units do not match
cannot divide by a value whose tolerance range includes zero
unknown unit 'wat'
unknown function 'sin'; available: abs, exp, ln, log10, max, min, sqrt
exponent must be dimensionless
declared as W but the expression evaluates to V/A
```

Every one is a build error. There is no path by which a dimensional mistake
produces a number.

## Known limitations

- **Torque reads as energy.** `N·m` and `J` are dimensionally identical, so a
  torque displays as joules. Pin it with `tq : N*m = ...`. Every units library has
  this; none solve it without a separate notion of quantity kind.
- **No solving for unknowns.** Forward evaluation only. Symbolic solve is planned.
- **No cross-item references.** A calc block cannot read another item's values.
