# Task: remove unused `import yaml` in schema.py and standards.py

Status: finished.

## What was done

- Verified `ruff check --select F401 src/refdes/schema.py src/refdes/standards.py`
  reports `import yaml` unused in both files (pre-existing finding).
- Confirmed each import is truly unused:
  - `yaml.` attribute access: none in either file (both already load YAML via
    `from .parse import yaml_safe_load`).
  - Re-exports: no `from .schema import yaml` / `from .standards import yaml`,
    no `import *`, no `schema_mod.yaml`/`standards_mod.yaml`/`schema.yaml`/
    `standards.yaml` attribute access anywhere in `src/` or `tests/` (module
    aliases in adopt.py/revise.py/tests only use other attributes). All
    `schema.yaml`/`standards.yaml` hits are string literals like
    "refdes-schema.yaml".
- Removed the two `import yaml` lines.
- `ruff check --select E9,F src/refdes/schema.py src/refdes/standards.py`: passes.
- Full suite: `python -m pytest -q` -> 1368 passed.

## Notes

- No changelog.d fragment added: the change is internal-only (removing an
  unused import), and per changelog.d/README.md fragments exist for
  user-visible behavior ("what changed and what they must do about it").
  Reported this to the orchestrator.
- Merged origin/main first (branch was already up to date).

## Files changed

- src/refdes/schema.py (2 lines deleted)
- src/refdes/standards.py (2 lines deleted)