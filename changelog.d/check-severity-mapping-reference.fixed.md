- The status-mapped form of `check_severity` is now documented for readers, and
  the two places that claimed it did not exist are corrected. `docs/checks.md`
  §Candidates vs. decisions covered only the scalar (`check_severity: info`)
  form; the mapping — `default:` plus per-status overrides — was written down
  only in `docs/design/candidate-parts.md` §4 and one sentence in
  `docs/lifecycle.md`, neither of which a newcomer reaches from
  `docs/index.md`'s nav. Added a "Severity per status" subsection there with
  the mapping's shape, the rule that `default:` is mandatory (or every declared
  status listed outright), the exact load-time refusal a reader hits without it
  (`types.decision.check_severity does not cover status 'proposed'. Add it, or
  add default: <level>.`), the fall-through behaviour that leaves an unmapped
  status at `default:`, the three other load-time refusals, and the
  `component` mapping hardware@3 ships as the worked example. Separately,
  `docs/schema-reference.md` said `check_severity` "must be `error`, `warning`,
  or `info`", which is only true of the scalar form and has been actively wrong
  for any type whose `check_severity` is a mapping — including every
  `component` under the bundled standard. It now names both forms and links to
  the new subsection instead of restating it.
