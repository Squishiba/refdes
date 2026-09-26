# build-crash-fixes — two source bugs from the docs audits

Two bugs, one commit each, both found by reading the docs against the running
tool rather than by a test. Each commit carries tests that fail on the unfixed
code (run before the fix, recorded below) and its own `changelog.d` fragment.

---

## Bug 1 — `refdes build` crashes on a calc line that leaves the reals

### Symptom (reproduced before touching anything)

`v = sqrt(-1)` in a ```calc fence in an item, then `refdes build`:

```
File "src/refdes/build.py", line 1206, in _run_item_calcs
    line.result = calc.format_value(outcome.value, project.sigfigs)
File "src/refdes/calc.py", line 802, in format_quantity
    return _sigfig_str(float(q.magnitude), digits)
TypeError: float() argument must be a string or a real number, not 'complex'
```

No file, no line, no mention of the square root, and the whole command dies.
Fixture: `.scratch/repro1/` (`refdes-project.yaml`, `refdes-schema.yaml` with a
`decision` type, `items/part.md`).

### Why

`calc.FUNCTIONS["sqrt"]` was `_monotonic(lambda q: q**0.5, "sqrt")`. pint does not
refuse a negative base — `(-1) ** 0.5` is `6.1e-17+1j`, a *complex* Quantity — so
`evaluate_block` recorded a value and returned no error. The crash happened one
stage later, in `build._run_item_calcs`, at `calc.format_value(...)`, which sits
**outside** the `try/except` in `evaluate_block` that turns an evaluation failure
into a line error. That is why it was a traceback and not a diagnostic: nothing
was there to catch it.

Probed with `calc.evaluate` on the unfixed code, to find every other route out of
the reals rather than only the reported one:

| expression | before |
| --- | --- |
| `sqrt(-1)` | complex Quantity -> **build crash** in `format_value` |
| `sqrt(-1 m^2)` | complex Quantity -> **build crash** in `format_value` |
| `ln(0)`, `ln(-1)` | raw `ValueError: expected a positive input` |
| `log10(0)`, `log10(-1)` | raw `ValueError: expected a positive input` |
| `exp(10000)` | raw `OverflowError: math range error` |
| `(-4) ** 0.5`, `(-8) ** (1/3)` | raw `TypeError: '<' not supported between 'complex' and 'complex'` (from `_span`'s `min`) |
| `0 ** -1` | raw `ZeroDivisionError: zero to a negative power` |
| `2 ** 10000` | raw `OverflowError` |
| `1 / 0` | already a `CalcError` — the reference case for what "right" looks like |

The `ln`/`exp`/`**` ones were already *reported* (the generic
`except Exception` in `evaluate_block` turns them into line errors) but with
whatever the exception happened to say. `sqrt(-1)` and the fractional powers were
the ones that actually crashed or produced nonsense.

A range that dips below zero was a second crash route, same root cause: `v = 5 ± 6`
is `[-1, 11]`; the nominal `sqrt(5)` is real, the low bound is not, and
`format_bounds` is exactly where it detonated. So a guard on the nominal value
alone would not have been enough.

### Fix (`src/refdes/calc.py`)

One rule, stated in the new "domain" section of the module: *a value that is not a
real number is a `CalcError`, raised where the argument is still in hand, and
never a value handed on to be formatted.*

- `_is_imaginary(q)` — one attribute read (`magnitude.imag`) that covers float,
  int and complex; a real negative result is not caught by it, which is correct.
- `_real(q, what, fix)` — the choke point, applied to **every corner**, not just
  the nominal.
- `_fn_sqrt` replaces the `_monotonic(...)` entry: an explicit `_is_negative`
  check on `lo`/`nom`/`hi` that names the value that is wrong, with `_real` behind
  it as the backstop for the cases pint refuses to compare (offset units).
- `_dimensionless(fn, name, fix)` evaluates corner by corner under its own
  `try`, so `ln(2 ± 2)` is reported against the low bound that actually failed
  rather than the nominal value that did not.
- `_power` wraps the `**` in `try`/`except (ValueError, OverflowError,
  ZeroDivisionError)` and passes the result through `_real`.

### Fix (`src/refdes/build.py`)

`build._run_item_calcs` now formats inside a `try` and reports anything that gets
out as a calc error on the same line, with `line.result`/`line.bounds` left empty
and the item marked failed. This is the structural half of the fix: the formatter
runs on a value the evaluator already accepted, so a failure there must still be
a diagnostic rather than the end of the command.

### Tests (`tests/test_calc_domain.py`, new — 41 cases)

- `DOMAIN_CASES` — ten expressions, one per route out of the reals, run through
  three layers: `calc.evaluate` raises `CalcError`; `evaluate_block` puts the
  error on the right line and leaves the surrounding lines evaluating; the build
  produces a diagnostic with `file`, `line` and `item_id`, and no result.
- Wording: `sqrt` says *negative value* and *square root*; the logs say
  *positive argument*; the message names the offending value.
- The range case: `v = 5 ± 6` then `sqrt(v)` is caught at the root.
- `refdes build` through the CLI returns 1 on `v = sqrt(-1)`.
- The safety net: `calc.format_value` monkeypatched to raise `TypeError` — the
  build reports a diagnostic rather than propagating.

**Failed before the fix, all 41.** Recorded reasons: `DID NOT RAISE CalcError` for
`sqrt(-1)` and `sqrt(-1 m^2)` (the complex value passed evaluation cleanly), the
raw `ValueError`/`OverflowError`/`TypeError` for the rest, the `TypeError`
escaping `build_mod.build` in the two crash-shaped tests, and the
`test_a_formatter_failure_is_still_a_diagnostic_not_a_crash` traceback at
`build.py:1206` — the original bug, reproduced in miniature.

### Verified after the fix

`refdes build` on `.scratch/repro1/` with every domain failure on one item:

```
ERROR items/part.md:10 [DEC-001] — calc 'a': sqrt() of a negative value (-1) is not a real number — the square root of a negative number has no real value; check the sign of the argument
ERROR items/part.md:11 [DEC-001] — calc 'b': ln() needs a positive argument, got 0 — a logarithm is undefined at zero and for negative values
ERROR items/part.md:12 [DEC-001] — calc 'c': log10() needs a positive argument, got -1 — a logarithm is undefined at zero and for negative values
ERROR items/part.md:13 [DEC-001] — calc 'd': exp() overflowed on 10000 — the result is beyond the largest number a float can hold
ERROR items/part.md:14 [DEC-001] — calc 'e': `-4 ** 0.5` is not a real number — a fractional power of a negative number has no real value; check the sign of the base
ERROR items/part.md:15 [DEC-001] — calc 'f': `0 ** -1` is undefined — zero to a negative power is not a number
ERROR items/part.md:16 [DEC-001] — calc 'g': `2 ** 10000` overflowed — the result is beyond the largest number a float can hold
```

Exit 1 (2 with `--keep-going`, as documented). `docs/math.md`'s "Errors you will
see" section lists the new messages and says why a domain failure can never
produce a result. Full suite: 2274 passed.
