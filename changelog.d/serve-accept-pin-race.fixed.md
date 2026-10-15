- The two-file transaction behind a `refdes serve` save of a source-value
  accept (`pin` with `set_body`) now holds under concurrent accepts of the
  same key: a loser's rollback no longer erases the pin a winner of the
  **same** key has adopted, and a winner's pin no longer disappears from
  under the body whose gate passed over it. The byte compare
  `_LockfileWrite.rollback` gained for #182 -- restore only while the
  lockfile still holds exactly the bytes this writer wrote --
  cannot see this spelling of the race:
  two accepts of the same key stage the same bytes, so the winner's own
  lockfile write is a no-op, the file still holds exactly the *loser's*
  bytes, and the loser's late revision check then compares them to nothing.
  Reproduced by driving an accept whose candidate gate stands in for the
  other process's applied accept -- body landed, lockfile untouched because
  its stage equalled what was already there: the loser returned
  `409 conflict`, its rollback restored the pre-accept bytes, and
  `refdes check` failed the project with
  `calc 'eff': source('analysis/budget.csv', 'eff') has no locked value`
  while the winner's body naming that pin was on disk. The rollback now
  re-checks the tree as well as the file, inside the same
  `write_lock.project_write_lock` section: `_accept_pins` hands the
  `_LockfileWrite` the `(canonical path, key)` pairs this write newly pins
  (`stage_source_pins`'s own diff of the pinned pairs) and the lines of the
  project as the accept read it that named them -- `(item, line)` pairs --
  and the rollback re-parses the project read-only and leaves the file to
  the winner unless the tree names those pairs with exactly those lines and
  nothing else. Naming *lines*, not named pairs, is what makes the check
  see the pre-named case: a pair the project was already naming, unpinned,
  when this writer read it is not exempt, because a cooperating accept of
  that pair stages the identical bytes, writes nothing, gates clean over
  the pin this write added, and lands -- adopting it. The window runs both
  ways, and the other side is closed from the winner: a cooperating accept
  that gates over this transaction's pin can fail and roll back inside
  this transaction's own gate -- its tree check cannot see a body that has
  not landed yet -- deleting the pin from under a body whose gate already
  passed over it. The final section, under the same lock that replaces the
  body, now asks the lockfile whether it still holds what this accept
  staged and puts a deleted pin back -- re-staged from the current records,
  under fetch's own policy -- before the body lands, so §4's pair lands
  together. What the accept added and nothing reads stays §4's inert pin
  the rollback cleans; what it added and something reads is a landed save's
  state now.
  The accept's whole-file write still sits outside the item's
  check-and-replace section -- moving it inside would mean holding the
  project lock across the candidate gate, which
  `docs/design/editor-source-picker.md` §4 declines for the seconds it
  would idle every other lock-taking writer; the tree question is answered
  under the lock instead, and the accepted costs are the work the lock now
  sections: `_accept_pins` snapshots the project's naming lines -- one
  authorized walk of its `source()` lines -- inside the write lock on every
  accept, and the rollback re-parses the tree on the refusal path. Five
  outcomes of the final-section re-check (lockfile unreadable, lockfile
  unparseable, a source file whose hash has moved, a failed replace, a lock
  that cannot be taken) refuse a save that has already passed its gate,
  both files as they were. Pinned by
  `tests/test_serve_sources_accept.py::test_a_conflicting_identical_accept_does_not_unpin_the_save_that_adopted_it`,
  `tests/test_serve_sources_accept.py::test_a_rolled_back_accept_does_not_erase_a_pin_adopted_over_a_pre_named_key`,
  `tests/test_serve_sources_accept.py::test_a_rollback_that_deleted_our_pin_inside_the_gate_is_reapplied_before_the_body`,
  and
  `tests/test_serve_sources_accept.py::test_a_gate_passed_save_is_refused_when_the_lockfile_cannot_be_repaired_midflight`.
