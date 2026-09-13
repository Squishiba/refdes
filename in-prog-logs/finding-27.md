# Finding 27 — project-defined reusable equations callable from any calc block

**Status: done.** `equations:` in `refdes.yaml`, callable from any calc block.

## What the finding said, and what was already true

Read `docs/design/backlog.md` §27 first, then `calc.py`. Every claim the finding
makes about the existing machinery checked out:

- `FUNCTIONS` / `MULTI_ARG` is a working registry, and the `ast.Call` branch of
  `_eval_node` resolves the name, rejects `keywords`, checks arity, evaluates each
  argument through the same `Value` arithmetic, and produces the
  `unknown function 'x'; available: …` diagnostic.
- `evaluate(expression, env)` is already parameterised on its environment, so a
  project equation really is "bind params into an env, evaluate the stored body".
  No new evaluator, no new parser — confirmed before writing anything.

## Shape landed

```yaml
equations:
  current_limit:
    params: [K, V, R]
    expr: K * V / R
    note: TPS1H200A datasheet p.22
```

```calc
CLIM_out1 : A = current_limit(2500, 0.8 V, 3.3 kohm) ± 15%
```

- `calc.Equation` (name / params / expr / note), `calc.EQUATIONS` as the one
  project-wide namespace, `calc.set_equations()` mirroring the existing
  `set_unit_aliases()` posture.
- `calc.validate_equations()` holds the two semantic rules, and
  `set_equations()` calls it before mutating, so there is no route to a live
  registry that skips them.
- `_call_equation()` does the binding: arity checked against `params`, arguments
  evaluated in the *caller's* env, body evaluated in a fresh env of params only.
- `schema._load_equations()` validates structure (mapping, known keys, identifier
  params, non-empty parseable `expr`) and `load_project()` installs the registry
  alongside the unit config. A project with no `equations:` resets it to empty,
  so one project's equations can't leak into the next build.
- `Project.equations` carries the loaded definitions.

## The three rules

1. **Shadowing a built-in is a hard error.** `sqrt` must mean one thing
   everywhere on the site. `validate_equations` rejects a name in `FUNCTIONS`
   (and `_q`, which the lexer intercepts before any lookup).
2. **Cycles are detected and reported**, following `blocked.py`'s precedent: the
   walk names the path that closes the loop — `equation cycle: a -> b -> a` — and
   it is a config-load `SchemaError`. A runtime stack in `_call_equation` is the
   backstop for a registry populated without going through `set_equations`, so a
   cycle is a diagnostic rather than a `RecursionError`.
3. **Arity was not reimplemented.** The existing call path checks it; the new
   message names the declared parameters:
   `current_limit() takes 3 argument(s) (K, V, R), got 2`.

## The two free properties — verified, not rebuilt

- **Units from arguments.** `current_limit(2500, 0.8 V, 3.3 kohm)` is amps because
  `V / kohm` is. One wrinkle worth recording: `3.3 kg` in the resistance slot is
  *not* automatically a dimensionality error — `K * V / R` with `R` in kg yields
  `V/kg`, which is dimensionally legal. The error the finding describes is what
  the call site's own unit assertion produces: `declared as A but the expression
  evaluates to V/kg` (verified by running it). Where the body's arithmetic is what
  fails — `series(1 kohm, 3.3 kg)` over `a + b` — the ordinary
  `cannot add … the units do not match` fires inside the call. Both are tested.
- **Tolerance propagation.** `± 15%` on an equation result, and a tolerance
  carried by an argument, both propagate through `Value` arithmetic unchanged.
  Tested both directions.

## Tests (18 new, in `tests/test_calc.py`)

Evaluation-level (behind an `equation_registry` fixture that restores
`calc.EQUATIONS`): evaluates with units from arguments; composes; wrong dimension
caught by the unit assertion; wrong dimension inside the body; `±` on the result;
`±` in an argument; arity; unknown name still lists built-ins *and* equations;
shadowing rejected with the built-in still working; cycle reported at
`set_equations`; cycle reported by the runtime backstop.

Config-level: loads from `refdes.yaml` (params and `note` preserved); an equation
call in an item's calc block builds to `0.6061 A` with no errors; a project with
no `equations:` installs none; a built-in name is a `SchemaError`; a cycle is a
`SchemaError` naming `a -> b -> a`; an unparsable body is caught at load; an
unknown definition key is rejected.

**Rule-removal check:** with the shadow branch and the cycle walk stubbed out, the
four rule tests (`test_an_equation_cannot_shadow_a_builtin`,
`test_a_builtin_equation_name_in_refdes_yaml_is_an_error`,
`test_an_equation_cycle_is_reported_not_followed`,
`test_an_equation_cycle_in_refdes_yaml_is_an_error`) all fail — verified by
running them mutated, then reverting.

`python -m pytest tests/ -q` → **681 passed** (663 baseline + 18), 0 failed.

## Scope

Touched: `src/refdes/calc.py`, `src/refdes/schema.py`, `src/refdes/model.py`
(one `Project.equations` field), `tests/test_calc.py`, `docs/math.md`, this log.
Nothing outside the allowed list was needed — in particular `build.py` was not
touched: `load_project()` installs the registry, the same way it already fixes
the unit vocabulary that calc reads.

## Notes for whoever picks this up

- Registering in `load_project()` rather than `build.build()` was a scope
  decision, not a preference. If `build.py` is open again, moving the
  `calc.set_equations(project.equations)` call next to `set_unit_aliases()` is
  the tidier home for it.
- Finding 28 moves `equations:` to a different file; it moves with `units:`, and
  `_load_equations()` is the only thing that has to follow.
- Equation bodies are re-parsed on each call. Not a cost at document-build scale;
  a parsed-tree cache on `Equation` is the obvious fix if it ever becomes one.
- `ruff` is not installed in this environment, so no lint gate was run (AGENTS.md
  says a green `ruff check .` is not a valid gate here anyway).
