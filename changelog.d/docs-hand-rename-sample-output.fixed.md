- `docs/troubleshooting.md`'s hand-rename sample now shows every line `refdes
  check` prints for it. Run literally, in the two-item project the block's own
  YAML trace describes — a `REQ-001` that a `REQ-002` `refines:`, a writable
  `refdes check` to expand the reference, then the hand edit of the target's
  `id:` — the second check prints

  ```
  (rewrote 1 reference(s) while loading)
  WARNING <project> — 2 item(s) with no coverage — see coverage.html
  2 items, 0 errors, 1 warnings
  ```

  and the page's block had the first and last of those three lines and not the
  middle one. The count line already matched character for character, and it
  still does; the missing line is the two-item project's own coverage warning,
  which has nothing to do with the rename and is now called out as such, so the
  next reader does not go looking for a third cause. Finding F5 of
  `in-prog-logs/user-sim-release-gate-run4.md`, reproduced here rather than
  taken on trust.
