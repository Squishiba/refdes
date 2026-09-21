- `refdes check` and `refdes build` now warn when an item that was captured
  into `.refdes/history/` (a `follows:` predecessor) has since been edited:
  `LOG-001: edited after captured -- current semantic content differs from
  the snapshot in followed event <id>; captured when LOG-002 followed it`.
  This is a warning, never an error: the exit code and the build are
  unchanged, and the history store is only ever read. A corrected (superseded)
  capture does not warn; edits to an `on_change: log` field do. The
  `items.json` index carries the same fact per captured item as a
  `captured` / `edited_after_captured` pair (absent for uncaptured items).
