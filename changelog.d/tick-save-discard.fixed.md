- Two fixes to the `refdes serve` task pane's Save seam, from the run-17
  user-simulation report. Clicking **Discard** used to leave the **Save**
  button visible over an empty draft (its visibility recomputed only on the
  panel's `change` event, and Discard resets the checkboxes
  programmatically), inviting a no-op click: the pane's refresh is now
  wrapped with the Save button's redraw, so every refresh -- Discard
  included -- recomputes the button. And the conflict panel no longer lists
  ticks whose value already equals the file's ("yours open, the file has
  open"): only rows that differ (and the current rows you did not tick) are
  listed, and when none of your pending ticks conflicts with the file the
  panel says so in one plain line. The three outcomes -- Keep mine / Keep
  theirs / Copy it out -- are unchanged.
