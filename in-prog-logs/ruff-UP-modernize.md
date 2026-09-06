# ruff UP modernise: tests/test_calc.py, tests/test_revise_migrations.py, tests/test_seal.py

## What was done

1. Ran `ruff check tests/test_calc.py tests/test_revise_migrations.py tests/test_seal.py --select UP --fix`
   (scoped to exactly the three files). `--fix` changed nothing: all 5 findings
   were UP031 (percent-format), whose fixes ruff marks unsafe/hidden.

2. Fixed the 5 remaining UP031 findings by hand, converting to f-strings:
   - `tests/test_calc.py:552-554` — `'    limit: "%s"\n' % limit`
     -> `f'    limit: "{limit}"\n'` (no literal braces; safe).
   - `tests/test_calc.py:558-567` — `"```calc\nT_j : degC = %s\n```\n" % value`
     -> `f"```calc\nT_j : degC = {value}\n```\n"` (no literal braces; safe).
   - `tests/test_revise_migrations.py:74-76` — the refdes.yaml fixture string
     contains literal `{`/`}` (YAML flow mappings). Converted to an f-string
     with every literal brace doubled: `{{ title: T, out: _site }}`,
     `{{ base: hardware, version: {version}, presets: [] }}`,
     `{{ width: 3, ledger: .refdes/ids.yaml }}`. `%d` -> `{version}` is
     value-identical: both call sites pass ints (`version=2`, `version=1`).
   - `tests/test_revise_migrations.py:81-85` — `"    equivalent: [%s]\n" % target_id`
     -> `f"    equivalent: [{target_id}]\n"` (no literal braces; safe).
   - `tests/test_seal.py:130` — `"defaults: { type: log, prefix: %s }\nitems: []\n" % prefix`
     -> `f"defaults: {{ type: log, prefix: {prefix} }}\nitems: []\n"`
     (literal braces doubled).

   No noqa suppressions were needed — all five conversions were safe once
   literal braces were doubled.

## Difficulties

- The shell whitelist refused `cd`, `where`, `uv`, env-var prefixes, and the
  venv's `python.exe`, so commands were run with absolute paths.
- The default interpreter (Python 3.14.7) had no pytest/deps; the project
  venv at C:/Users/Jared/Refdes/.venv was not on the whitelist. The user
  installed pytest into the default interpreter; I then installed the
  project's existing runtime deps (pyyaml, jinja2, pint, markdown-it-py) and
  the dev dep jsonschema into the same interpreter so the suite could run.
  No project dependencies were added or changed.

## Verification

- `ruff check tests/test_calc.py tests/test_revise_migrations.py tests/test_seal.py --select UP`
  -> "All checks passed!" (0 findings).
- `pytest -q tests` -> 650 passed, 0 failed (25.88s).

## Status

Finished. Only the three named test files were modified (plus this log).
