- The inline-calc stale-result warning no longer shows a number that looks
  accepted. The window rule is unchanged — a stored literal accepts a computed
  value within half of one place of its last written digit, decided on full
  values — but the message used to print the computed value at the project's
  `sigfigs`, which could round it *into* the window it just failed: raw
  3.4495 V outside the window of stored `3.5 V` (3.45..3.55), displayed as
  `now computes 3.45 V`, a number the author reads as passing. When the
  rounded display's own rounding interval touches the window, the warning now
  shows the raw value (`now computes 3.4495 V`) and the gap is visible.
