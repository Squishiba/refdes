- **`refdes work` (living notes H7c).** The project-wide worklist as a
  command — every thread tip's open authored tasks, then one labelled
  `Derived (auto clears when fixed)` block whose rows are grouped under
  small per-kind headings. The authored tasks and the derived rows
  print as two separate labelled groups with separate numbering (derived rows
  carry no number and no checkbox and are never written back); every open task
  prints the entry that declared it and that entry's date, with a relative span
  only under an explicit `--as-of DATE` — without the flag the bytes never
  depend on the wall clock; a folded verdict prints together with its tip's
  open tasks; and a fork names every tip in its header, printing a
  `Tasks at <tip>:` block for each tip that still has open work, with no
  single current status anywhere. The derived block enumerates every gap that can be
  computed offline: uncovered/unverified active requirements, proposed/on-hold
  and conflicting (refused-fold) thread verdicts, blocked-by cascades and stale
  blockers, failing checks,
  unpinned citations and missing kept copies, and forked threads. Remote
  citation drift is deliberately absent — it is networked (`citations.refresh`,
  under `check --refresh` only) and `refdes work` never touches the network.
  The thread data comes from `refdes.threads.threads_projection()` (the same
  projection `refdes thread` renders and the `index` payload carries); the
  derived rows come from `refdes.threads.project_derived()`, which reuses the
  projection's own per-item row builder over the whole project. `--json` prints
  the projection as `{"threads": [...], "derived": [...]}`, with the load's
  key-minting notice on stderr so stdout is valid JSON even on a first run that
  mints keys. A read/list command, not a release gate, so a non-empty worklist
  exits 0; the command writes nothing (its build never seals, like
  `index`/`ls`/`thread`). See `docs/cli-reference.md`.
