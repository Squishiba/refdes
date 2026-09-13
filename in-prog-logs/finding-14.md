# Finding 14 — a grouping/collection type (hardware@3)

Adds `group` to the bundled hardware@3 standard: a named collection of
items ("the PCIe interface spec") that can be linked and rendered but can
never stand in for its members. Implemented entirely in
`src/refdes/standards/hardware/v3/base.yaml` — no changes to `schema.py`
or `build.py` were needed, because both negative properties are already
expressible through existing schema-layer machinery.

## The two naming choices

**Type name `group`, prefix `GRP`.** No deviation from the task's
suggestion: every existing type is a lowercase singular noun with a
three-letter prefix (REQ/BND/DEC/TST/CMP/LOG), and `group`/`GRP` slots
into that convention without colliding with anything.

**Inverse of `part_of` is `contains`.** The existing pairs that run
passive-author-side/active-inverse — `governed_by`/`governs`,
`constrained_by`/`constrains`, `blocked_by`/`blocks` — all name the
inverse as the *actor's active verb*: the governed thing is pointed at by
the thing that **governs** it. The group is the actor in its members'
view, so `part_of` → `contains` reads the same way in backlink renderings
("The PCIe interface spec" shows `contains: REQ-001, …`). `has_part` was
considered and rejected as noun-shaped where every sibling inverse is a
verb; `includes` was rejected because `include:` is already a reserved
schema keyword in this very file.

## Where membership lives

`part_of: [group]` is declared on requirement, bound, decision, test, and
component — the spec-content types. Not on `log`: log entries are records
of activity, not things a spec group collects. The group declares **no**
membership links of its own; `contains` exists only as the computed
inverse backlink (`resolve_links` fills `group.backlinks["contains"]`
when a member declares `part_of`), so membership flows one way and a
group can never list — and so silently grow — its members.

## The two negatives, and how the standard enforces them

1. **Not coverable** — `coverable: false` on the type. `compute_coverage`
   skips the type entirely, so a group never gets a coverage row and
   never acquires a stage.
2. **Not a satisfaction target** — `satisfies:` target lists on
   `decision`/`component` stay `[requirement, bound]`. `resolve_links`'
   existing target-type check turns `satisfies: [GRP-001]` into a hard
   error naming the type ("...but GRP-001 is a group"), and the link is
   not recorded, so it cannot settle anything even as a side effect.

## Tests (tests/test_standards.py, four new)

- `test_group_is_declared_and_not_coverable` — GRP prefix,
  `coverable is False`, no `contains` declared on the group,
  `part_of.inverse == "contains"`.
- `test_group_never_appears_in_coverage` — **A**: with a group and an
  active member, `REQ-001` is in `project.coverage` and `GRP-001` is
  not; no coverage row, warning, or error names the group.
- `test_group_cannot_be_a_satisfies_target` — **B**: `satisfies:
  [GRP-001]` produces an error on DEC-001 whose message says "is a
  group" (not "does not exist"), and the claim resolves nowhere.
- `test_part_of_resolves_and_the_group_sees_members_through_contains` —
  **C**: member's `part_of` resolves; group's `contains` backlink lists
  the member.

**Negative-test verification:** with a deliberately unrestricted
implementation (group `coverable: true`, `group` added to both
`satisfies:` target lists), tests A and B (and the declaration test) all
fail while C still passes — then the standard was restored unchanged.
The tests genuinely discriminate; none is an always-pass.

## Verification

- `python -m pytest tests/ -q` → **667 passed** (663 prior + 4 new), 0 failed.
- v1/v2 base.yaml, CHANGELOG.md, and backlog.md untouched.
