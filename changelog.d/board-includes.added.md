- A board can now declare `includes: [GRP-...]` in the `boards:` registry:
  the members of those group items are displayed and listed on that board's
  scoped pages — document, parts, references, log, and `{{index board:}}`
  tables — labelled "shared, via GRP-...", and a board whose only parts are
  included ones now gets a parts page instead of none. Included items are
  never counted: summary numbers, coverage rows, and the release gate still
  cover only items the board owns, and the membership manifest, per-board
  seals, board-move warnings, and `items.json` are unchanged. Validation
  mirrors `conforms_to:` exactly — a bare string is a configuration error
  and a target that is not an existing group is a build error.
  (docs/design/backlog.md finding 33)
