# serve navis mint — M1 tests (slice: tests only)

Task: contract tests for the NEW `POST /api/navis/mint` route (Jared
2026-11-05: "serve offers a mint"). Tests-only slice: wrote
`tests/test_serve_navis_mint.py`, did not touch `src/`; an implementer
continues on this branch (navis_mint.py / navis_write.py + api.py hook).
## What the file pins (28 cases, 18 test functions)

- success: project-wide mint of all keyless markers (`mint_keys` posture);
  200 `kind: ok`, `changed`, `minted` {key, key6, item, file},
  `still_keyless`; keys valid per `keys.malformed_key_message`, unique
  incl. against a hand-declared key; `file` repo-relative posix.
- BYTE-LEVEL: expected text regenerated from originals by reverse-splicing
  the returned keys (`_unsplice`) — nothing else changes; line counts and
  all other bytes identical; hand-keyed marker byte-intact; snapshot diff =
  minted files only; idempotent second call; the nothing-keyless noop is
  changed false with mtime_ns + bytes identical.
- body/transport: `{}` ok, extra keys ignored; non-object → 400
  `bad_request`; 403 gate-first under `--no-write` (malformed bodies too);
  token/Origin/Content-Type rules COMPARED against `/api/items/create`
  and `/api/navis/archive` (route-agnostic gates), never hard-coded.
- 405 on GET/PUT/DELETE. Refusals: folded list-file `body: >` marker
  (test_navis_mint recipe) → stays keyless, bytes untouched, counted in
  `still_keyless`, others mint. Stale: a file edited on disk after the
  snapshot is refused by provenance (the edit survives byte-for-byte)
  while the other file mints in the same call.
- freshness: forced rebuild before answering — `GET /api/navis` key/key6
  and the preview page's `key6` span mirror the sibling's
  `test_the_served_page_shows_archived_after_the_write`.
- locking: two simultaneous POSTs (barrier) → exactly one `changed: true`,
  loser `minted: []`, each marker spliced exactly once, joins time out →
  no deadlock. 500: OSError from the writer seam → `kind: error`, tree
  unchanged. Scope: the `.refdes/navis/` record bytes are unchanged and
  the store still loads after a mint; no store file added.

## Ambiguities resolved (stated choices)

1. "non-object/invalid JSON -> 400 {kind: bad_request}": raw-invalid JSON
   is answered by the server gate BEFORE the route (400 `{"error": "invalid
   JSON"}`, no kind — server.py:823-826, the sibling pins it that way). The
   file pins kind: bad_request for parsed non-objects (the handler's answer)
   and the sibling's 400+error posture for raw bytes.
2. Red-first vs route-agnostic gates: the token/Origin/415/PUT-DELETE
   expectations are green the moment the gates exist, so each transport test
   also asserts the tokened POST mints (200) — every test in the file is
   red today, and the transport tests pin the route is LIVE behind the gate.
3. OSError seam: `refdes.revise.write_rewrites_verified` — the writer
   `navis.mint_keys` imports at call time (the sibling's archive_record seam).
4. `still_keyless` on the losing concurrent call is NOT pinned (spec
   silent); only `changed: false` + `minted: []`. `minted` list order is
   NOT pinned; the byte-level check works by key set, per file.

## Verification

- RED: `PYTHONPATH=<worktree>/src ... pytest tests/test_serve_navis_mint.py`
  → 28 failed, every failure 404 `{"error": "not found"}` from
  `api.handle`'s fall-through (GET answers 404, not 405) — missing route,
  no typos. Full suite NOT run (test-author slice). `ruff check` clean on
  the file; cross-platform lint green (newline="", read_bytes, no fixed
  ports, no POSIX-only tools).
