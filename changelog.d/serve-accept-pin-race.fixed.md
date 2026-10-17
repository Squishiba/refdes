- The two-file transaction behind a `refdes serve` save of a source-value
  accept (`pin` with `set_body`) now holds under concurrent accepts of the
  same key. A save that pins a key two people pick at once: a loser's
  rollback no longer erases the pin a *winner* of the **same** key has
  adopted -- the byte compare `_LockfileWrite.rollback` gained for #182
  reads "still mine" there, because two accepts of the same key stage the
  same bytes and the winner's own write is a no-op -- and the rollback now
  asks the tree, in the same lock section, whether the naming lines are
  still the ones the accept read; they are checked as `(item, line)` pairs,
  so a winner landing a second line over a pair the project already named,
  unpinned, is an adoption the restore cannot erase. The window runs both
  ways: a cooperating rollback can delete a pin between the gate that
  passed over it and the body that names it, so the final section, under
  the lock that writes the body, puts the pins back before the body lands
  -- re-staged from the current records under fetch's own policy. That
  re-check can itself fail (lockfile unreadable, unparseable, a source file
  whose hash has moved, a failed replace, a lock that cannot be taken):
  the save comes back `Refused`, both files exactly as they were, and
  nothing lands half. What the accept added and nothing reads stays §4's
  inert pin; what it added and something reads is a landed save's state
  now. The mechanism and its costs -- the naming-lines snapshot inside the
  write lock on every accept, the tree re-parse on the refusal path -- are
  in `docs/design/editor-source-picker.md` §4. Pinned by
  `tests/test_serve_sources_accept.py::test_a_conflicting_identical_accept_does_not_unpin_the_save_that_adopted_it`,
  `tests/test_serve_sources_accept.py::test_a_rolled_back_accept_does_not_erase_a_pin_adopted_over_a_pre_named_key`,
  `tests/test_serve_sources_accept.py::test_a_rollback_that_deleted_our_pin_inside_the_gate_is_reapplied_before_the_body`,
  and
  `tests/test_serve_sources_accept.py::test_a_gate_passed_save_is_refused_when_the_lockfile_cannot_be_repaired_midflight`.
