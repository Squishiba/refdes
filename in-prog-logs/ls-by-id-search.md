# `refdes ls <ID>` — free-text search should reach the item's own id

Source of the finding: `in-prog-logs/user-sim-release-gate-run1.md`, L5.
The user-simulation run hit `refdes ls REQ-SYS-001` returning
"no items match" immediately after `refdes id` had printed that id. Not a
docs-vs-code mismatch — `ls --help` really did say "matched against title and
tags" — just a query surface that misses the single most obvious query.

## What changed

- `src/refdes/cli.py`, `cmd_ls`: the free-text haystack is now
  `" ".join([item.id, item.title, *tags]).lower()` (was title + tags). One
  line. Matching rules are unchanged otherwise — substring, case-insensitive,
  no exact-id-only mode — so `REQ-SYS-001`, `req-sys-001` and `req-sys-0` all
  behave exactly like a title or tag substring would.
- `src/refdes/cli.py`, `ls` subparser: help text is now
  "free text, matched against id, title and tags: (case-insensitive)".
- `cmd_ls` docstring: says id/title/tags, and why the id is in there (the
  query right after `refdes id` prints one is the id itself).
- `docs/cli-reference.md` §`refdes ls`: the `QUERY ...` table row and the
  free-text prose paragraph updated to include the id, with an example
  (`refdes ls req-sys-0`) and a note that there is no exact-id-only mode.
  Leaving that stale would have re-created the docs-vs-behaviour drift the
  release-gate run keeps finding.

## Tests

`tests/test_blocks.py`, in the existing `ls (finding 9)` section:

- `test_ls_free_text_matches_a_full_id` — `ls DEC-001` returns DEC-001 and
  nothing else. No title or tag in the fixture contains "DEC-001", so a hit
  can only come from the id.
- `test_ls_free_text_matches_a_partial_lowercased_id` — `ls dec-00` returns
  the three decisions and not REQ-001/CMP-001: substring + case-insensitivity
  on ids.
- `test_ls_help_says_free_text_matches_ids` — runs `ls --help` and asserts the
  help text names the id (regex, because argparse wraps at terminal width).
  Guards against the help going stale relative to the code again.

## Verification

- `pytest tests/test_blocks.py -q` → 40 passed.
- Full suite `pytest tests -q` → 2628 passed, 2 skipped.
- `ruff check src/refdes/cli.py tests/test_blocks.py` → clean (scoped to the
  touched files per `AGENTS.md`; repo-wide `ruff check .` is not a green
  baseline).
- Real end-to-end run, `.scratch/ls_id_probe.py` (throwaway project under
  `.scratch/ls-id-project/`):

  ```
  $ refdes ls REQ-SYS-001
  REQ-SYS-001  requirement  Input ripple stays under 50 mV.
  [exit=0]
  $ refdes ls req-sys-0
  REQ-SYS-001  requirement  Input ripple stays under 50 mV.
  REQ-SYS-002  requirement  Bulk decoupling chosen.
  [exit=0]
  ```

## Deliberately out of scope

- `src/refdes/serve/filters.py` — the browser editor's free-text filter still
  matches title + tags only. The task scoped this to the CLI, and the serve
  side has its own facet-counting semantics; widening it is a separate,
  arguable call worth its own fragment if we want CLI/editor parity.
- `docs/design/browser-editor.md` describes `ls`'s filtering as it was when
  that design was written (its `cli.py:441-494` line refs were already stale
  before this change). Left as the historical record rather than half-updated.

## Status

Done. Changelog fragment: `changelog.d/ls-free-text-matches-ids.changed.md`.
