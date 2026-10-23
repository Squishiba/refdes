# f13-1 — inline-calc release gate names the unreadable history store

Task: when the release gate's `inline_calc_results` rule fails closed on an
unreadable history store, the output must open with ONE line naming the store
and the cause, then the offenders as today.

## What I found

The contract's premise ("offenders are listed with no explanation") did not
match HEAD: `_rule_inline_calc_results` (lifecycle.py:819) returned a single
generic line ("history: inline calc freshness cannot be checked: history
store unreadable (detail)") *instead of* the per-item offenders in the
fail-closed path. Either reading of the premise lands on the same required
behavior, so I implemented the contract's required output exactly.

## Change (src/refdes/lifecycle.py only)

- `_unreadable_history_offender` -> `_unreadable_history_gate_line`: emits
  `stale inline-calc gate: cannot read the history store <path> (<error
  text>) -- failing closed`, path = `history_mod.HISTORY_DIR` (project-
  relative, `.refdes/history`, separators normalized to `/`), error text =
  `str(exc)` whitespace-collapsed (the CLI joins offenders with ", " in the
  gate table -- cli.py `_print_gate_table` -- so the row must stay one line;
  a HistoryError carries multi-line parser context).
- The except-path no longer short-circuits: on `HistoryError`/`OSError` it
  sets `frozen_captures = set()` (exemption unprovable -> every editable
  stale span adjudicated as if uncaptured, same strings as the readable
  path) and records the store line. Offender computation is now one shared
  loop; the store line is prepended, once, iff offenders is non-empty.
  Sealed/imported-only stale spans -> empty offenders -> rule passes, no
  line (store-line suppression preserved). No stale spans -> early return,
  unchanged.
- Docstring: added the sentence on the naming line.

Docs (math.md "fails closed and names the unreadable store", lifecycle.md
table + prose) now describe exactly what runs -- untouched, per contract.
Changelog fragment: changelog.d/inline-calc-gate-names-history-store.fixed.md.

## Verification

- Probe (.scratch/f13-1/probe_gate.py, 5 cases, all pass, run with
  PYTHONPATH=src:tests + repo venv pytest): OSError monkeypatch -> FAIL with
  exact named-store line first + offenders, line appears once; OSError + no
  stale span -> pass, nothing printed; readable store -> no named line,
  offenders unchanged; captured-exempt span + corrupt store (real
  HistoryError, test_lifecycle.py recipe) -> was pass, now FAIL with
  `LOG-001` offender explained by the leading line; sealed item under broken
  store stays exempt (pass).
- End-to-end: `refdes release rel-a` on a scratch project with a corrupt
  events file -- gate row `FAIL inline_calc_results  stale inline-calc gate:
  cannot read the history store .refdes/history (...) -- failing closed,
  DEC-001: inline calc Vout (items/dec.md:7)`, exit 1, not stamped.
- `tests/test_inline_calc.py`, `test_project_settings.py`,
  `test_check_severity_status.py`: 141 passed. ruff on lifecycle.py: 3
  findings, identical to HEAD (pre-existing, not touched).

## Review round (PR #368, CHANGES REQUESTED -> fixed on this branch)

- The two pre-existing test_lifecycle.py assertions flagged above are now
  updated to the contract shape (named-store line first, offender after;
  intent kept: fail closed, the item is an offender, one-row line).
- Designer's acceptance file: STORE_REL was os.path.join -> `.refdes\history`
  on Windows against the implementation's forward-slash output (contract's
  form); pinned as the literal ".refdes/history". No other os.sep-dependent
  assertion in the file (rest uses os.path.isfile / literal "items/...").
- Added test_multiline_error_text_collapses_into_one_gate_row (HistoryError
  with newlines -> the named-store line stays one row, text = whitespace-
  collapsed str(exc)); the lifecycle.py docstring already names the reason.
- Designer log corrected: tests/f13-1.cases.json was not delivered in the PR.
- Full suite at this head: `PYTHONPATH=src <venv> -m pytest -q tests/` ->
  4423 passed, 2 skipped, exit 0 (foreground, 8m02s). ruff on the touched
  test files: only findings pre-existing at base, untouched lines.

Status: done, committed on ac/f13-1/coder.
