- A conflicting `refdes serve` save of a source-value accept no longer
  deletes a *successful* save's pin. Reproduced by driving two cooperating
  accepts of the same item with the second's lockfile write landing in the
  window between the first's `.refdes/citations.yaml` write and its late
  revision check: the loser correctly returned `409 conflict`, but its
  rollback restored the lockfile bytes *it* had read — the pre-accept ones —
  so the winner's body, which names its pin, was left on disk with the pin
  gone, and `refdes check` failed the project with
  `calc '...': source(..., ...) has no locked value`. The accept's whole-file
  lockfile write cannot move inside the cross-process check-and-replace
  section without holding that lock across the candidate gate (which the save
  path itself notes "can take seconds"), so the rollback was made safe
  instead: `_LockfileWrite.rollback` now re-reads the lockfile and restores
  its snapshot only while the file still holds exactly the bytes this writer
  wrote; if another writer replaced it, the rollback leaves the file alone,
  which is the design's own inert-pin posture
  (`docs/design/editor-source-picker.md` §4) rather than a destroyed landed
  save. Single-writer refusals are unchanged — there the file still holds
  this writer's bytes, so the byte-identical rollback the §4 tests pin still
  happens. Pinned by
  `tests/test_serve_sources_accept.py::test_a_conflicting_accept_does_not_unpin_a_save_that_already_landed`.
