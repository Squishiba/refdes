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
- Missing `page_count_sha256` is still trusted for old remote hash-only PDF
  records, because the bytes are not on this machine and a plain fetch cannot
  repair them without network.
- A trusted `page_count_error` is not re-counted by plain fetch merely because
  pypdf may have been installed after the fetch. This preserves existing
  behavior and avoids turning plain fetch into a broad repair command.
- The final gate did not include pushing, PR creation, or merge.
