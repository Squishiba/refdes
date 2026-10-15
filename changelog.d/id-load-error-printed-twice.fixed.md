- `refdes id`: on a project where some files failed to load and an item was
  waiting for an id, every load error was printed twice -- once before the
  allocation, and again after it, because the post-allocation report printed
  the cumulative `project.errors`, which still held them. Each load error is
  now printed once; errors the allocation itself raises (a numeric-hint
  collision, a write-back refusal) are still reported, and the allocation
  report, the exit code, and the nothing-pending path are unchanged.
