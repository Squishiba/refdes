- `source()` used *only* in an inline calc span no longer gets advice that
  dead-ends. `refdes fetch`'s key discovery reads calc fences only, so for a
  span-only key it hashes the file, extracts nothing, and the same "has no
  locked value" error returns forever — the message's `run 'refdes fetch
  --path ...'` advice was a loop with no exit. The span-form diagnostic now
  says the span form is never pinned and points at the fence form (where
  fetch does extract keys); the fence form keeps its original advice, which
  works.
