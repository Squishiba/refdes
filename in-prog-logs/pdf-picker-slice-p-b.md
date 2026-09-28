# PDF picker Slice P-B

2026-09-27 — Started from a clean worktree. Read the full PDF design,
the CSV picker, both source reader/service modules and tests/test_serve_static.py
(the static/tests path in the request does not exist). P-A exposes positioned
spans and candidate rows, but no page dimensions or PDF proposal read. P-C
extraction/accept is still unimplemented in PdfReader.

Plan: extend the same sourcepicker.js confirm controls and proposal endpoint,
add page geometry for a fixed-aspect reconstruction, show all candidates and
explicit failure/drift states, and keep PDF saving visibly unavailable until
P-C. No separate picker, byte-serving route, parser, or write operation.
Status: in progress; verification and publication pending.

Implementation: sourcepicker.js now offers browse=pages in the same file list,
loads the cited page via the existing page endpoint, positions spans within
the PDF's MediaBox, lists every numeric candidate with its header guess, and
highlights the reviewed row/token. The same showConfirm/unit/name/proposal
and accept controls serve both readers; a PDF adds a quote and editable key.
The widened read-only proposal returns accept_supported=false for PDF: no
draft insertion or lockfile write is enabled before P-C. The shared API still
composes all calc syntax and re-reads/authorizes each PDF selection, comparing
its sha256 with the displayed page. Page failures, caps, citation details and
drift are visible; page/file navigation cancels stale responses.

Verification difficulties: the first probe needed .scratch created before
pytest's basetemp could be created. The next run demonstrated that the sandbox
forbids local sockets; reran with the required escalation for real HTTP tests.
Two existing visitor test doubles needed MediaBox attributes for the new
geometry contract. Focused tests and full-suite verification are underway.
Ruff F/I checks on all touched Python files passed; existing E501 findings
are outside this change and were left intact.

Final review: key edits refresh the displayed pin even with an empty unit;
PDF name proposals avoid existing assignments. Corrected the PDF HTTP fixture's
calc fence so the existing-name refusal is exercised against a real calc.
The initial new tests also needed to strip the unit annotation before calling
parse_source_call and to preserve page 2 when simulating changed bytes.

The first full suite finished with 2563 passed, 2 skipped and 3 failures.
The static JS scanner treated a comment apostrophe as a quote; changed the
comment and confirmed all 43 static tests pass. The other two failures are
fixture ancestry assumptions: test_config_split discovers this checkout's
project marker and test_serve_state discovers its Git metadata when basetemp
is under .scratch. Final full run uses bwrap with a private /tmp alias bound
to this checkout's .scratch, so every actual temporary file stays here while
fixtures have independent ancestry. No tests are excluded or patched for this.
The first namespace invocation needed the standard private /dev setup for
pytest capture; the corrected invocation is running.

Finished implementation and verification. The final full suite passed:
2566 passed, 2 skipped, in 183.74s (log retained at
.scratch/pdf-picker-p-b-full-3.log). Two warnings concern pytest's cache on
the namespace's read-only checkout; test fixtures and all real HTTP tests ran.
No tests were excluded. Invocation:

    bwrap --ro-bind / / --dev /dev --tmpfs /tmp \
      --bind "$PWD/.scratch" /tmp/refdes-tests \
      --bind "$PWD/.scratch" "$PWD/.scratch" \
      --setenv TMPDIR /tmp/refdes-tests --chdir "$PWD" \
      python -m pytest --basetemp=/tmp/refdes-tests/pdf-picker-p-b-full-3

Scoped Ruff passed for src/refdes/sources.py, src/refdes/serve/sources.py,
src/refdes/serve/api.py, tests/test_serve_static.py,
tests/test_serve_pdf_sources.py and tests/test_sources_pdf.py with
--select E4,E7,E9,F,I. git diff --check passed. Static UI tests follow this
repository's text-check conventions; no browser runtime verification is
claimed. Changelog fragment: changelog.d/pdf-picker-panel.added.md.
Publication is the remaining step: commit these explicit paths, push
premium-bedbug, and open a PR against main. PDF accept remains intentionally
unavailable, as Slice P-C rather than unfinished P-B work.

Publication finished: implementation commit de3339d was pushed to
origin/premium-bedbug. Opened PR #67 with gh pr create:
https://github.com/Squishiba/refdes/pull/67
The worktree was clean after the implementation commit; this final log entry
is committed and pushed separately to record the completed task.
Status: finished — Slice P-B implemented, verified, committed, pushed and PR open.
