# Math

Calc blocks are a restricted expression language: assignments, arithmetic, units,
and a whitelist of functions. No loops, conditionals, imports, attribute access, or
I/O. A document cannot execute code, so results are deterministic and untrusted
input is safe to build.

## A calc block

````markdown
```calc
V_out   = 3.3 V
I_load  = 1.2 A
eff     = 0.93
P_diss  = V_out * I_load * (1/eff - 1) | W
A_board = 1.4 inch * 0.9 inch
P_dens  = P_diss / A_board | W/in^2
```
````

Renders as a table of expression and evaluated result:

```
V_out   = 3.3 V                                  → 3.3 V
P_diss  = V_out * I_load * (1/eff - 1) | W       → 0.2981 W
A_board = 1.4 inch * 0.9 inch                    → 1.26 in²
P_dens  = P_diss / A_board | W/in^2              → 0.2366 W/in²
```

Variables are visible to later lines in the same item, across multiple blocks.
They are **not** shared between items — unless a reference to the item's values
names them, below.

## Naming a calc block

A calc block can carry a name, which is how an item with two calculations says
which is which — and how prose can point at one table instead of "the second
calc block":

````markdown
```calc id="losses"
P_out  = V_out * I_load | W
P_diss = P_out * (1/eff - 1) | W
```
````

`id="..."` is an attribute on the opening fence line — the fence's info
string, quoted exactly like `caption="..."` on a figure or `type="decision"`
on a page block. Naming is **opt-in**: a ```` ```calc ```` with no attribute is
legal and renders byte-for-byte as it always has; a block needs no name until
something wants to point at it.

The name is lowercase, 1–40 characters, matching `[a-z][a-z0-9_-]{0,39}` — the
same shape as citation ids and figure ids, and deliberately not the
symbol-shaped value names (`P_diss`) a block assigns, so a bare token's kind is
readable and a block name can never be pasted where a value name belongs and
look right. `id` is the only attribute the fence accepts: anything else on the
fence line — a bare word, an unquoted value, an unknown key, a name outside the
grammar — is a build error at the fence line naming the fix (see
[troubleshooting](troubleshooting.md)).

What a name is: **a label on the rendering.** A named block's table gains an
anchor (`#calc-<name>`) and a caption carrying the name, so the two
calculations in an item are distinguishable on its page.
`[[DEC-PWR-001#calc:losses]]` in prose links straight to that table, and
`{{calcblock item="DEC-PWR-001" block="losses"}}` on a page renders it — both
address the block itself, never its individual values.

What a name is **not**:

- **Not a scope.** `env` and the one-name-per-item rule stay item-wide: a value
  assigned in block `supply` is visible to block `losses` exactly as it is now,
  and two blocks assigning the same value name still get the ordinary "assigned
  twice" error. Naming a block must not become a way to make two `P_diss`
  values coexist.
- **Not a key.** No `@key` composite, no expansion pass, nothing `refdes keys`
  touches. Renaming a block breaks the prose and page blocks that point at it,
  loudly, at the referring site — and no arithmetic, because no arithmetic
  refers to blocks.
- **Not a value qualifier.** Block names never appear in a value reference; see
  the next section.

Block names are unique per item: two `id="losses"` fences in one item are a
build error naming both lines and the rename fix. The same name in two
different items is fine.

## Referencing another item's values

One number that belongs to the power stage and is used by everything downstream
of it should be written once. Retyping it into every item that needs it means
the copies diverge silently when the original changes. A dotted reference names
another item's calc value directly:

```calc
V_in = DEC-PWR-001.V_in
P_in = V_in * I_in | W
```

This is a real dependency, not a convenience alias. The build evaluates items
in dependency order — an item's calc runs only after every item it reads from —
and the reference is stored expanded as a `DISPLAY-ID@key` composite like every
other structured reference, so renaming `DEC-PWR-001` refreshes the label and
keeps resolving. The next writable command freezes the bare spelling to its
composite; under `--no-write` the bare reference still resolves on the display
id, and nothing is written.

Any named value in the target's calc blocks is referenceable — there is no
exports list. The pipe unit works on a reference like on any line:
`V_in = DEC-PWR-001.V_in | mV` re-expresses the target's value in millivolts.
Units and tolerances flow through untouched: a reference to `12 V ± 5%` arrives
with its ±5% intact, which is exactly what a retyped `12 V` loses.

A reference never names a block: the target half is an item, the name half is a
value, and that is the whole grammar — block names are labels on the rendering,
not part of value resolution. So `DEC-PWR-001.losses.P_diss` is a build error
naming the working form `DEC-PWR-001.P_diss`, not a second spelling of one
reference.

A reference binds a name exactly as an assignment does, so the one-name-per-item
rule is unchanged: an item that both assigns `V_in` and references it gets the
ordinary "assigned twice" error.

Every failure is a loud error at the referring line — never a silent default or
a stale value:

```
ERROR calc V: no item 'DEC-NOPE' -- cross-item reference 'DEC-NOPE.V_in' names an item that does not exist
ERROR calc X: cross-item reference 'DEC-001.Iout': DEC-001 does not define 'Iout' (it defines: I_out, V_in)
ERROR calc V: cannot resolve 'DEC-001.V_in': DEC-001's own calc failed
ERROR calc reference cycle: DEC-001 -> DEC-002 -> DEC-001
```

A reference to an item whose own calc failed reports *that*, in one line — the
root error is stated once, at the item that broke. A cycle is an error naming
the full path, the way `blocked_by` and equation cycles already are.

References into imported items are refused with a message saying so: a
cross-project calc reference is only honest against the pinned artifact
version, and that is a later decision.

### An upstream change marks the dependent changed

The value a reference resolved to is part of the referring item's content
hash (`hash_format` 4), so when `DEC-PWR-001`'s `V_in` moves, `DEC-B` shows up
as `changed` in the baseline diff even though nothing in its own text did --
and `refdes audit` says which reference moved:

```
  changed   2   DEC-B, DEC-PWR-001
    DEC-B -- referenced DEC-PWR-001.V_in: 12 V (11.4 V … 12.6 V) -> 11.4 V (10.83 V … 11.97 V)
```

The hash covers the target's key and the full-precision value with its unit
and tolerance, not the rounded display: renaming the target's display id, or
the bare → `DISPLAY-ID@key` expansion of the reference on disk, changes
nothing; an edit below the displayed precision still counts. Editing some
*other* value or the prose of the target does not touch the dependent.
Baselines stamped before this record no reference values, so for those the
diff still lists the item as changed but names no reference.

Renaming a value *inside* the target has no surrogate to protect it (a calc
name is not a key): every dependent fails loudly at its own reference line,
which is the report.

## Reading a value from a source file

A number that lives in a spreadsheet export -- a power budget, a measured
table -- can be pulled into a calc block by name instead of being retyped:

```calc
eff = source("analysis/power-budget.csv", "tps62913_half_load_eff") | 1
P   = source("analysis/power-budget.csv", "rail_3v3_power") | W
```

The file is an ordinary repo-local [citation](markdown.md#citing-a-datasheet)
**declared on the same item** (`citations: [{path: analysis/power-budget.csv}]`);
a citation on another item, or a remote URL, does not authorize the read. The
CSV is a `key,value` table (extra columns are allowed for your own notes):

```csv
key,value,source_note
tps62913_half_load_eff,0.93,TPS62913 datasheet rev E figure at half load
```

`refdes fetch` reads the file once, pins each key you used in
`.refdes/citations.yaml`, and from then on `check` and `build` read only that
lockfile -- they never open the CSV. The rules that keep a wrong number from
slipping in:

- **Exact key, one row.** A missing key, a duplicated key, a duplicated
  `key`/`value` header, a blank or non-numeric cell, `100 mW`, `1,000`,
  `1_000`, non-ASCII digits, or an overflow is an error at fetch time and
  leaves the previous pin untouched.
- **The unit is yours to declare, and is mandatory** -- `| 1` for a
  dimensionless value. It *labels* the file's bare number: `1850` in a
  milliwatt sheet under `| W` shows as `1850 W`, on purpose, so the mismatch is
  visible instead of quietly converted. `refdes fetch --update` also prints an
  advisory warning when a value changes by exactly 1000x.
- **A tolerance goes on the calc line**: `source(...) ± 2 % | 1`.
- `source(...)` must be the whole right-hand side (not inside an expression),
  and is not callable from a project equation.

### When the file changes

A changed source file **warns loudly; it does not fail the build**, and the
build keeps using the reviewed, locked value until you accept the change:

```
WARNING <project> — SOURCE FILE CHANGED: 'analysis/power-budget.csv' no longer matches its pin, but the build is still using the LOCKED values, not the file -- 'rail_3v3_power': locked 1.85, file now 2.3 (CHANGED) [used by LOG-PWR-001]. Review the change, then accept it with: refdes fetch --update --path analysis/power-budget.csv
```

The same text shows under the affected calc row on the rendered item.
`refdes fetch --update` is the acceptance gate: it prints
`analysis/power-budget.csv: rail_3v3_power: 1.85 -> 2.3`, re-pins the file and
its values together, and the next build uses `2.3`. CI can promote the warning
to an error with `--require-citations`. The locked value is part of the item's
content hash (`hash_format` 4), so an accepted update marks the item changed
even though its text did not; an unrelated edit elsewhere in the file does not.
Design: [calc-sources](design/calc-sources.md).

## Referencing results in prose

```markdown
The converter loses {{P_diss}} over {{A_board}} of board.
```

→ "The converter loses 0.2981 W over 1.26 in² of board."

A reference can ask for a different presentation unit, the same `| unit` form
as a calc line:

```markdown
The converter loses {{P_diss | mW}}.
```

→ "The converter loses 298.1 mW." — a unit of the wrong dimension is a build
error at the reference, never a silent fallback to the calc's own unit.

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

Add your own aliases in `refdes-project.yaml`:

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

`name = expression | unit` declares what the result must be and what unit to
present it in:

```calc
P = V_out / I_load | W
```

```
ERROR calc P: declared as W but the expression evaluates to V/A
```

Whitespace around `|` is optional, and the unit accepts everything a quantity
accepts — compounds like `W/in^2`, house units, aliases. A tolerance goes on
the expression, before the unit: `V = 12 V ± 5% | mV`.

Assertions also **pin the display unit**, which is why `P_dens = ... | W/in^2`
reports `0.2366 W/in²` rather than `236.6 mW/in²` — matching the bound it is
checked against. Use them wherever getting the dimension wrong would be
expensive.

> **Note:** the older spelling, `name : unit = expression`, is retired —
> the build reports an error naming the exact fix on every line that still
> uses it. `refdes calc-rewrite` converts a project to the `| unit` form in
> one transactional pass (it verifies every calc still evaluates to the
> same value and unit, carries baselines and seals forward, and leaves
> sealed append-only entries untouched — see its `--help`).

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
| `volt * ampere` | `1 W` |
| `millivolt / ampere` | `1 mΩ` |
| `1 / microsecond` | `1 MHz` |

But a unit you wrote yourself is never rewritten. `1.4 inch` stays inches,
`0.5 h` stays hours, `W/in^2` stays per square inch. Only compound and reciprocal
results are candidates for renaming, and only sub-products are collapsed — in
`volt*ampere/inch**2`, the `volt*ampere` becomes `W` and your `inch**2` is left
exactly as written.

Which units are candidates is set by `units.preferred` in
[`refdes-project.yaml`](schema-reference.md). Only single-symbol units belong there.

## Functions

`sqrt`, `abs`, `min`, `max`, `exp`, `ln`, `log10`.

`exp`, `ln`, and `log10` require dimensionless arguments. `min` and `max` take
any number of arguments. Trigonometric functions are **not** available — intervals
through non-monotonic functions need range analysis that is not implemented, and
silently under-wide bounds would be worse than no support.

## Project equations

A formula you retype per output, per rail, per input is a formula you will get
wrong in one of them. `equations:` is a project setting, so it lives in
[`refdes-project.yaml`](schema-reference.md), and declares named expressions
callable from any calc block on the site:

```yaml
equations:
  current_limit:
    params: [K, V, R]
    expr: K * V / R
    note: TPS1H200A datasheet p.22
```

```calc
CLIM_out1 = current_limit(2500, 0.8 V, 3.3 kohm) ± 15% | A
```

`note:` is provenance — a datasheet page, an application note — and nothing at
build time reads it. It is there so the person correcting the formula knows
where it came from.

Calling an equation is not a new evaluator: the arguments bind to `params` and
the body is evaluated exactly as if you had written it inline. Two things follow
from that:

- **Units come from the arguments.** Parameters declare no dimensions; the body's
  arithmetic has them. `current_limit` returns amps because `V / kohm` does, and
  passing `3.3 kg` where a resistance belongs is an ordinary dimensionality error
  at the call site — `declared as A but the expression evaluates to V/kg` — not a
  new error to learn.
- **Tolerances propagate.** `± 15%` on an equation result behaves exactly as it
  does on any other expression, and a tolerance carried by an argument reaches the
  result through it.

Three rules:

- An equation may call another equation. A cycle is a build error naming the path
  that closes the loop — `equation cycle: a -> b -> a` — the way a `blocked_by`
  cycle already is.
- An equation cannot shadow a built-in. `sqrt` has to mean one thing everywhere on
  the site, so redefining it is rejected rather than silently preferred.
- Arity is checked against `params` by the same call path that checks `sqrt()`
  takes its one argument: `current_limit() takes 3 argument(s) (K, V, R), got 2`.

The namespace is project-wide, like `units:`. Equations are not board-specific,
and two boards defining `current_limit` differently would create a resolution
question that needn't exist.

## Errors you will see

```
cannot add V and A — the units do not match
division by a value whose tolerance range includes zero
unknown unit 'wat'
unknown function 'sin'; available: abs, exp, ln, log10, max, min, sqrt
equation cycle: a -> b -> a
exponent must be dimensionless
declared as W but the expression evaluates to V/A
```

Every one is a build error. There is no path by which a dimensional mistake
produces a number.

## Known limitations

- **Torque reads as energy.** `N·m` and `J` are dimensionally identical, so a
  torque displays as joules, and a `| N*m` assertion does not pin it back. Every
  units library has this; none solve it without a separate notion of quantity
  kind.
- **No solving for unknowns.** Forward evaluation only. Symbolic solve is planned.
