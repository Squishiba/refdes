# Phase H1 — the history store, with no call sites

Status: finished locally; not pushed, not merged (Jared reviews and lands).

## What landed

- `src/refdes/history.py` — the `.refdes/history/` store: `objects/<semantic-sha256>.yaml`
  and `events/<event-id>.yaml`, `semantic_payload`/`semantic_digest`, `save_object`,
  `load_object`, `event_id`, `append_event` (idempotent), `load_events`.
- `tests/test_history.py` — 19 tests, sabotage-style. Full suite: 1512 passed.

## Decisions taken inside the ratified design

- Event ids: `uuid5` over `(kind, item_key, successor_key)` with a fixed
  namespace (`uuid5(NAMESPACE_URL, "refdes:history:event")`), exactly as the
  plan's stated deviation requires. `occurred_at` excluded from the id and
  never used for ordering (`load_events` sorts by derived id).
- Digest covers the semantic core `{history_format, type, fields, links, body}`
  only; `key`, display `id`, and `source` file/line are *stored* in the object
  but excluded from the digest — same reasoning `compute_hashes` uses for
  excluding an item's own key/display id (identity and provenance are not
  content; a file move must not look like an edit).
- Found while testing: two captures of one state from different files/lines
  share a digest but have different `source` bytes. `save_object` therefore
  verifies the *semantic core* against the filename digest (corruption →
  loud `HistoryError`) and lets the first capture's provenance stand, instead
  of byte-comparing. Test: `test_same_state_from_different_files_shares_one_object`.
- Re-append of an existing edge whose `object` digest differs raises
  ("already captured") rather than silently keeping the first snapshot.
- Load refuses loudly on: missing/future/invalid `history_format`, missing
  required keys, unknown event kind, event id ≠ filename, and the same
  (kind, item_key, successor_key) edge recorded under two ids.

## parse.py check (not changed)

`parse.py:33` `RESERVED = {"id", "type", "history", "body", "former_ids", "key"}`:
`history` is engine-reserved, so no item can carry a field named `history`;
history's own metadata keys (kind, occurred_at, item_key, successor_key,
object, reason, history_format) live only in store files, never on items — no
collision possible. **`tasks:` is NOT in RESERVED yet** — the task-list phase
(H4/§5) must add it there; noted, not touched, per the task's scope.

## Not done (deliberate)

- No changelog.d fragment: no call sites, nothing user-visible.
- No CLI, no build change, no seal change, no `tasks:` — H1 boundary held;
  `.refdes/history/` is created only by an explicit `save_object`/`append_event`.
