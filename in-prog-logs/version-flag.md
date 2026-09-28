# `refdes --version` (finding L2 from the release-gate user simulation)

Task: `refdes --version` did not exist — it fell through to the top-level
usage dump with a non-zero exit, while the docs advise that "a later `refdes`
may write a higher number here; that is expected" with no way to ask the tool
which version you are holding. Source finding:
`in-prog-logs/user-sim-release-gate-run1.md`, "L2 — no `--version`".

Status: **finished**.

## What I verified first

- `pyproject.toml` declares `version = "0.5.0"`; `src/refdes/__init__.py`
  hardcoded `__version__ = "0.1.0"`. Confirmed both by reading the files.
- `grep -rn "__version__" src/ tests/` found exactly two hits: the stale
  constant itself, and `sources.py:947`, which reads `pypdf`'s own
  `__version__` and has nothing to do with ours. Nothing in `src/`, `tests/`,
  `docs/`, or `release.py` consumed `refdes.__version__`.
- The environment before the change: `python -m pip show refdes` → `0.5.0`,
  and `importlib.metadata.version("refdes")` → `0.5.0`, while
  `refdes.__version__` would have said `0.1.0`. That is the drift the task
  warned about, live in the checkout.
- Per `AGENTS.md` ("before writing any claim about CLI behavior, run the
  actual command"), every behavior claimed below was run, not recalled. The
  venv's `refdes` script points at an editable install whose target
  (`/tmp/w-pr59-merge/src`) no longer exists, so I exercised the working tree
  code directly with
  `python -c "import sys; sys.path.insert(0,'src'); from refdes.cli import main; sys.exit(main(['--version']))"`.

## Decisions

**`__version__`: derived, not deleted.** Nothing depended on the constant, so
deleting it outright was defensible. I kept the name and made it read the
installed distribution's metadata instead, because `pkg.__version__` is a
convention people and tooling reach for, and a *correct* derived attribute
costs nothing extra now that the CLI needs the same lookup. One source of
truth (`pyproject.toml` → installed metadata), no drift possible. A test
asserts `refdes.__version__ == importlib.metadata.version("refdes")`, so
reintroducing a hardcoded constant fails the suite.

**The CLI never reads the constant.** `refdes.cli._version_line()` calls
`refdes.get_version()`, which is `importlib.metadata.version("refdes")`. The
flag's output therefore cannot inherit a stale value even if someone later
re-adds one.

**`argparse`'s own `action="version"`** handles print-and-exit-0, so no custom
exit handling. `-V` and `--version` both map to it. The version string is
computed when the parser is built — one metadata lookup per process, ~1 ms,
in exchange for keeping the argument declaration plain.

**Not-installed fallback.** `PackageNotFoundError` is caught and the flag
prints `refdes (version unknown -- not installed as a package)`, still exit 0.
`__init__.__version__` falls back to the PEP 440 local version
`0.0.0+unknown` in the same situation.

## Changes

- `src/refdes/__init__.py` — stale `__version__ = "0.1.0"` replaced by
  `get_version()` plus a metadata-derived `__version__`.
- `src/refdes/cli.py` — `_version_line()` helper; `-V`/`--version` on the
  top-level parser, before `-c`. Import block reshuffled by
  `ruff check --select I` (it combines `from . import get_version, standards`);
  mechanical, no behavior change.
- `tests/test_version_flag.py` — new: long flag and short flag print
  `refdes <installed version>` and exit 0; nothing on stderr; works from an
  empty directory with no `refdes-project.yaml` and never prints a usage
  dump; `--version` is advertised in `--help`; the not-installed fallback
  prints an honest line and exits 0 with no traceback; `refdes.__version__`
  matches the installed metadata. The metadata-dependent tests skip rather
  than fail if `refdes` is not installed as a package at all.
- `docs/cli-reference.md` — `-V`/`--version` in the usage line and the global
  option table.
- `docs/getting-started.md` — one sentence at the `standard.version`
  paragraph telling the reader to ask the tool with `refdes --version`, which
  is the advice the finding said was missing.
- `changelog.d/version-flag.added.md` — fragment.

## Verification

- `python -m pytest tests/test_version_flag.py -q` → 6 passed.
- `python -c "... main(['--version'])"` → prints `refdes 0.5.0`, exit 0. Same
  for `-V`. `main(['--help'])` usage line now reads
  `usage: refdes [-h] [-V] [-c CONFIG] [--no-write] {...}`.
- `ruff check --select E9,F src tests` (the CI gate) → all checks passed.
  `ruff check --select I` on the three touched Python files → clean; the
  repo's 24 other pre-existing `I001` findings were left alone per
  `AGENTS.md`.
- Full suite: see the note below.

## Follow-ups noticed, not taken

- `editors/vscode/package.json` still says `"version": "0.1.0"`. That is the
  extension's own version, not the package's, so it is out of scope here — but
  if the extension is meant to track `refdes`, nothing keeps them in step.
