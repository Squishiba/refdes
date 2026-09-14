Task: record decisions and results from 2026-09-14 into docs/design/keys.md (docs-only).

Progress:
- Fast-forwarded from main before changes (already up to date; worktree clean).
- Verified every fact against the repo before writing:
  - Adoption commit 0a37b1b is at HEAD; its message records 0 keys minted, 0 links
    expanded, log-seal-board-a.yaml 6/6 hashes carried, boards.yaml 21/22 with
    CON-THM-002 dropped, keys-adopted.yaml added, and an identical `check`
    diagnostic set before/after (1 error, 2 warnings, 20 items).
  - `.refdes/keys-adopted.yaml` present (adopted: true, format: 1).
  - `.refdes/log-seal-board-a.yaml` has 6 entries with hash_format: 2 and carried
    hashes; `.refdes/log-seal.yaml` empty (sealed: {}).
  - `.refdes/ids.yaml` has four burned prefixes (BND-THM, DEC-PWR, REQ-PWR, TST-PWR);
    no baseline file exists anywhere under .refdes/ ("no baselines currently stamped"
    still accurate); 20 items per check output.
  - Rename trial commit 3226700 exists: only the id: line and the display halves of
    the two inbound composites changed (verifies: and addresses:), key halves
    unchanged, no seal violation.
  - tests/test_keys_adopt.py contains tmp_path tests covering baseline/seal
    re-keying, uncomparable entries, rollback, idempotence (verified via grep).
- Edited docs/design/keys.md:
  - §10 eleven-characters bullet -> "Decision, 2026-09-14: eleven characters stays",
    citing Jared's review of the rename diff.
  - §9 item 2 -> Status: done — composite shape kept (rename diff evidence).
  - §9 item 3 -> Status: implemented, but precisely split: real project covered
    seals only (no stamped baselines); baseline half carried by tmp_path tests.
  - §7 "This repository's own project" -> adoption record (0a37b1b) with verified
    numbers; kept 20 items / 6 sealed / no baselines / four burned prefixes;
    added the re-sorted-by-key observation (adoption diff moves every line,
    no hash changed).
  - Implementation-status header -> this repo is adopted (0a37b1b); the
    revise.py/former_ids.py cleanup (§4) remains design only, deferred by Jared.
- Edited docs/design/backlog.md "Surrogate keys — remaining layers": the remaining
  §4 cleanup is now marked deferred by Jared on 2026-09-14 (was already listed as
  the one open cleanup; no other fact in this task was mentioned as open there).
- No changelog fragment: design-doc-only change, matching prior design commits
  (e.g. 2ce5649, 1fa52af) which touched only docs/design + in-prog logs.

Status: edits complete; full suite + commit pending.