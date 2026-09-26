# Micro sign on Linux: `60 µA` vs `60 μA`

Task: `tests/test_compare_block.py::test_compare_renders_pass_and_fail_columns`
fails on this server, green in CI and on Windows. Which side is environment
dependent, and is the fix small and clear?

## Symptom

`/home/jorb/work/venv-refdes/bin/python -m pytest -q tests/test_compare_block.py`
→ 1 failed, 11 passed. The cell for `I_q` of `CMP-PWR-014` renders `60 μA`
(U+03BC GREEK SMALL LETTER MU); the test wants `60 µA` (U+00B5 MICRO SIGN).
Same in the full suite (1 failed, 2231 passed, 1 skipped) — not an ordering or
fixture-pollution effect, and the *only* failure in the suite.

Codepoints, from the rendered page and from pint directly:

```
rendered cell      '60 μA'   ['0x3bc']
pint 0.26.1        f"{Q(60,'uA').units:~P}"  ->  '60 μA'
pint 0.25.3        f"{Q(60,'uA').units:~P}"  ->  '60 µA'
```

## The rendered string comes from pint, not from refdes

`src/refdes/calc.py:798 format_quantity()` builds the cell as
`f"{_sigfig_str(...)} {q.units:~P}"` — the `:~P` (short pretty) format spec is
pint's, so the *unit spelling* is whatever pint's registry says the symbol is.
`{{compare}}` renders `item.calc_values`, which is `format_value` output
(`src/refdes/blocks.py:736` reads the formatted string; the block never touches
pint). Nothing in `src/` ever chooses between the two micro code points: the one
`replace()` that mentions them is `calc.py:356 __to_pint_units()`, which is the
*input* path (`µ` → `μ` before pint parses), and by design both spellings parse
to the same quantity.

## The variable is the pint version, and Python version picks it

`pint/default_en.txt` line 75, the alias list after `micro- = 1e-6 =`, per
release (read out of the wheels):

| pint   | Requires-Python | canonical micro symbol |
|--------|-----------------|------------------------|
| 0.24.4 | >=3.9           | U+00B5 `µ`             |
| 0.25   | >=3.11          | U+00B5 `µ`             |
| 0.25.3 | >=3.11          | U+00B5 `µ`             |
| 0.26   | **>=3.12**      | U+03BC `μ`             |
| 0.26.1 | **>=3.12**      | U+03BC `μ`             |

So the swap and the Python floor landed in the same release, which is why it
looks platform-shaped and is not: `.github/workflows/tests.yml` pins
`python-version: "3.11"` and then `pip install -e ".[dev]"` unpinned, so CI
resolves the newest pint that supports 3.11 = **0.25.3** (`gh run view
36208036285 --log`: `pint-0.25.3` on both ubuntu-latest and windows-latest).
This server runs 3.13.5, so it gets **0.26.1** and the other spelling.

Consequences worth being explicit about:

- It is not Linux and not Python 3.13's string handling. Windows on 3.13 would
  fail identically; so would Linux in CI if `tests.yml` moved to a 3.12+
  interpreter.
- "It passes in CI" was true only because CI's interpreter is too old to
  install the pint that changed it. The last green Tests run on `main`
  (2026-09-26T01:19:32Z, run 36208036285) is green *with pint 0.25.3*.
- Reproduced by version swap, not by guessing: `pip install pint==0.25.3` in the
  task venv → whole suite green including this test; back to 0.26.1 → this test
  red again. (venv restored to 0.26.1 afterwards.)

## Which side is wrong

The test expectation is *not* the odd one out; it agrees with the project's own
documented display.

- `docs/design/candidate-parts.md` §7.4 renders the `{{compare}}` table — the
  one this test reproduces "cell for cell" — with `60 µA`, U+00B5. Same file,
  same cell. (That table is a markdown illustration rather than a byte-exact
  render: it re-spells the headers `≥ 3 A` / `≤ 500 µA`, which is exactly why
  the test expects the *authored* `>= 3 A` / `<= 500 uA` instead. It is still the
  only statement anywhere in the repo of what a micro value displays as.)
- `docs/math.md` "Writing units": all three of `u`, `µ`, `μ` are accepted input;
  nothing promises a library-chosen output spelling. The neighbouring `mil`
  paragraph is the precedent for display being the library's symbol ("They
  display as `th` (thou)") — but that is an *alias* refdes chose, not a codepoint
  the library may re-order between releases.
- SI (and the Unicode Consortium's own advice for the symbol) is U+00B5 MICRO
  SIGN; U+03BC is the Greek letter mu, a different code point that merely looks
  the same. `calc.py`'s own lexer treats them as two distinct characters
  (`_SEGMENT` carries both).
- The test is not the only place that would break: any site built on a 3.12+
  interpreter published a different byte for the same source, and a page could
  print `60 µA` in the table and `60 μA` in the error beneath it (the three
  diagnostic messages in `calc.py` formatted units inline, separately from
  `format_quantity`).

So: the code was delegating a byte of its own output to a transitive dependency
whose value changed under it. Hard-coding `\u03bc` in the test would only move
the failure to CI, and relaxing the test to "accept either" would bless a build
that is not reproducible. The small, clear fix is to make refdes own the
character.

## Fix

`src/refdes/calc.py`: new `_display_units()` (the display counterpart of the
existing input-side `_to_pint_units()`), used at all five places a unit is
printed — `format_quantity` (2), `_binary`'s dimensionality error, the
`_dimensionless` wrapper's message, and `convert_value`'s declaration error.
Values and diagnostics now agree by construction.

`tests/test_calc.py`: new "micro sign" section — all three input spellings
(`uF`, `µF`, `μF`) format to `47 µF` with no U+03BC anywhere, and the three
diagnostic messages are pinned to the same spelling. `test_compare_block.py` is
untouched: its expectation was right all along and now holds on both pints.

`docs/math.md` "Writing units" gains the output rule next to the input rule.

`changelog.d/micro-sign-display.fixed.md` added.

## Verification

- `pytest -q` under pint **0.26.1** (this server, Python 3.13.5): 2238 passed,
  1 skipped.
- `pytest -q` under pint **0.25.3** (what CI resolves on 3.11): 2238 passed,
  1 skipped. venv left on 0.26.1.
- `ruff check --select E9,F src tests`: clean.

## Not touched / worth knowing

- The limit in a bound's header is still rendered as authored, never reparsed
  (`{{compare}}`'s "never evaluates a limit" rule), which is why the same table
  shows `<= 500 uA` in the header and `µA` in a value. Unchanged, and correct:
  the header is the author's text, the value is a computed quantity.
- `pyproject.toml` still says `pint>=0.23`. The fix makes that floor honest
  again (0.23 through 0.26 all render the same now), but no upper bound was
  added — none is needed for this to be reproducible.
- Nothing in this repo's own `items/` or `docs-site/` holds a micro-scale calc
  value, so the built docs are byte-identical before and after.
