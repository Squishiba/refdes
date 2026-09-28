Config and schema validation errors now name their valid values in prose
instead of a Python repr. A bad `item_layout:` reads `item_layout must be one
of flat, workspace, got 'grid'` rather than a bracketed list repr, and the
same comma-joining now applies to `baseline_identity:`,
`cross_workspace_severity:`, unknown `release_gate:` rules, dangling
`required_when:` values, both forms of `check_severity:`, `on_change:` on a
field or a body, item-level `history:`, and `standard.base:`. A bad field
`type:` now lists the declared field types in the project's declared order
(`text, person, limit, ... enum`) instead of an alphabetized repr. A message
a human reads should not carry a Python repr.
