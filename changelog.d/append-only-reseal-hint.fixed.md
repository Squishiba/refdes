- The append-only violation error names the command to run: it now reads
  `or run with refdes build --reseal ...` rather than a bare `--reseal`. The
  same error is printed by `refdes check`, which has no `--reseal` flag, so
  following the advice on the command that printed it produced a usage dump
  and exit 2. The deletion half of the same error had the identical defect and
  is fixed with it; a board-scoped violation still names
  `refdes build --reseal <board>`.
