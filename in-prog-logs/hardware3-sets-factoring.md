# hardware@3 base.yaml sets-factoring pass (composition Q3)

Task: use the landed composition features (sets carrying fields/links/
body, doc-only patches, `extends:`) to remove the remaining field/link/
body duplication in `src/refdes/standards/hardware/v3/base.yaml` without
changing the resolved schema. The oracle
(`tests/test_extends.py::test_hardware3_base_resolves_unchanged`, both
presets [] and [design-debate]) had to stay green with NO fixture edits.

## What landed

Five new sets in base.yaml:

- `grouped` — `links: { part_of: [group] }`; included by requirement,
  decision, test, component (bound receives it through `extends:`).
- `claims` — `links: { satisfies: [requirement, bound], constrained_by:
  [bound] }`; decision + component.
- `invalidate_body` — `body: { on_change: invalidate }`; decision, test,
  component, log.
- `named_title` — `title: { type: text, required: true, on_change:
  invalidate }`; decision, test, component, each with a doc-only patch
  keeping its own sentence (composition §3).
- `statement_title` — optional-label `title`; requirement + bound, each
  doc-patched.

Field ORDER is oracle-compared, so each title set is placed last in its
type's include list: set fields merge before the type's own, which
reproduces the pre-pass order (`...citations, title, status, ...`). Link
verb order is explicitly not compared, so moving links into sets is free.

vocabulary.py:

- `_includers` widened per composition §5: a type matches a set when it
  carries the set's whole contribution — fields under the same *semantic*
  spec (doc may differ, which is what a doc-only patch produces), links
  with identical targets, same body. Name-superset matching would have
  listed every type with a `title` as an includer of `named_title`.
  Caveat kept: an inherited-identical contribution still matches (bound
  shows under `grouped`/`provenance`), as it did before.
- Hand-written EXAMPLES entries for the five new sets (the
  `test_bundled_standard_terms_have_hand_written_examples` gate).

Tests (tests/test_composition.py):

- `test_base_yaml_declares_nothing_identically_twice` — zero byte-
  identical own field/link/body declarations across types. Before the
  pass: eight redundant declarations (part_of x4, satisfies x2,
  constrained_by x2, body-invalidate x4). After: zero.
- `test_base_yaml_doc_only_diffs_are_the_approved_survivors` — the only
  full redeclarations differing solely in doc are exactly status +
  rationale (requirement/bound) and checks (decision/component).

docs/schema-reference.md and docs/vocabulary.md regenerated with
`python docs-site/gen_examples.py` (generated pages; the only diffs are
the new set entries and link-comment ordering).

## Left unfactored, with reasons

- requirement/bound `status` and `rationale`: doc-only patches apply to
  includes, not to an `extends:` parent, and a set's fields land BEFORE
  the type's own — routing them through a set would resolve bound as
  `title, status, rationale, limit`, stranding `limit` after `rationale`
  (the oracle compares field order). Q2 already decided `checks` stays
  fully declared on decision + component.
- `preview:`, `coverable`/`coverable_statuses:`, status lists, identity
  keys, and the `include:` lines themselves — left out by composition §1
  by decision, not by this pass.
- Presets and frozen v1/v2: untouched, per task rules.

## Verification

- `python -m pytest -q` — 1495 passed; fixtures untouched (git status
  clean for tests/fixtures/).
- Merged origin/main repeatedly during the pass (latest: d84e123); no
  conflicts with base.yaml.

Status: done. Not pushed, not merged — owner reviews and lands.
