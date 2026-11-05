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

## Implementation (DC-1-impl)

- `tools/docs_context/refs.py` (single module, no `__init__.py` -- the
  tests' namespace-package import off `tools/` matches
  `tests/test_pr_size.py` exactly); changelog fragment added.
- Two test-author bugs found (report carries the details; tests NOT
  edited per the hard rule): `refs_of()` passes the *ref* kind to
  `block_at()`, which matches it against *block* kinds, so every test
  routing through it fails with "no code_ref block starting at line 3"
  for any implementation (it contradicts the block-kind test); and
  `src/../outside.txt` resolves *inside* the fixture repo
  (`repo/outside.txt`), so `{"error": "outside repo"}` is unprovable
  lexically. Handled the second with a strict rule the spec's safety
  posture supports: any ref path with a `..` segment is refused as
  "outside repo" before touching the filesystem, which makes all
  affected assertions pass.
- Proof of conformance with the intended spec: a `.scratch/` copy of the
  test file with only `refs_of()` fixed (block found by start line)
  runs 42/42 green; the unmodified file runs 12 passed / 30 failed with
  every failure the one helper AssertionError.
- Real-docs validation: `docs/navis.md` (8 links, 18 commands),
  `docs/browser-editor.md` (10 links, 6 commands, 2 file refs),
  `docs/cli-reference.md` (48 links, 141 commands, 40 file refs; one
  `file_ref` `.git/hooks/pre-commit` correctly refused, 21 file refs
  legitimately missing in this repo: `.refdes/*` outputs). Three cards
  spot-checked against ground truth (help byte-identical at
  COLUMNS=100, anchor excerpt matches, file window matches).
- Fidelity fixes found only by running on the real docs: flag-shaped
  tokens (`-o/--out`) are no longer file refs; page links with no
  anchor are not flagged broken; heading slugs html-escape like the
  site's rendered text (the `#...-lt-ref-gt` anchors).
