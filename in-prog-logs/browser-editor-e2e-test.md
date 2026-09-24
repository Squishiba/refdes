# Browser editor: end-to-end author-session test

Task: add an automated end-to-end integration test for the browser editor's
full write path -- create, edit, link, conflict, sealed refusal -- as one
continuous session against a real running server, asserting file state as well
as API responses. Test-only; no changelog fragment.

## What landed

`tests/test_serve_editor_e2e.py`, two tests:

1. `test_a_full_author_session` -- the story. A temp project fixture (schema
   with `requirement`/`decision`/`log`, one sealed log entry produced by an
   ordinary writable build so the seal state is the one a real project has),
   served by a live `EditorApp`. Steps:
   - Step 0: `GET /api/item/LOG-001` already reports the entry uneditable and
     says "sealed".
   - Step 1: `GET /api/create/preview` promises `DEC-002` and reserves nothing
     (no ledger yet); `POST /api/items/create` delivers that id, a minted key,
     and the file revision. The file is a pure append (`startswith(DECS)`), the
     id is in `.refdes/ids.yaml`, and `GET /api/item/DEC-002` works without a
     restart.
   - Step 2: `set_field` on `DEC-002` using the revision step 1 handed back.
     The whole-file diff is exactly one replaced line, inside the new item's
     block; `reqs.yaml` and `log.yaml` are still the fixture's bytes.
   - Step 3: `add_link` with a bare `REQ-001`; the server writes the composite
     `REQ-001@<key>` into DEC-002's block, DEC-001's link line untouched
     (composite count goes 1 -> 2), and the whole-file diff is one region.
   - Step 4: two `set_field` posts race on the same stale revision. Exactly one
     200 and one 409; the 409 carries `current_revision` and a diff; the file
     contains exactly one of the two titles, and step 3's link survives.
   - Step 5: editing the sealed `LOG-001` is a 422 refusal naming "sealed", and
     the tree hash does not move at all.
   - Coda: across the whole session only `items/decs.yaml` and
     `.refdes/ids.yaml` ever changed.
2. `test_the_same_session_against_a_no_write_server` -- the same five
   operations replayed against `read_only=True`: every one a 403 whose `error`
   says `--no-write`, and the tree byte-identical at the end.

## Approach notes

- Reused the established harness rather than building a second one:
  `serve_support.Client` / `snapshot_tree`, `conftest.write_project_config`,
  `helpers._build_at`. No new HTTP client, no new fixture plumbing.
- Byte fidelity is `difflib.SequenceMatcher` over `splitlines(keepends=True)`,
  reported as (kind, old, new) regions -- `spans()`. A line-index diff would
  have been wrong for step 3, which inserts a line.
- Whole-tree hashing between every step (`snapshot_tree`) extends the
  `test_no_write.py` discipline to the composed session.
- Keys are minted at import so the fixture text can name the target's key;
  without that the composite written in step 3 is not assertable.

## Difficulties

- Two assertions were written against the wrong shape and were corrected by
  running them, not by guessing: DEC-001's `status: accepted` line precedes
  DEC-002's, so "the edit landed in the new block" needed `rindex`; and the
  patcher writes a lone link as `satisfies: REQ-001@<key>` rather than a
  flow list, so the composite assertion accepts either spelling while still
  rejecting a bare `REQ-001`.

## Verification

- `python -m pytest tests/test_serve_editor_e2e.py -q` -> 2 passed
- `python -m pytest -q` -> 2047 passed
- `ruff check tests/test_serve_editor_e2e.py --select E9,F` -> clean

Status: finished.
