- An entry captured before #323 with a labelled ```calc fence no longer
  reports `edited after captured` on the first build after upgrading with
  nobody having edited it (finding R10-F5 of the run-10 release-gate
  simulation, a release blocker). That warning was permanent: its documented
  remedy, `refdes history capture` of the entry, is refused by the
  one-capture-per-item rule, and the only command that cleared it was
  `history redact`. The comparison in `capture_index` now also recognises a
  pre-#323 capture of an unchanged entry — the live entry's pre-#323 digest
  and its stored snapshot re-digested under the current formula — so an
  unedited entry is silent, and a label rename made after the upgrade stays
  silent (a label is not content). Real edits of an old capture, prose and
  calc rows alike, warn exactly as they did. The digest format and what new
  captures store are unchanged; sealing and baselines are untouched.
