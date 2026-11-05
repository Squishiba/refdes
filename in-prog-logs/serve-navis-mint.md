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

# serve navis mint — M1 implementation (slice: src only)

Task: implement `POST /api/navis/mint` to the contract above. Wrote
`src/refdes/serve/navis_mint.py` (~100 lines, renderer of
`navis.mint_keys(project, write=True)` into HTTP, styled on
`navis_write.handle`) and a 4-line route hook in `api.handle` (+import).
No test edited; the test file is the spec.

## Findings

- LOCKS: `mint_keys` takes no lock of its own — `revise.py` contains no
  `write_lock`/`project_write_lock` reference at all;
  `write_rewrites_verified` → `write_rewrites` → `textio.atomic_write_text`
  writes files directly. So the route's `write_lock_for(root)` is the only
  lock on the mint path, taken first per the documented order;
  `project_write_lock` is never touched here. No re-entrancy hazard;
  `state.refresh` takes only the `ProjectState` RLock (navis_write already
  calls refresh under the same lock, same posture).
- `still_keyless` SOURCE: the NAVI_MINT_REFUSED warnings mint_keys records
  on the project (delta across the call = the total; a read-only build
  emits none). Chosen over post-mint projection rows because the response
  promises THIS call, and the row count would also charge the caller with
  markers mint_keys never touched (a malformed marker is the corruption
  lint's report, not a mint refusal).
- Snapshot staleness verified over HTTP by the stale test: `mint_keys`
  re-reads each file at splice time and its line-exact check refuses an
  edited file (the user's bytes win); the untouched file mints in the same
  call. The losing concurrent request re-reads
  `app.state.snapshot.project` INSIDE the write lock, so it plans against
  the winner's committed state (its `still_keyless: 0` is left unpinned by
  the spec).
- stdout purity: verified on a live server (8817) — mint announcements
  (`_announce_navi_mints`) all land on stderr; stdout keeps only the
  launch-URL lines.

## Live capture (docs/navis.md, serve API section)

Writable `refdes serve --port 8815` + `--no-write` on 8816 against
`.scratch/serve-navis-mint/proj`; mint 200 with two minted markers, second
POST `changed:false`, GET 405, `--no-write` 403 with the mint-disabled
message. Item files show the spliced keys; no `.refdes/` directory created
by the route.

## BLOCKER found (later fixed with authorization): one test was unpassable

`test_two_simultaneous_mints_mint_each_marker_exactly_once` fails at its
line 547 on EVERY run against a correct implementation:
`_KEYED_RE.findall` over `note-a.md`+`note-b.md` also matches the fixture's
own hand-declared `HAND_KEY` marker, so the file-side list has 4 keys
against the winner's 3 minted. The extra item changes every run (= the
module-level `keys.mint()`). Proposed change (author's file, one line):
filter `if k != HAND_KEY` out of `keys_in_files`. Its other assertions
(each marker keyed exactly once, line counts) pass under the
implementation.

## HAND_KEY test fix (authorized)

The orchestrator independently confirmed the finding (27/28 unmodified;
28/28 with `if k != HAND_KEY` in the `keys_in_files` comprehension) and
AUTHORIZED exactly that one edit; applied (three-line wrap for the
100-char cap), nothing else in the test file.

## CI (PR #427)

pr-size PASS. Tests jobs red ONLY on the test file, on two counts:
(1) py3.13 job's single failure is the HAND_KEY bug (its only red test),
fixed as above with the authorization; (2) the 3.11 matrix (ubuntu+
windows, tests.yml:46) additionally TypeError-s in the two tests using
the file's `_text()` helper — `Path.read_text(newline=)` is Python 3.13+
(the local venv is 3.13.5, so the author's red run never hit it).
SECOND AUTHORIZATION (orchestrator, head 7faeebef): replace that one
helper body with `(root / rel).open(encoding="utf-8", newline="").read()`
(`Path.open` takes `newline` since 3.5; `write_text(newline=)` is 3.10+,
fine). Applied, nothing else; mint 28/28 + ruff green on 3.13.5 after.
Grepped the file, my new src module, and the doc code for other
3.12+/3.13-only APIs: none (test imports are stdlib + project modules;
`navis_mint.py` touches no version-gated API).

## Status

DONE (M1-impl). Touched-file runs after all edits: mint 28/28,
navis_write 57, docs anchors + crossplatform lint 14, ruff clean on
navis_mint.py (api.py: my lines only; pre-existing findings elsewhere
untouched). Full suite once before pushing: 5877 passed, 2 skipped, 1
failed (the HAND_KEY bug, fixed as above). CI expectation after the two
authorized test fixes: all 4 checks green (pr-size, ubuntu/windows on
3.11, py3.13).
