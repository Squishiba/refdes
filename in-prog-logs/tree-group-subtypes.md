# tree.py subtype-aware for `extends:` (tree group-subtypes)

## Task

Make `src/refdes/tree.py` honour `docs/design/extends.md`: where it decides
"is a group" by literal `type == "group"`, use `Project.is_subtype` so a type
that `extends: group` behaves as a group. Same output when no subtypes exist.
Tests in `tests/test_tree.py`, changelog.d fragment, full suite green. No push
to main -- orchestrator refdes-2 reviews and lands.

## Setup

- Branch `ao/refdes-116/root` was already at `origin/main` (`cd05c4b`,
  `git rev-parse HEAD` == `git rev-parse origin/main`), so the requested
  "merge current origin/main first" was a no-op.

## Change (src/refdes/tree.py)

Three literal group decisions replaced with `project.is_subtype(<type>,
"group")` (mirrors build.py's ALLOW-consumer pattern, extends.md §3.2/§3.3):

1. `_group_parents` (~line 107): a `part_of` target is a group parent iff
   `project.is_subtype(target.type, "group")`.
2. `build_forest` cycle promotion (~line 218): the promoted head is treated
   as a group node (attaches `by_group` children + `ref_groups` references)
   iff `project.is_subtype(head.type, "group")`.
3. `_attach_groups` (~line 353): recursion descends into group child nodes
   iff `not project.is_subtype(child.item.type, "group")`. This function had
   to gain a `project` parameter (its two call sites in `build_forest` and its
   own recursion updated). This is the third hardcoded check on top of the two
   the task named.

No other behavior changed. `Project.is_subtype` recomputes `subtype_map` per
call -- negligible at project type counts, and the local call is the
established public API.

## Tests (tests/test_tree.py)

- `SUBTYPE_GROUP_SCHEMA`: component + group + `subgroup: {extends: group}`
  (minimal delta: identity only) + a `widget` member type whose WDG prefix
  sorts after SGR so the cycle test exercises the desired promotion order.
- `test_type_that_extends_group_is_treated_as_a_group_in_the_tree`: a
  same-board member expands under the subgroup's node exactly as under the
  plain group alongside (old behavior unchanged, explicit contrast), no
  group-view placeholder, expanded-count invariant, and the rendered page
  nests CMP-002 under SGR-001.
- `test_subtype_of_group_in_a_cycle_is_promoted_as_a_group_root`: two
  subgroups in a `part_of` cycle + a widget member; the smallest id
  (SGR-CY-001) is promoted and anchored under Board A, the other two nest
  under it ("Board A > SGR-CY-001" breadcrumbs).

Discrimination verified: temporarily reverted tree.py to the literal checks
(backup at .scratch/tree.py.subtype-new.py) and both new tests fail; restored
afterwards. Plain-group behavior: all pre-existing tree tests pass unchanged.

## Docs

- `changelog.d/tree-group-subtype.added.md` fragment added.
- `docs/design/extends.md` §12 "Untouched: tree.py" note updated -- it was
  made false by this change; the bullet now says tree.py honours subtypes.

## Verification

- `python -m pytest tests/test_tree.py tests/test_tree_scoped.py -q` -> 30 passed.
- `python -m pytest -q` (full suite) -> see run below.

## Status

Complete, not pushed. Full suite result and diff in final report to refdes-2.