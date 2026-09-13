# Finding 16 — `recorded_by: [log]` on `decision` (hardware@3)

## Problem

A `log` is `append_only: true` and `compute_hashes()` folds every link into
the content hash unconditionally (there is no `on_change` equivalent for
links), so a sealed log can never gain a link to something written after it.
"Write the log while deliberating, decide afterwards" is therefore
unauthorable in that order: the `log.links.records: [decision]` end can only
point backwards.

## Verified before editing

1. `records`/`recorded_by` already exist as an inverse pair in the bundled
   v3 `link_types:` block —
   `records: { inverse: recorded_by, label: "Records", trace: false }`
   (`src/refdes/standards/hardware/v3/base.yaml`, line 100). No new verb.
2. `schema.py` resolves a link declared from either direction: after building
   `inverse_of` it back-fills the reverse mapping
   (`inverse_of.setdefault(inverse, name)`, lines 311-312), and the
   declaration check accepts a name that is any declared inverse
   (`if lname not in link_types and lname not in inverse_of.values()`,
   line 354). `build.resolve_links` then puts the edge on both ends —
   `target.backlinks[inverse]` and `item.resolved_links[link_name]`
   (`src/refdes/build.py`, lines ~315-317).

## Change

`src/refdes/standards/hardware/v3/base.yaml` — one line added to
`types.decision.links`:

    recorded_by:    [log]

Nothing else about `decision` touched. v1 and v2 base.yaml untouched (frozen
released shapes). v3 `migration.yaml` untouched — the change is purely
additive: an item that omitted `recorded_by:` validated and built the same
way before and after.

## Test

`tests/test_standards.py::test_hardware_v3_decision_declares_recorded_by_and_the_link_resolves`
— the module that already asserts the bundled standards' declared
`types[*].links`. It asserts the declaration resolves on a `hardware@3`
project, then builds a `decision` carrying `recorded_by: [LOG-001]` against a
real `log` item and asserts no errors, `resolved_links["recorded_by"] ==
["LOG-001"]` on the decision, and `backlinks["records"] == ["DEC-001"]` on the
log — i.e. the edge lands on both ends under the inverse verb.

## Verification

- `python -m pytest tests/ -q` → 659 passed (658 baseline + 1 new), 0 failed.
- `git diff --stat -- .../v1/base.yaml .../v2/base.yaml` → empty.

## Note

`docs/design/threads.md` (design-only) records that this finding dissolves if
the thread model lands, since `log`/`decision` collapse into one chained item
type. Until then this is the valid one-line fix.
