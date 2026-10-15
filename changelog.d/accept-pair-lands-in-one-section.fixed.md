- `serve` accept (#182): the source-value picker's accept used to write
  `.refdes/citations.yaml` *before* the candidate gate and restore the
  previous bytes on every refusal. That window runs both ways: a
  cooperating accept of the same key landing inside it makes this
  operation's write a byte-identical no-op, and the loser's rollback
  restores the pre-accept file -- erasing the winner's adopted pin from
  under the body that names it; and a cooperating accept can gate over a
  pin this one then rolls back, deleting it from under a landed body.
  Both leave a tree naming an unpinned pair, which is not §4's inert
  residue: `refdes check` fails the project. No predicate on the
  restore side can tell the erasing case from the one that requires the
  restore -- at refusal time the disk is byte-identical in both worlds.
  The fix is structural: the lockfile bytes are staged in memory, the
  gate judges the candidate through the loader's new `lockfile_overlay`
  (read-only window), and the pair -- lockfile then body -- lands in the
  save's final section, behind the revision check, in one section of the
  project's cross-process write lock. A cooperating writer that moved
  the lockfile during the gate is re-staged from, under fetch's own
  policy, not restored over. The restore that remains runs inside the
  same section as the write it undoes. Proven with deterministic
  interleavings in `tests/test_serve_sources_accept.py` and the rewritten
  topology proof in `tests/test_citations_lockfile_locking.py`.
