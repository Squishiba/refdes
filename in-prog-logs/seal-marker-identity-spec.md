# Seal marker identity — design note

Branch: `design/seal-marker-identity`. Docs only.

## What landed

- `docs/design/seal-marker-identity.md` — analysis of the
  `in-prog-logs/source-bug-sweep.md` finding that `history.migrate_seals` falls
  back to a display id as a `legacy-seal` marker's `item_key` when the sealed
  item is deleted and the record carries no surrogate key.

No code changed. `src/refdes/history.py` and all tests untouched.

## Verification done (not taken on trust)

- Derivation confirmed at `src/refdes/history.py:879`; marker id is
  `uuid5(kind, item_key, "")` (`history.py:301`), so the label is baked into the
  filename.
- **The keys.md claim holds.** `mint_missing` is defined over live items with a
  source file to write into; `keys.md:968-971` says carry-forward "does not
  manufacture that missing historical identity"; `keys.md:923-953` refuses to
  re-mint a deleted key before reporting it. Carve-out found: keys.md tolerates
  *naming* a dead identity (Layer 5, `keys.md:975-980`) — it objects to
  *manufacturing* one. That distinction is what keeps options (c)/(d)/(f) live.
- Minting is also mechanically broken here: `secrets.token_bytes` is not
  reproducible, so a re-run mints a different key and writes a second marker.
- **A derivation change duplicates rather than rewrites.** `append_event`
  short-circuits on an existing path (`history.py:355-366`); a changed derived
  id means the old marker stays and a new one appears. `load_events` cannot
  detect it (`history.py:406-411` checks the same edge under two ids).
  `HISTORY_FORMAT` bump alone would not distinguish the generations.
- **Adoption cannot heal it**: `keys.plan_surrogate_storage` re-keys a legacy
  seal entry only when its live item is identified and the hash carries, else it
  keeps the display id and reports uncomparable (`keys.py:349-358`). So the
  population does not shrink over time; it only disappears when the record is
  deleted via `--reseal`.
- **Unreleased**: `refdes history` is a pending `changelog.d` fragment with no
  `CHANGELOG.md` entry; this repo's `.refdes/` has no `history/`. Decision is
  cheap now, permanent after release.
- Two new findings surfaced while verifying, both written into the note:
  `_report_deleted` scans the **base** seal file only (`seal.py:354`), so an
  orphan record inherited into a board file is silent; and `migrate-seals` loads
  via `load_tree`, not `load_readonly`, so it never runs the seal verifier.
- `history redact <item>` requires a surrogate key (`cli.py:1260-1266`), so a
  display-id-keyed marker is unreachable by item redaction.
- Reader rule is mechanically checkable today: `keys.KEY_LEN` +
  `keys.malformed_key_message` (`keys.py:36,117`); display ids contain `-`,
  keys never do (`model.py:886-887`).

## Position taken

Recommend (f): leave the derivation exactly as-is; add a documented reader rule
("a `legacy-seal` marker's `item_key` is an identity only if it is a well-formed
surrogate key") plus an optional additive field and a migration-time report line.
(e) (refuse and report) named as the defensible alternative. (b) ruled out. (c)
and (d) rejected on the duplicate-marker and overlap-dedup/hash-stability
objections respectively — the sweep's claim that (d) is "most faithful to
existing idempotence" is argued against in §4(d).

Marked explicitly as a recommendation, not a decision. Seven open questions for
Jared in §6.

## Gates

- `pytest -q -x tests` — 2427 passed, 2 skipped (docs-only change; suite was
  already green and nothing was touched that it exercises).
- `ruff check --select E9,F src tests` — all checks passed.
