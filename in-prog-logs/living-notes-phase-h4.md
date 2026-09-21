# Living notes — Phase H4: `refdes history capture`, `redact`, and `migrate-seals`

Implemented on `ao/refdes-133/root` (merged `origin/main` first: `5794542`
-> `be2f9a1`, editor edit-service files only, no overlap).

## What landed

- `src/refdes/history.py`:
  - `capture(root, item)` — the manual `captured` event; idempotent by the
    derived id; carries `occurred_at` (the one clock H2's comment reserved
    for this command).
  - `redact(root, item_key=... | object_digest=...)` — transactional
    removal of matching objects/events plus one `redaction` event that
    names what was removed by digest and event id only.
  - `migrate_seals(project, capture_current=False)` — one `legacy-seal`
    marker per seal record in every `.refdes/log-seal*.yaml`; seal files
    read, never touched; `--capture-current` writes clearly dated
    `migrated-current` events only where the live content still matches
    the recorded hash (compared through `seal._matches_sealed_hash`, the
    one shared hash-format reader).
  - `EVENT_KINDS` gains `legacy-seal` and `migrated-current`; new
    `NO_OBJECT_KINDS = {legacy-seal, redaction}` — these kinds omit the
    `object` key entirely (a marker has no snapshot; a redaction event
    must not point at the content it just removed). `append_event` and
    `load_events` were narrowed for it; every other kind still requires an
    object.
  - `_CAPTURE_KINDS` gains `captured`: H4 is the writer H3's comment said
    would trigger it, so a manual capture followed by an edit produces the
    H3 warning (tested).
- `src/refdes/cli.py`: a `history` subparser group following the
  `keys`/`standard`/`former-ids` pattern, with `capture`, `redact`, and
  `migrate-seals`; all three refuse under `--no-write` through
  `_refuse_no_write()` (exit 2) before loading anything. The global
  `--no-write` help now names them.
- Docs: `docs/cli-reference.md` gains the three-command section and a
  `.refdes/history/` row in "Files the tool writes".
- Tests: `tests/test_history_commands.py` (19 cases — exact-write tree
  diffs, `--no-write` byte-identity including no history dir, idempotence,
  the no-leak sabotage (body text absent from output and every store
  file), shared-object orphan rules, redaction-event survival, store
  loadability and id==filename after redact, loud unknown-target errors,
  seal-file bytes unchanged by migrate-seals, capture-current match/differs).
- Changelog: `changelog.d/history-commands.added.md`.

## Resolved ambiguities (decisions, flagged for the reviewer)

1. **Event kind names.** The plan's prose says a `manual` event and a
   `redacted` event; the H1 store ratified the kinds as `captured` and
   `redaction`, and H3's `_CAPTURE_KINDS` comment already anticipated
   `captured` as the manual-capture kind. Used the store's names.
2. **Acknowledgement flag name.** The plan requires "an explicit
   acknowledgement flag" without naming it: `--confirm`, matching
   `former-ids propose --confirm`, the repo's only prior acknowledgement
   flag.
3. **Object-less events.** A `legacy-seal` marker is "recorded hash only;
   original content was not captured" (§H5), and a `redaction` event must
   not repeat removed content — neither has a snapshot to name. Rather
   than invent a fake digest, these two kinds omit `object`; `load_events`
   refuses an object-less event of any other kind exactly as before.
4. **Redaction event addressing.** Item target -> `item_key` = the item's
   key; object-digest target -> `item_key` = the digest (no item owns it
   necessarily). The event's `successor_key` carries a 12-hex fingerprint
   of the removal set, so a second, genuinely different redaction of the
   same target gets its own derived id instead of colliding with the
   first.
5. **What redaction does NOT remove.** Redaction events themselves (the
   audit trail must survive); events that merely point at the item as
   `successor_key` (they record other items); objects still referenced by
   a surviving event (content addressing lets identical items share one
   snapshot).
6. **`captured` joins the H3 comparison** (one-line `_CAPTURE_KINDS`
   change). H3's comment said it would when its writer existed; H4 is
   that writer. `migrated-current` deliberately stays out — it matches
   current content by construction, and letting it silence the diagnostic
   is a separate decision.
7. **Second-run messaging.** Q4 ("the line prints only when an event was
   actually written") governs the automatic capture line; an explicit
   command that said nothing at all would look broken, so the idempotent
   second run prints `... is already captured; nothing was written` — not
   a capture announcement.
8. **`--capture-current` match check** uses `build.compute_hashes` (run by
   the CLI only when the flag is given) + `seal._matches_sealed_hash`, so
   hash-format-migrated seal files compare correctly; an item whose
   content hash never matched is reported `differs` and not captured.

## Gap logged (H5 boundary)

- `migrate-seals` writes the markers, but nothing **reads** them yet:
  making sealing history-backed (the `sealing: history` type knob,
  `seal.verify()`/`_report_deleted()` scoping, the `links.py:623-634`
  refusal change, the `audit` sibling section) is H5 and was not touched.
  Until H5 lands, a migrated project still seals and errors exactly as
  before; the markers are inert-but-true records, which is what the plan
  means by landing the migration as one documented transaction in H4.
- The plan's H5 verification ("`refdes build` on this repo's own items
  with the six seals present exits 0, and after `history migrate-seals`
  `.refdes/history/events/` holds six `legacy-seal` markers") was
  spot-checked locally against a synthetic two-seal fixture, not against
  this repo's own `items/` tree, since running the migration over the
  repo's real `.refdes/` is a landing-time action, not a worker-branch
  one.

## Verification

- `python -m pytest -q` — full suite green.
- `ruff check --select E9,F` on touched files — clean.
