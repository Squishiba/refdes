# Vocabulary page: worked examples for every term (refdes-111)

## Task

Every term in the generated vocabulary page (`docs/vocabulary.md` and a
built site's `vocabulary.html`) gets a direct, worked example, not just a
definition. Types: a minimal items-file snippet declaring that type. Link
verbs: the verb used from one item to another, both directions where
declarable from either end. Field sets: a type including it. Reserved keys:
the key appearing on an item. All values verified against
`src/refdes/standards/hardware/v3/base.yaml` and this repo's `items/` tree.

## What was done

- Mid-task main moved (b3af06b -> 35073bb, per-term diagrams + coverage
  spine). Discarded my two uncommitted infra edits, fast-forward merged,
  re-applied against the new structure (`_term_html(e, project)`). No
  conflicts.
- `src/refdes/vocabulary.py`:
  - `TermEntry.example` field.
  - `EXAMPLES: dict[(kind, name), str]` -- hand-written examples for all
    7 types, 15 link verbs, 3 field sets, 11 reserved keys of hardware@3.
    Values taken from `base.yaml`, `items/` (REQ-PWR-001..004, BND-THM-001,
    DEC-PWR-001, TST-PWR-001, CMP-PWR-001, LOG-A-001/003/004/006), and
    docs/links.md + docs/authoring.md + docs/workspaces.md examples. No
    invented fields.
  - `_fallback_example(entry)` -- generic minimal example built only from
    the entry's own resolved facts (prefix, required fields, declared_on,
    targets/inverse, included_by), so overlay/preset terms are never
    example-less. Placeholders (`...`), never invented content.
  - Rendered in both renderers: markdown `**Example:**` + fenced yaml block
    after the fields table; HTML `<div class="vocab-example"><h4>Example
    </h4><pre><code>` (escaped, static, no script).
  - Module docstring updated.
- `src/refdes/templates/vocabulary.html.j2` and the hand-written intro of
  `docs/vocabulary.md`: mention the examples + the hand-written/generated
  convention.
- Regenerated `docs/vocabulary.md` via `python docs-site/gen_examples.py`.
  (`docs/schema-reference.md` gets re-touched by every gen run but its
  content is unchanged -- reverted the EOL-only churn.)
- `tests/test_vocabulary_page.py`: 4 new tests -- every term has an
  example; examples render in both renderers; every pinned-standard term is
  covered by the hand-written table (a standard term silently falling back
  is a gap); example markup is escaped (`<= 0.15` arrives as `&lt;= 0.15`).

## Verification

- `python docs-site/gen_examples.py --check` semantics covered by
  `test_docs_site_check_accepts_the_committed_page` -- passes.
- `tests/test_vocabulary_page.py`: 22 passed.
- Full suite: 1295 passed.
- `ruff check src/refdes/vocabulary.py tests/test_vocabulary_page.py
  --select E9,F`: clean (repo-wide ruff baseline is not clean by design).

## Notes / risks

- Hand-written examples are keyed by term name and describe hardware@3 as
  shipped; a project whose overlay redefines a standard term still gets the
  standard's example (illustrative, not authoritative, for that project).
  Documented in the EXAMPLES comment.
- Not pushed, not merged, per instructions. Branch: ao/refdes-111/root at
  35073bb + uncommitted working-tree changes for review by refdes-2.
