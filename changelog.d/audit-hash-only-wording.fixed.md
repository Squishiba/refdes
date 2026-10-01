- The docs no longer claim a hash-only remote citation's sha256 was checked.
  `docs/output.md`'s `state` table defined `"ok"` as "Resolved — hash on file",
  and `docs/cli-reference.md`'s audit section glossed `state` as "what
  verification found" — so an `audit` row reading `ok  hash-only  cited by
  CMP-PWR-001` said, in two places at once, that a comparison had happened. For
  a remote citation pinned with `keep_copy: false` nothing is on file to compare
  against: `check`, `build` and `build --require-citations` all exit 0 on a
  lockfile whose pinned digest is wrong, and only `refdes check --refresh`,
  which re-downloads, reports the drift and exits 1. That silence is by design
  and is unchanged. The `ok` row now says what was actually done — a local or
  kept citation's sha256 was compared against the bytes on disk, a hash-only
  one has no bytes here to compare and its sha256 is recorded, not verified,
  until `refdes check --refresh` — and the sentence under the table no longer
  says `ok` alone claims the sha256 is right. Pinned by
  `tests/test_audit_hash_only_wording.py`.
