- **Changed:** hardware@3's `base.yaml` now practices the composition it
  ships (docs/design/composition.md Q3): the duplicated `part_of`,
  `satisfies`/`constrained_by` and `body: { on_change: invalidate }`
  declarations moved into the new `grouped`, `claims` and `invalidate_body`
  sets, and the shared `title` fields into `statement_title`
  (requirement/bound) and `named_title` (decision/test/component), with each
  type keeping its own wording through a doc-only patch. The resolved
  schema is byte-identical — the `test_hardware3_base_resolves_unchanged`
  oracle holds with the fixtures untouched — so nothing that hashes, seals
  or baselines an item can tell. Visible effects: the generated vocabulary
  page gains entries for the five new sets, and the vocabulary's "Included
  by" inference now matches a set's links and body and a field's semantic
  spec (doc may differ), instead of bare field-name supersets, so a set
  sharing a common field name no longer claims every type that has it.
