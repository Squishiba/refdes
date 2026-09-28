# PDF picker Slice P-C

2026-09-27: Started from a clean upbeat-zebra worktree. Read the full
docs/design/editor-pdf-picker.md, including §6 and §12, PdfReader in
src/refdes/sources.py, and the proposal, pin staging, edit transaction and UI
paths. Read the PDF fixture/test conventions and changelog.d/README.md.

Implementation plan: carry a server-derived quoted-row anchor into the
existing set_body/pin transaction. Re-location searches every page, matches
exact case-sensitive non-numeric tokens after whitespace splitting, and uses
the zero-based numeric-token index. Missing or ambiguous rows and incomplete
page reads must fail without changing the old pin. Fetch and drift diagnostics
must receive the saved anchor too. Browser values/quotes remain untrusted.

Remote kept copies are browsable, but the existing source() authorization
only accepts repo-local files (citations.authorize_source_path). Preserve that
rule and give remote proposals its actual refusal reason.

Implemented PdfAnchor on source requests/results and PdfReader.extract().
The picker and re-location share _pdf_page_listing; extraction opens the PDF
once, refuses incomplete page reads, and reports gone/ambiguous matches rather
than trusting the recorded page. The original author-confirmed quote survives
fetch update; the display page follows the row. citations.py now passes old
anchors into fetch and drift reads and stages newly confirmed ones for accept.

Extended the existing SourcePin/API parsing and accept_plan, without adding an
edit op or write path. The server derives quotes and numeric indexes again,
checks session digests through staging, and refuses rebinding an existing key
to another candidate. editor.js carries the PDF session selection alongside
the persisted draft pin; sourcepicker.js already honors accept_supported.
Local proposals now enable Accept, while kept remote proposals give the
existing source() authorization refusal. Updated the existing design status
and added changelog.d/pdf-picker-accept.added.md.

Validation so far: ruff --select E4,E7,E9,F,I on the touched Python files is
clean. The first sandboxed pytest attempt could not open local HTTP sockets;
reran with required escalation. Expanded targeted run passed 178 tests in
29.53s (reader, PDF HTTP, CSV accept, static UI). Added further transaction,
token and race checks afterwards; full pytest is running. The initial reader
test used bytes for a content-stream replacement even though pdf_page returns
str; corrected before the successful targeted run.

Not finished; full-suite result, final review, commit, push and PR pending.

First full run: 2620 passed, 2 skipped, 3 failed in 187.97s. One new test's
Client.request call passed a dict instead of encoded JSON; corrected, and the
complete PDF HTTP file now passes (59 tests). Two existing failures were test
environment assumptions exposed by putting all temporary fixtures in .scratch:
test_config_split's retired-marker fixture inherited the checkout's marker,
and test_serve_state's initially non-repo fixture inherited the checkout's git
context. Isolated upward discovery in those two tests (a filesystem-root
boundary for the marker test and GIT_CEILING_DIRECTORIES for the git test),
without changing production discovery behavior or skipping tests.

Final review added the byte-cap check before the page digest's first read,
using the reader's shared size check. Testing that cap and revalidation/staging
races ensures coordinates cannot acquire a digest from newly changed bytes.
Final validation rerun pending.

Final full-suite validation passed: 2624 passed, 2 skipped in 201.64s.
Command: PYTHONPATH=src TMPDIR="$PWD/.scratch/tmp" pytest
--basetemp=.scratch/pytest-pc-full-final -q --tb=short (required socket
escalation); output retained in .scratch/pytest-pc-full-final.log.
Scoped ruff check on the touched Python files with --select E4,E7,E9,F,I
passed, as did git diff --check. All scratch fixtures, probes, logs and the PR
body remain in .scratch/. Implementation and validation finished; committing,
pushing upbeat-zebra and opening the PR next.

Finished: committed implementation as ad33d01, pushed upbeat-zebra to origin,
and opened https://github.com/Squishiba/refdes/pull/71 with gh pr create.
The implementation commit left the worktree clean. This final log entry is
being committed and pushed separately to record publication; no code changed
after the successful full-suite and scoped-ruff gates.
