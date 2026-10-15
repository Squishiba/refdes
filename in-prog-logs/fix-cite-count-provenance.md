fix-cite-count-provenance (CITE-LOCK-004)

Date: 2026-10-13
Branch: fix/citation-page-count-provenance-20261013
Stack: stacked on CITE-LOCK-003, starting from HEAD 9339ba6

Goal
----
Make citation page counts/errors provenance-bound to the pinned sha256, distrust
missing/mismatched provenance, validate the new lockfile field shape, and repair
offline where the bytes are already present.

Starting state
--------------
The branch already had partial changes in `src/refdes/citations.py` and the new
regression tests in `tests/test_citation_pages.py`:

- constants `PAGE_COUNT_SHA256_KEY` and `PAGE_COUNT_UNVERIFIED_WHY`;
- a small `_page_count_matches_pin()` helper;
- the optional-fields text in `_record_problem()` mentioned
  `page_count_sha256`;
- the new tests failed because fetch did not bind page counts to sha256 and
  check/fetch/audit still trusted unbound counts.

Reproduced the red set before touching code:

    PYTHONPATH=$PWD/src python -m pytest tests/test_citation_pages.py -q

4 failed, 51 passed:

- `test_without_the_pdf_extra_the_page_is_not_checked_and_fetch_says_so`
  needed `page_count_sha256` on a freshly written `page_count_error` record.
- the parametrized untrusted-provenance test needed check/build to distrust a
  count whose provenance was missing or mismatched, and a plain offline fetch to
  repair it.
- the hash-only stale-count test needed plain fetch to warn without downloading
  and without rewriting the record.

Implementation
--------------
`src/refdes/citations.py`:

- Added `_count_provenance_untrusted(path, record)`.
  - A count/error is distrusted when `page_count_sha256` does not match `sha256`.
  - A missing provenance key is distrusted for local and kept-copy records.
  - Remote hash-only PDF records are the compatibility exception when the
    provenance key is missing: only a prior fresh fetch could have counted those
    bytes, and plain fetch cannot repair them offline.
- Fresh fetch now writes `page_count_sha256` beside both `page_count` and
  `page_count_error`.
- The already-pinned skip path now:
  - removes the whole page-count group when no page is cited any more;
  - counts local/kept-copy bytes when no count exists, as CITE-LOCK-003 did;
  - recounts local/kept-copy bytes when the recorded count/error cannot be
    trusted, and writes the matching provenance;
  - does not download for remote hash-only pins, but reports an untrusted count
    as "not checked" without rewriting it.
- `_apply_page()` now reports cited pages as not checked when the lockfile's
  recorded count/error cannot be trusted.
- `page_count_gaps()` reports the same condition, so `audit` reads
  `pages unchecked` instead of `ok`.
- `_record_problem()` rejects a malformed `page_count_sha256` shape, without
  making the key required.

`src/refdes/cli.py`:
- Audit's second line now says "could not be checked against these bytes" rather
  than "could not be counted", because `page_count_gaps` now also reports a
  recorded but untrusted count.

Tests
-----
Added `test_a_malformed_page_count_provenance_is_a_diagnostic` in
`tests/test_lockfile_corruption.py`.

Commands run after implementation:

    PYTHONPATH=$PWD/src python -c "import refdes; assert refdes.__file__.startswith('/home/jorb/work/refdes/.scratch/fix-cite-count-provenance'), refdes.__file__"

    PYTHONPATH=$PWD/src python -m pytest tests/test_citation_pages.py tests/test_lockfile_corruption.py tests/test_run5_friction_f1_f2_f6_f8.py tests/test_citations.py tests/test_serve_sources_accept.py -q

Result: 308 passed, 1 skipped after adding the malformed-provenance test.

Full suite:

    PYTHONPATH=$PWD/src python -m pytest -q

Result: 3611 passed, 2 skipped.

CLI probes
----------
Created scratch probes under `.scratch/`:

- `.scratch/cite-count-provenance-cli-probe`: local PDF with an existing pin
  whose `page_count: 8` had mismatched `page_count_sha256`.
  - `refdes check` warned:
    "the page numbers cited for docs/manual.pdf are not checked: the lockfile's
    page count is not tied to the pinned sha256".
  - plain `refdes fetch` repaired the record offline to `page_count: 2` and
    matching `page_count_sha256`.
  - `refdes build --require-citations` then reported the real out-of-range page
    as an error.

- `.scratch/cite-count-provenance-cli-probe-hash-only`: remote PDF record with
  stale count and mismatched provenance.
  - `refdes check` warned.
  - plain `refdes fetch` skipped and warned "not checked" without changing the
    record.
  - `refdes audit` printed `pages unchecked`.

- `.scratch/cite-count-provenance-cli-probe-no-extra`: fresh local fetch with
  `pypdf` hidden via a wrapper.
  - `refdes fetch` wrote `page_count_error` and matching `page_count_sha256`.

Ruff
----
Ran scoped lint:

    ruff check src/refdes/citations.py tests/test_citation_pages.py tests/test_lockfile_corruption.py

This repo has many pre-existing ruff findings. I fixed the new `SIM103` finding
in the new helper. Remaining findings in these files were pre-existing in
untouched areas (`ISC004`, `S110`, `BLE001`, `RUF100`, `UP017`, `S112`,
`I001`) or in test files from the parent commit.

Status
------
Finished implementation, docs, and verification. No commit had been made at the
time of writing this log before the final review pass.

Known limits
------------
- Missing `page_count_sha256` is no longer trusted for remote hash-only records
  that already claim a count/error. A plain fetch cannot repair them without the
  network, so it warns and leaves them for `fetch --update`.
- A trusted `page_count_error` is not re-counted by plain fetch merely because
  pypdf may have been installed after the fetch. This preserves existing
  behavior and avoids turning plain fetch into a broad repair command.
- The final gate did not include pushing, PR creation, or merge.

Follow-up review of a501d8e
---------------------------
Two blockers were reported:

1. The skip-path repair could leave `page_count` and `page_count_error` in the
   same record when replacing one with the other.
2. `_count_provenance_untrusted` trusted a remote hash-only count whose
   provenance key was absent, leaving the original merge-corruption hole open.

Added three tests first:

- repairing an untrusted old failed count writes a new count and removes the
  failed count;
- recording a new failed count removes the old count;
- a remote hash-only record with `page_count: 8` and no
  `page_count_sha256` is untrusted, warned by check/build, left unchanged by a
  plain fetch that must not use the network, and reported by audit as pages
  unchecked.

All three failed at the expected assertion on the old code, then passed after:

- popping the opposite count key in each repair branch;
- making missing provenance untrusted for any record that claims a count/error,
  including remote hash-only records.

Existing run-5 audit fixtures were updated to the new contract: a remote
hash-only counted pin is trusted only when its provenance matches its pin, and
an unprovenanced failed count reports the unverified-provenance reason. Docs
were changed to remove the old remote hash-only exception.

Gates:
- new tests: 3 passed;
- citation pages + run-5 friction: 85 passed;
- citation pages, lockfile corruption, run-5, citations, serve accept, audit
  wording: 341 passed, 1 skipped;
- full suite: 3614 passed, 2 skipped;
- CLI probe:
  `.scratch/cite-count-provenance-cli-probe-hash-only-unprovenanced` confirmed
  check warns, plain fetch skips and warns without changing the lockfile, audit
  reports pages unchecked, and build --require-citations exits nonzero.

PR prep 2026-10-14
------------------
Started from head `fd7d377`, status clean. Verified pwd, branch, worktree root,
and AGENTS.md. Every commit on `origin/main..HEAD` has a
`Co-authored-by: Qwen3.8-Flash-Next <noreply@refdes.local>` trailer.

- `git fetch origin main` (one fetch). Current main was `9f83092`.
- Inspected merged #212 (`1a1c960`): its citations.py change wraps
  `load_lockfile()`'s read in a `UnicodeDecodeError -> LockfileError` guard.
  After rebase it is present at `src/refdes/citations.py:1152` (HEAD
  `5355b34`).
- Inspected open PR #225 (`aa1efa9`): its citations.py guard is
  `MAX_PAGE_DIGITS = 64`, enforced in `page_number()` and
  `serve/sources._pdf_proposal()`. It is not in current main and is not included
  in this PR; our branch does not touch `page_number()` or
  `serve/sources._pdf_proposal()`, so it preserves the open PR's guard.
- `git rebase origin/main`: clean, 3/3 commits, zero conflicts. New head
  `5355b34`.

Verification after rebase, with `PYTHONPATH` forced to this worktree's `src` and
`refdes.__file__` verified as
`/home/jorb/work/refdes/.scratch/fix-cite-count-provenance/src/refdes/__init__.py`:

- Page-count/fetch/audit/lockfile suites:
  `tests/test_citation_pages.py tests/test_citations.py
  tests/test_lockfile_corruption.py tests/test_run5_friction_f1_f2_f6_f8.py
  tests/test_audit_hash_only_wording.py tests/test_serve_sources_accept.py`
  -> 341 passed, 1 skipped.
- #212 adjacent store suites:
  `tests/test_history.py tests/test_keys_adopt.py tests/test_reseal_audit.py
  tests/test_seal.py tests/test_yaml_loaders.py`
  -> 85 passed.

Real CLI probes:

- `.scratch/pr-cite-probe-local`: a local PDF pinned with a mismatched
  page-count provenance. `check` warns and names plain fetch; plain fetch skips
  the re-pin, recounts to `page_count: 2`, writes the matching
  `page_count_sha256`, and warns about cited page 5 of the 2-page PDF.
  `build --require-citations` then reports the page error.
- `.scratch/cite-count-provenance-cli-probe-hash-only-unprovenanced`: a remote
  hash-only PDF pin with `page_count: 8` and no provenance. `check` warns with
  the `--update` remedy; plain fetch warns, leaves the lockfile unchanged, and
  downloads nothing; `audit` reports `pages unchecked`;
  `build --require-citations` fails.
- `.scratch/pr-cite-probe-no-extra`: fresh local fetch with pypdf hidden writes
  `page_count_error` plus matching `page_count_sha256`, and `check` reports the
  pages as unchecked.
- `.scratch/pr-cite-probe-corrupt-lockfile`: non-UTF-8 lockfile. `fetch`,
  `check`, `audit`, and `build` all name `.refdes/citations.yaml` and exit 1
  with no traceback, preserving #212.

Scoped ruff on the touched Python files:
`E9,F,I001,SIM` reports only pre-existing findings (SIM105 at
`src/refdes/citations.py:346`, import-sorting SIM/I001 in untouched import
blocks). No findings were introduced on this branch's added lines.