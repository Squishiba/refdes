# docs-vocab-honesty

Two doc defects found by a vocabulary inventory. Branch:
ao/refdes-107/docs-vocab-honesty, off main (5a45952). One commit per chunk.

## Chunk 1 — coverage stage count disagreed three ways

Authority: `Coverage.stage` in `src/refdes/model.py` (lines 589-598) returns
`verified` / `satisfied` / `claimed` / `addressed` / `open` — five stages.
`build._coverage_for` (build.py:691) populates `cov.claimed_by` for
satisfiers whose status is not in the type's `satisfying_statuses:`.

- docs/coverage.md already said five and matched the code — left alone.
- docs/concepts.md said "three notions" with four rows — heading is now
  "The five coverage stages" (orchestrator pass: `open` is not a notion of
  done, so counting notions was wrong either way), `claimed` row added,
  `satisfied` row reworded to match coverage.md/code semantics, prose keeps
  the original insight: three senses of done, claimed = unsettled satisfied,
  open = none of them.
- docs/index.md line 12 echoed "three notions" — fixed to five.
- docs/design/backlog.md line 678 says "the same four stages" in a shipped
  finding note — left alone as design history; noted in the report.

Tests: 1256 passed.

## Chunk 2 — follows: documented but not declared

(to be filled in below)
