- `refdes work` now prints the same `(N malformed row(s) not shown)` note on a
  thread's authored-tasks heading that `refdes thread` prints. It used to print the
  bare heading, so a worklist entry whose declared task list held a malformed row
  silently showed one fewer open task than the author declared it has.
