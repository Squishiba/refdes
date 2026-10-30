- **Live inline calc in the browser editor.** The body editor
  recalculates inline calc spans while you type: the draft goes to the
  server on a short debounce (`POST /api/item/<ref>/calc`, evaluated in
  Python — the browser never learns the grammar) and a panel under the
  textarea lists each `:=` span as ok, stale, or error with its computed
  value, carrying the same message `refdes check` reports. Stale rows
  carry a Fill button; with the panel's "update results while I type"
  checkbox on — on by default, saved per browser under
  `refdes.live-calc.autofill` — stale result slots fill themselves as you
  pause, each fill one Ctrl+Z away and landing in the draft only. Where a
  browser's native undo cannot carry the edit, the panel says so,
  auto-fill stands down for the session, and Fill keeps working. The
  panel writes no text you did not ask for and touches no file:
  `check` and `build` remain the verdict.
