# extends: (docs/design/extends.md)

Task: implement extends.md in full, phased per its section 8; report to refdes-2 after each phase.

## Phase 1 -- engine (done)

- `standards._resolve_extends` runs after `_merge_types`, on the merged/include-expanded
  types. `extends` stays on the resolved dict so schema.py can record `ItemType.extends`
  (the doc's sketch pops it, but then the subtype map has nothing to read).
- prefix/label/plural must be declared by the child (a missing one is an error); `doc` is not
  inherited either (it is the type's own definition -- not listed in the spec table, judgment call).
- Merge order: inherited-only fields/links keep the parent's order, then the child's own in its
  declared order. Not in the spec; chosen so bound's field order is unchanged when it converts.
- Liskov guards: required parent field can't become optional; `append_only: false` under an
  append-only parent errors. Preset-extends-another-preset errors (spec 2.4).
- Set-named-as-parent message says "set" not "field_set" (composition.md predates the rename).
- Un-deferred the two composition tests. Oracle fixtures snapshotted BEFORE any base.yaml change:
  tests/fixtures/hardware3_resolved.json and ..._design_debate_resolved.json (tests/oracle_dump.py).
- Difficulty: bash heredocs mangle `
` inside python strings -- wrote test tails with the Write tool.

## Phase 2 -- consumers (done)

- build.resolve_links, `_group_type_names` (conforms_to/includes), `_verifier_type_names` go through
  `is_subtype`/`_expand_subtypes`; the name-based coverable fallback also accepts a subtype of
  requirement/constraint. schema_json completion text lists subtypes after the parent name.
- `coverage.group_inherited` (configcheck `coverage:` block, `Project.group_inherited`, default TRUE for
  every project per Jared's overturn). Grouping effect: coverage rows get a `(subtype)` badge and sort
  with the parent (only when the project has subtypes -- old ordering otherwise), summary type_rows fold
  subtype counts into the parent row.
- SPEC CONTRADICTION resolved toward the task text: extends.md 3.2/4.1 say `{{index type=}}` must not include
  subtypes by default, but sec 8 / the task say "index groups by parent when the setting is on". Implemented:
  index lists subtypes when `coverage.group_inherited` is on (default), overridable per block with a new
  `subtypes="true|false"` param (the spec's own "opt-in parameter"), each subtype row marked `(type)`.
- Not touched: tree.py's hardcoded `type == "group"` checks, cli `ls --type` (LISTING, exact by spec),
  nav's `log`, diagram edges (declared targets).
- Tooling note: bash heredocs with apostrophes break this shell tool; used Write + a python append.
