# CITE-LOCK-012: reject negative PDF page counts consistently

Branch: `fix/citation-negative-page-count-20261015` (worktree
`/home/jorb/.paseo/worktrees/16msma8v/fix-citation-negative-page-count-20261015`,
base `7e49a20` == main tip when started). Owner: Qwen3.8-Flash-Next (task
claimed in shared `.scratch/PROGRESS.md` as CITE-LOCK-012).

## Old finding vs current main

Baseline evidence (`in-prog-logs/current-main-resweep-cite-page.tsv/.txt`,
pinned `8b6a52e`, 2026-10-12): with a lockfile record `page_count: -3` and a
citation `page: "99"`, plain `refdes fetch` printed
`WARNING docs/manual.pdf: page 99 is not in this document -- it has -3 page(s)
(cited by CMP-001)` (exit 0) while `refdes check` printed
`1 items, 0 errors, 0 warnings` (exit 0) and `build` published. Split-brain:
`_check_pages` (fetch) warns for any recorded int including negatives;
`_apply_page` (check/build) folds any count < 1 into "no count" and goes
quiet; the lockfile validator is type-only, no range.

Merged #233 (`b164df0`, CITE-LOCK-004/003) landed after that resweep and
rewrote the neighbourhood: `page_count_sha256` provenance is now required for
a count to be trusted by `_apply_page`, and the plain-fetch skip path counts
already-pinned records. It did NOT change the negative-count split. I
re-verified against current main with the real CLI (venv `refdes` entry
point, `PYTHONPATH` pinned to this worktree's `src`, `refdes.__file__`
asserted per run — probe at `.scratch/cite-negative-page-20261015/probe.py`):

- `neg`: trusted-provenance record (`page_count: -3`, `page_count_sha256`
  == `sha256`) on an 8-page PDF, `page: "99"` — fetch exit 0 with the
  `-3 page(s)` warning, check exit 0 quiet, build exit 0 publishing.
  PRESENT at current main.
- `zero` control: a real `refdes fetch` of a 0-page PDF records
  `page_count: 0` and check/build stay exit 0 quiet (fetch prints its
  fetch-time `it has 0 page(s)` warning for the out-of-range page — that is
  current, documented behavior, untouched).
- `pos` control: `page_count: 8`, `page: "99"` — fetch, check, and build all
  warn the same sentence. This is the consistency family.

## Decision: load refusal, not a consistent warning

`page_count(data)` is `len(reader.pages)`, so a negative count is not output
`refdes fetch` can ever have written — unlike `page_count: 0`, which is
`fetch`'s real output for a document pypdf opens and finds no pages in
(documented at `docs/cli-reference.md`, pinned by
`test_a_zero_page_document_still_validates_clean`). The validator's own
constraint is "never report `fetch`'s own output as malformed"; a negative is
outside that constraint, so the refusal is safe. Refusing at
`load_lockfile`/`read_lockfile` — the one door every reader of the file goes
through (verified by grep: `build.py` x2, `cli.py` fetch/audit,
`serve/edit.py`, `serve/sources.py`) — makes every command agree by
construction, which is exactly what the finding's split-brain needs; a
warning-only fix would leave the record "loading as sound", the half of the
finding the check's silence lives on. Zero-page behavior is preserved
exactly.

## Changes

- `src/refdes/citations.py` (`_record_problem`): new range clause —
  `page_count` that is an `int` < 0 is a `LockfileError` naming the entry,
  the value, why `fetch` cannot have written it (`len(reader.pages)`), the
  0-is-real/negative-is-not contrast, and the split it used to cause. The
  shared remedy sentence is appended by the caller
  (`_restore_remedy("Rewrite that record by hand")` at the raise site in
  `load_lockfile`), matching the sha256/type messages; my clause carries no
  remedy of its own (the first draft did and printed the git-checkout advice
  twice — caught in the probe, fixed).
- `src/refdes/citations.py` (type-check comment): "no range" → the range
  refusal lives in the clause below, where `fetch`'s own output provably is
  not in the running; "(reads a count below 1 as no count...)" narrowed to
  0.
- `tests/test_lockfile_corruption.py`:
  - `test_a_malformed_page_count_pair_is_a_diagnostic[count-is-negative]`
    (table case, red before: check exit 0).
  - `test_a_negative_page_count_is_refused_by_every_reader` (CLI regression:
    real fetch → hand-corrupt `page_count: -3` → check exit 1 naming
    `.refdes/citations.yaml`, build exit 1, fetch exit 1 leaving the file
    byte-identical, no `-3 page(s)` published anywhere, no traceback; red
    before at the check==1 assert).
  - zero-page test's parenthetical narrowed (negatives are now refused
    outright, pointer to the test below).
- `docs/cli-reference.md`: refusal list gains "a `page_count:` that is
  negative"; the acceptance paragraph explains the 0-sound / negative-refused
  line and the split it used to cause.
- `docs/troubleshooting.md`: new per-shape entry for
  `has page_count -3` (the page lists one entry per lockfile refusal; the
  `page_count 'eight'` entry's "0 is not this error" claim is unchanged).
- `changelog.d/citation-negative-page-count.fixed.md`.

## Gates

- Red confirmed before the fix: the two new/changed negative tests fail
  (check exit 0), the 5 sibling table cases pass.
- Green after: targeted suites
  `test_lockfile_corruption + test_citation_pages + test_citations +
  test_citation_sections + test_citation_ids +
  test_citations_lockfile_locking + test_serve_sources_accept +
  test_serve_sources + test_audit_hash_only_wording` = 409 passed, 1
  skipped. Full suite: see below.
- Probe (real CLI, pinned src): -3 → fetch/check/build all exit 1 with one
  sentence at `.refdes/citations.yaml:11`, file byte-identical after the
  refused fetch; 0-page fetch/check/build unchanged (exit 0, 0 warnings);
  positive control unchanged (consistent warnings on all three).
- Scoped ruff `E,F,W,I,UP,B` on `src/refdes/citations.py
  tests/test_lockfile_corruption.py`: 10 findings == baseline (HEAD copies
  of the same files, same rules). No new findings; none silenced.

## Finished

YES — fix, red/green CLI regression, docs, changelog, gates, PR.
