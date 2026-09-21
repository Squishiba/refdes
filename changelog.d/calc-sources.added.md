- A calc block can read a named number from a repo-local CSV:
  `eff = source("analysis/power-budget.csv", "tps62913_half_load_eff") | 1`.
  The file is a same-item `citations:` path with a `key,value` table;
  `refdes fetch` extracts each used key once and pins it in
  `.refdes/citations.yaml` (`values:`), and `check`/`build` read only the
  lockfile. The `| unit` is mandatory and labels the bare number; every
  ambiguity (missing/duplicate key or header, blank or non-numeric cell,
  units, `1,000`, non-ASCII digits, overflow) is a fetch error that leaves the
  old pin untouched. A changed source file **warns loudly** — naming the file,
  key, locked vs current value and the exact `refdes fetch --update --path …`
  that accepts it, on the console and on the rendered calc row — while the
  build keeps using the locked value; `--require-citations` makes it an error.
  `fetch --update` prints `old -> new` and an advisory note on an exact 1000x
  change. See docs/math.md.
