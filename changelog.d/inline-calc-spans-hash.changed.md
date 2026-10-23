- **`HASH_FORMAT` is 6: inline calc spans are dependencies and arithmetic.**
  A cross-item reference inside an inline calc span (`V_in := DEC-001.V_in`,
  the whole right-hand side) is now a real dependency: `refdes build`
  evaluates the referenced item first (closing the slice-1 scheduler gap that
  ran spans ahead of their targets), its resolved key and resolved value
  enter the referencing item's content hash, and `refdes fetch` pins the
  `source()` keys a span names — so editing a referenced value marks the
  span's item stale, and editing a `source()` input moves its hash, exactly
  as a fenced calc line already did. The arithmetic of a span — its name, its
  right-hand side, and its unit assertion, never the author's written-out
  result — now feeds the baseline's narrow arithmetic probe (`calc_hash`), so
  an inline-only item finally gets a `calc_hash`, and an edit to a stored
  result can never masquerade as an arithmetic change. The two slice-1
  diagnostics that told span authors to move to the fence form are gone,
  because the fence is no longer required. An item with no triggered inline
  span has a byte-identical hash payload and is untouched by the bump; a span
  with only literal arithmetic keeps its old content hash (it gains only a
  probe, which content hashing never reads). Baselines and seals recorded
  under hash format 5 migrate by the usual carry-forward rule (an entry moves
  only when its content is provably unchanged under its own recorded
  definition), and a span's arithmetic change that predates its item's first
  format-6 stamp is undetectable and grandfathered, because the old record
  never stored a span probe. Rollout caveat for shared projects: the
  lockfile is rewritten whole by `refdes fetch`, and pre-slice-2 code does
  not discover a span's `source()` calls, so one `fetch` by a collaborator
  on the old code drops the `values:` pins a span names (recoverable -- a
  `fetch` on the new code re-pins them; until then the span does not
  evaluate: `refdes check` fails it with
  `source(...) has no locked value -- run 'refdes fetch --path ...'`, an
  error, not a stale-value warning). Everyone working in a project that
  pins span sources must be on this version before relying on those pins.
  Decides `docs/design/inline-calc.md` §3; details
  in `docs/math.md`, `docs/change-tracking.md`, and `docs/lifecycle.md`.
