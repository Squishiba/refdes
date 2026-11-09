- Two fixes to the `refdes serve` task pane's save seam. A clipboard that
  refuses the "Copy it out" copy (a denied permission prompt is the real
  case: `navigator.clipboard.writeText` rejects asynchronously, which the
  surrounding try/catch cannot see) no longer surfaces as an unhandled page
  rejection: the refusal is swallowed, the read-only transcript textarea
  stands, and a refused clipboard costs the copy, never the pane. And
  "Keep mine" in the conflict panel no longer works from a stale choice:
  it used to re-store the tick pairs captured when the panel was shown,
  so ticks added while the panel stood open were silently dropped. It now
  reads the draft's pending ticks at click time, keeping the current draft
  under the current tip key and revision -- the three outcomes and
  "nothing merges" are unchanged.
