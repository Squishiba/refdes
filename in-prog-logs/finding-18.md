# Finding 18 — unit characters after the first char, and `%` outside tolerances

## Bugs

Both in the calc lexer's unit pattern (`src/refdes/calc.py`):

1. `_SEGMENT` listed `Ω`, `µ` (U+00B5), `μ` (U+03BC) and `°` only in the
   leading character class; the continuation class was `[A-Za-z0-9_]*`. A
   unit could *start* with these but never *contain* them after the first
   character — so bare `Ω` parsed while `kΩ` / `MΩ`, the normal spelling
   for prefixed resistances, failed with a raw `invalid syntax`.
2. `%` was reachable only through `PERCENT_RE` in the tolerance pre-parse
   (`evaluate_assignment`), so `± 15%` worked but `85 %` or `100 V * 5 %`
   anywhere else failed with a raw Python `invalid syntax` error.

## Fix

- `_SEGMENT` continuation class is now `[A-Za-z0-9_Ωµμ°]*` (both mu
  characters kept — they are distinct codepoints and the code listed both).
- `_UNIT_RUN` admits `%` as its own alternative:
  `(?:{_SEGMENT}(?:[/·]{_SEGMENT})*|%)` — not a segment character, so `%`
  cannot leak into the middle of an ordinary unit.
- The one SyntaxError escape in `evaluate` now names the offending
  expression: `could not parse expression '3.3 V/': invalid syntax`.
  Error handling otherwise untouched.

`PERCENT_RE` still runs as the tolerance pre-parse, so `± 15%` keeps its
"15% of the value" meaning; the new `%` alternative only applies when the
pre-parse did not already consume it.

## Verification

- `python -m pytest tests/ -q` → 655 passed (650 pre-existing + 5 new), 0 failed.
- New tests in `tests/test_calc.py`: `kΩ`/`MΩ` units, `85 %`,
  `100 V * 5 %`, `± 15%` tolerance regression, malformed-unit error text.
- `docs/math.md` did not document the old limitation, so it is unchanged.
