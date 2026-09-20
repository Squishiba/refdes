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

Confirmed the premise: grep for `follows`/`followed` across
src/refdes/standards/ hits only a v2 comment and the derives_from label
prose — no link_types declaration in v1, v2 or v3. The engine is landed
(chains.py walk, links.py plan_follows_freeze/freeze_follows called from
cli.py:133, keys adopt implemented as cmd_keys_adopt), but an undeclared
verb errors at parse/schema (schema.py:555, blocks.py:403).

Changed (user-facing docs only):
- docs/links.md — `follows:` paragraph rewritten: what it will do kept,
  plus a plain statement it is not available and is an unknown-link error
  today; ships with the threads work.
- docs/design-log.md — Thread section rewritten the same way.
- docs/cli-reference.md — keys adopt bullet "Freezes bare follows:
  references" now caveats that no bundled standard declares it yet.
- changelog.d/follows-docs-honesty.fixed.md — new fragment.

Checked and left alone: docs/design/threads.md (the design doc itself says
hardware@3 does not declare follows:), docs/design/living-notes.md,
living-notes-plan.md, keys.md, backlog.md (design history/plans),
docs/vocabulary.md (no follows entry), README.md, refdes-schema.yaml, and
every other docs/*.md hit for "follows" — all ordinary English prose, not
the link verb. docs-site/ has no follows: mentions.

Tests after chunk 2: 1256 passed.
