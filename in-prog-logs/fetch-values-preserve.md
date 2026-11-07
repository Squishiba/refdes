# fetch --update prunes unrecognized `values:` keys — test slice FETCH-VALUES-tests

Tests-only slice: new file `tests/test_fetch_values_preserve.py` (6 tests, all
red on main `3cba4b01`); the tree carries nothing else.

## Reproduced first (worktree `.scratch/fvp/`, `rd.sh` asserts `refdes.__file__`
resolves into this worktree's `src`, `refdes 0.5.0`)

Tiny project: `refdes-project.yaml` (`site:` only), a `decision` type with a
`citations` field in `refdes-schema.yaml`, `datasheet.csv` =
`key,value\nV,5.0\n`, one item citing it with the fence
```calc\nV = source("datasheet.csv", "V") | V\n```.

1. `fetch --path datasheet.csv` → `extracted datasheet.csv V = 5.0`, the row
   pins `values: {V: {reader: csv, value: '5.0'}}`.
2. Hand-insert `Q: {reader: csv, value: '9.0'}` above `V`.
3. `fetch --path datasheet.csv --update` → exit 0, stdout is only the
   `fetched … hash-only` line and `1 citation(s) processed, 0 failed`. Diff of
   `.refdes/citations.yaml`:

```diff
-    fetched: '2026-11-06T06:38:43Z'
+    fetched: '2026-11-06T06:39:00Z'
     sha256: 7469b4c8307904c69fed25ccf5885f36362e72d926c181ea0b635f1f585cec74
     values:
-      Q:
-        reader: csv
-        value: '9.0'
       V:
         reader: csv
         value: '5.0'
```

4. `check` → `1 items, 0 errors, 0 warnings`, exit 0. Silent loss confirmed.
5. Extra leg the probe did not pin: a **plain** `fetch --path datasheet.csv`
   over unchanged bytes prunes `Q` the same way (same diff, plus the
   `fetched:` re-stamp).

## Decision: REPORT the removal, keep the prune (not the task's preferred KEEP)

"Unrecognized" resolves to *a key no `source()` span references any more* — the
only thing the fetch can see: both prune sites extract `source_keys` and write
exactly that map (`fetch_all`'s rebuild at `citations.py:3051-3114`,
`_refresh_pinned_sources` at `:2339-2393`, which also pops the whole map when no
span keys it, line 2349). Keeping such a key collides head-on with code and
design that say pruning it is the point:

- `citations.py:2347-2351` pops the whole `values:` map with the comment
  "nothing cites a key from this file any more".
- `citations.py:2421-2424` `stage_source_pins`' docstring: "the whole-map
  replacement `_refresh_pinned_sources` does is correct for a fetch that walked
  every body in the project and wrong for one key from one item".
- `docs/design/calc-sources.md:534-538` (fetch collects all `source()` uses,
  replaces that path's record) and the matrix row at :558 ("`--update` …
  Replace file hash and all values"). The record's documented content is
  exactly the keys in use; the sections analogue at `citations.py:3061-3066`
  says the same for `sections:` ("a section nobody cites any more goes with the
  bytes it was found in").

So the hand-inserted `Q` is, by inspection, a stale pin, and the documented
rule removes it. Nothing in the code, the tests, or the design doc sanctions
*silence*: `_diff_source_values` (`citations.py:2312-2336`) reports only keys
present in the NEW map, so a key that leaves the map is invisible by
construction. The least destructive consistent behaviour is therefore
**report the loss, naming the file and the key, on a run that still exits 0**.
Nothing in `check` reads a key no span names (`citations.py:1559` looks one key
up on demand) and the validator only requires `values` to be a mapping
(`:1127-1132`), so the key is inert while present and its removal moves no hash —
purely informational, which is what makes a report the right severity.

## The tests (all red on main for the same behavioural reason)

1. `test_update_reports_the_values_key_it_removes` — F1 verbatim: `--update`
   removes `Q` AND names it (the task's pins 1+2, in report form).
2. `test_plain_fetch_reports_the_values_key_it_removes` — the plain-fetch prune
   leg above, reported too.
3. `test_update_refreshes_the_recognised_pin_and_reports_the_orphan` — pin 3:
   value → `6.0`, `sha256` = new file digest, `datasheet.csv: V: 5.0 -> 6.0`
   printed (green today), plus the report line (red today).
4. `test_plain_fetch_changes_only_what_it_reports` — pin 4 in report form: the
   row's raw text changes ONLY by the removal of the reported key and the
   `fetched:` stamp (asserted on bytes, green today), plus the report line.
5. `test_check_stays_clean_with_the_extra_key_present_and_after_the_drop` —
   pin 5: `check` exit 0 / `0 errors` with `Q` present (green today), the drop
   reported (red), `check` clean again, span computes `5 V` from the pin.
6. `test_update_twice_reports_the_removal_once` — pin 6: the second `--update`
   reports nothing and the row (stamps excluded) is byte-identical.

Red evidence, all six, same line (test lines 170/188/208/229/249/266):

```
E  AssertionError: no report line named datasheet.csv Q; got:
E    fetched  datasheet.csv  sha256=7469b4c83079...  hash-only
E    1 citation(s) processed, 0 failed
```

Every green guard runs and passes before its red assert, so no
test is red for an incidental reason.

The report line's exact wording is left to the implementer: the contract
asserted is one line per removed key naming BOTH the citation path and the key
on a run that exits 0, plus one assumed marker word (`DROP_MARKER = "dropped"`).
The KEEP-FLIPS comments mark the three assertions that change if the
orchestrator picks KEEP instead; the report assertions stand under either.

## Green-path check (prototype REVERTED before the commit)

To prove the pins are satisfiable I patched, ran, then `git checkout --`'d
`src/`: added `FetchResult.source_dropped: list[str]` of `"{path}: {key}"`,
filled it at both prune sites, and printed in `cmd_fetch`
`         source: dropped datasheet.csv: Q (no source() span references it any more)`.
All 6 new tests passed with it, and the neighbours stayed green:
`test_calc_sources`, `test_citations`, `test_citations_lockfile_locking`,
`test_fetch_size_warning`, `test_lockfile_corruption`, `test_citation_pages`,
`test_citation_ids`, `test_citation_path_hygiene`, `test_inline_calc`,
`test_calc_preview`, `test_sources_csv` → 493 passed, 1 skipped (xlsx).
`git status` after the revert: only the two new files.

Cross-platform: no `Path.read_text(newline=)`; writes use `newline=""`, reads use
`read_bytes()`; the project-relative path is a bare filename (no separator); no
ports. `tests/test_crossplatform_lint.py` 26 passed with the new file present;
`ruff check tests/test_fetch_values_preserve.py --select I,F,E,W` clean.

## Alternatives for the orchestrator (resolved)

Four options were tabled (REPORT; keep-unre-emit-able-keys; KEEP-all; make-it-
an-error); the orchestrator ACCEPTED option 1, REPORT — the KEEP-FLIPS
assertions stay as pinned.

## Implementation (slice FETCH-VALUES-impl) — DONE

Per the accepted REPORT decision: `FetchResult.source_dropped` (citations.py),
filled at every prune site — the whole-map pop and the map replacement in
`_refresh_pinned_sources`, and the whole-record rebuild in `fetch_all` — and
printed by `cmd_fetch` as
`         source: dropped <path>: <key> (no source() span references it any
more)` on a run that still exits 0; the prune itself, the hashing, and the
lockfile bytes are untouched, and a run that prunes nothing prints nothing
new. `docs/cli-reference.md`'s fetch `values:` paragraph gained one sentence
(quote taken from a real scratch-project run, `.scratch/fvimpl/`); fragment
`changelog.d/fetch-reports-pruned-values.fixed.md`. 27 added lines in src.

Green: all 6 new tests; neighbours `test_fetch_values_preserve` +
citations/calc/sources/fetch/lockfile/serve-sources/cli set → 911 passed,
1 skipped; full suite once before push. ruff on the two touched src files:
same 8 pre-existing findings as their HEAD versions, none mine. Not verified
locally: Windows CI (relies on CI), PDF/xlsx records (CSV only).
