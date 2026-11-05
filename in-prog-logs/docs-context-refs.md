# docs context refs — slice DC-1 (tests only)

Task: contract tests for the planned `tools/docs_context/refs.py` (docs
"reference cards" library + JSON CLI). Test-author slice only: nothing was
created under `tools/` — the implementer continues on this branch.

## What landed

- `tests/test_docs_context_refs.py` (42 tests), imported by file path off
  `tools/` exactly like `tests/test_pr_size.py` does (namespace-package
  import, no `__init__.py` needed, no sys.path leakage).
- Spec coverage: `parse_doc` block kinds/ranges (built on
  `refdes.build._markdown_parser()` — verified token `map` ranges for
  heading/paragraph/list_item/table/fence against the real parser before
  writing the fixtures); code_ref grammar incl. all mandated negatives
  (`key: value`, `12:30`, `localhost:8080`, `std::vector`,
  `http://host:80/x`, `a:b`, `file.py`, `e.g.:3`, `v1.2:3`); file_ref;
  command verbs (flag/quote/placeholder/path-like stops, global-flag
  skip, console `$` lines, `# comment` tails); link fields; offsets
  invariant `block.text[start:end] == raw`.
- Cards: ±5 clamped windows, `cited`, missing file, past-EOF
  `in_range`, `symbols_missing` heuristic (excludes ref text, command
  words; `alpha42` present / `ZZZ_missing` absent).
- Safety: `../`, absolute (synthetic `Ref`), `.git/`, symlink-outside
  (skipif Windows), binary (`\x00`), >2 MB sparse — card is an `error`
  and the three path-escape cases run with `builtins.open` monkeypatched
  to raise, proving the file is never opened.
- Links: site slug rules replicated exactly per `tests/test_docs_anchors.py`
  (underscore heading case, duplicate-heading `-2`), excerpt = first 8
  text lines, `#anchor`-only against the doc itself, external cards
  never fetched (`socket.socket` monkeypatched to raise).
- Commands: `known` via the argparse tree; negatives (`refdes rm`,
  `refdes navis nope`, `; | & $ ( ` metachars) tested with
  `subprocess.run`/`Popen` monkeypatched to raise; the known
  `navis archive` path asserts exactly one list-argv call, no
  `shell=True`, `PYTHONPATH=<repo>/src`, `COLUMNS=100`, `timeout=10`,
  4000-char truncation.
- CLI: JSON shape, exit 2 + stderr on missing doc, byte-identical
  output on rerun, and a smoke run over the real `docs/navis.md`.

## Notes

- RED by design: collection fails with
  `ModuleNotFoundError: No module named 'docs_context'` (exit 2); all 42
  tests fail for exactly that reason. Full suite not run (overridden for
  this slice).
- Cross-platform: fixture writes use `newline=""`, binary via
  `write_bytes`/`truncate`, symlink test skips on Windows, CLI assertions
  normalise separators, no raw-`\n` byte assertions on text-mode files.
- The `known` tests assume the implementer calls `subprocess.run` via the
  module (`refs.subprocess.run`-style) as the spec dictates.
