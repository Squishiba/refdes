- The global `--no-write` help text listed `id`, `revise`, `stub-tests`,
  `revision`, `release`, and `keys adopt` among the commands that report what
  they would change and write nothing, and left `calc-rewrite` out — even though
  `calc-rewrite` folds `--no-write` into `--dry-run` exactly as `revise` and
  `id` do, and `docs/cli-reference.md`'s global table listed it correctly. The
  flag's own documentation under-promised what it suppresses; it is now in the
  list, with a test pinning the whole set so the help text and the table cannot
  drift apart again.
