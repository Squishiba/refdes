# cfgsplit-p2-helpers — migrate tests/helpers.py to the two-file config

## Base

- Branch `ao/refdes-50/root`, fast-forwarded with `git merge --ff-only feat/config-split`
  onto `6bbe0b2` ("tests: migrate boards/blocks/nav/pages fixtures to the two-file
  config"). Confirmed HEAD == 6bbe0b2 before touching anything.

## Import-direction check (done first, as instructed)

`tests/conftest.py` line 20 does `from helpers import (...)` at module level, and
`write_project_config` is defined *below* that import in conftest. So a module-level
`from conftest import write_project_config` in helpers.py would be a genuine circular
import: pytest imports conftest -> conftest imports helpers -> helpers asks conftest for
`write_project_config`, which does not exist yet on the partially-initialized module ->
ImportError.

**Decision:** import `write_project_config` *inside* the two functions that need it,
with a comment explaining why. By call time pytest has fully loaded conftest, so the
local import resolves. This keeps a single source of truth for the split logic instead
of duplicating it in helpers.py. (The pilot's test modules, e.g. test_boards.py, use a
module-level `from conftest import write_project_config`; they can because they are
imported after conftest finishes — helpers.py cannot.)

## Sites changed (tests/helpers.py only)

`grep -n "refdes.yaml" tests/helpers.py` found exactly the two sites named in the
task, no others:

1. `_numeric_hint_project` (was line 113):
   `(tmp_path / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")`
   -> `write_project_config(tmp_path, NUMERIC_HINT_SCHEMA)`
2. `_check_severity_project` (was line 203):
   `(tmp_path / "refdes.yaml").write_text(CHECK_SEVERITY_SCHEMA, encoding="utf-8")`
   -> `write_project_config(tmp_path, CHECK_SEVERITY_SCHEMA)`

Both constants (NUMERIC_HINT_SCHEMA, CHECK_SEVERITY_SCHEMA) are unchanged; the helper
splits them by top-level key into `refdes-project.yaml` + `refdes-schema.yaml`. Neither
site loads by explicit path immediately after writing (both rely on discovery from the
tmp root), so the returned-settings-path one-liner was not needed.

## Verification

- `grep -n "refdes.yaml" tests/helpers.py` -> no matches.
- Pilot modules: `python -m pytest tests/test_boards.py tests/test_blocks.py
  tests/test_nav.py tests/test_pages.py -q` -> see final result below.
- Full suite: `python -m pytest tests/ -q` -> failure count reported below (was 419).

## Results

- Pilot modules: 80 passed.
- Full suite: 388 failed, 290 passed, 13 errors (was 419 failed) — down 31.
- `git status --short` before commit: only `tests/helpers.py` and this log.

## Commit

`tests: migrate the shared helpers fixtures to the two-file config` (backlog finding
28). Not pushed.
