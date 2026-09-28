- `docs/getting-started.md` no longer dead-ends a reader on a permanently red
  build. The walkthrough fails `DEC-PWR-001`'s thermal check at step 5, adds a
  test and a log entry at steps 6 and 7, and never reaches green — and nothing
  on the page said so. Superseding the failed decision does not clear it: the
  decision's own numbers stay on the record, and `decision` ships
  `check_severity: error` for every status, so a `superseded` decision is
  still a build error. Added a short note at the end of the walkthrough saying
  exactly that, with the minimal `refdes-schema.yaml` overlay that demotes
  settled history (`default: error` / `superseded: info` / `rejected: info`),
  the mandatory-`default:` failure a reader hits if they omit it, and a
  pointer to the existing `check_severity` reference in
  [checks](checks.md#candidates-vs-decisions) rather than restating the
  feature.
