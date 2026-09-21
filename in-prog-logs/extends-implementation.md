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
