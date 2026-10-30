- The browser editor's live-calc panel now computes spans from the unsaved
  draft, not just from the saved item. Typing in a form field input re-runs
  the panel on the same debounce the body keystrokes use: a span in the
  edited item that names one of its own fields (`DEC-001.$limit`) evaluates
  against the drafted value, so a row moves `ok` -> `stale` (or out of an
  error) as you type, and a `Fill` then lands the computed text — with
  nothing written to disk until you save. References from the edited item to
  *other* items' fields keep reading the saved items, so the preview's
  dependency surface matches the build's: the same input state, saved into
  the project, produces `refdes check`'s verdicts label-for-label. The
  `fields` bag on the `/calc` route, previously validated and carried, is
  consumed; its values must be scalars (collections and `null` are a 400,
  the same rule the save route applies).
