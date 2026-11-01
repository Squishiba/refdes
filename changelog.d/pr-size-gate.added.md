- CI now gates PR size: a PR adding more than 350 lines under `src/` fails
  the `pr-size` check; split it into slices or add the `size-exempt` label
  to waive. Tests, docs, and tooling don't count; PRs below 400 are
  grandfathered. See `tools/pr_size.py`.
