# edit-03 — the editor's write route resolves retired ids

## Task

`GET /api/item/<ref>` resolves retired ids (`former_ids:`) but the write
route's `_find_item` (src/refdes/serve/edit.py) did not, despite its docstring
claiming parity. Fix in src/refdes/serve/ only, via ONE shared resolver
(no copy-paste), plus a changelog fragment. Acceptance tests are owned by the
designer (new file tests/test_serve_edit_retired_ids.py) — per the task rules
I did not write them.

## What I did

- New `src/refdes/serve/resolution.py`: `resolve_ref(project, ref)` returns a
  `Resolution(item, handle, retired, claimed_by)`. Accepted spellings, in the
  read route's order: `project.items` dict key (surrogate key / provisional
  handle), display id, key via `item_by_ref`, then a retired id scanned
  through the declared `former_ids:` fields. Live spellings run first, so a
  retired id that is a live id of another item resolves to the live item.
  Two items claiming the same retired id resolve to nothing; `claimed_by`
  carries the owners so the write refuses loudly.
  - The retired step scans the fields, not `project.former_ids`, because that
    map is build output and the write path's `_load_before` runs on an
    unbuilt `load_tree` snapshot where it is empty (verified: `_load_before`
    with `full=False` skips `build()`; `former_ids` is parsed in parse.py, so
    the fields are there). The scan applies the same exclusions
    `ids.collect_former_ids` applies (live ids, double claims), so on a built
    snapshot it agrees with the map.
- `api._find_item`: body replaced by a delegation to `resolve_ref`; docstring
  kept, with a pointer to the shared resolver.
- `edit._find_item`: same delegation (link-target/amend callers now accept
  retired ids too; composites are built from the current item, so the written
  text is the current identity).
- `edit._apply_locked`: asks `resolve_ref` directly. Ambiguous retired id ->
  `Refused` naming both claimants. The patcher is given the resolver's handle
  (`patch_ref`), i.e. the item's CURRENT spelling — a retired id is not in
  the file, so handing the raw request ref to `plan_patch` would refuse.
- `Applied` gained `item_id`/`handle`; the HTTP 200 payload from
  `api._apply_edit` now carries `"id"` and `"handle"` so the browser can
  correct its ref. "no item" refusal for unknown refs unchanged.
- `changelog.d/serve-write-route-retired-ids.fixed.md`.

## Verification

- `.scratch/edit-03/check.py` (scratch, HTTP level via `serve_support.Client`
  + live `EditorApp`): retired-id save lands on REQ-007 with response
  id/handle REQ-007; retired-id set_body lands on the right item; retired id
  that is a live id writes the live item; retired id claimed by two items ->
  422 naming REQ-001 and REQ-002, file byte-identical; unknown retired id ->
  422 "no item"; parity on a key-minted project: surrogate-key handle,
  display id, and retired id all read (200) and save (200), refusals agree
  (read 404 / write 422).
- Full serve suite green: `tests/test_serve_*` (703 passed, 1 skipped),
  `tests/test_serve_edit*.py`, `tests/test_no_write.py` posture file passes.
- `ruff check --select I,F,E9` clean on the three touched serve files
  (repo-wide ruff baseline is not clean; not touched).

## Notes / risks

- Behavior extension the contract implies: link targets given as retired ids
  (`add_link`/`remove_link`/`amends`) now resolve, writing the current
  composite. No existing test asserted the old narrower behavior.
- The read route's response for an ambiguous retired id stays a 404 (as
  today, since `collect_former_ids` leaves it out of the built map); only
  the write route adds the loud "names both claimants" refusal.

## Review rounds

PR #358 review (product code approved, test file only): tightened the parity
loops to assert the write's reported id/handle match the read route's per
spelling and that landed saves land inside REQ-001's own span (keyless
provisional handle pinned as the patcher's "in this file" refusal, not the
find's); `test_no_refusing_path_writes_anything` now drives both refusals
(unknown ref, double claim) through set_field/set_body/add_link in separate
project dirs with a finished docstring; dropped the trivially-true
`"REQ-001" in text` for a REQ-001-block assertion; fixed the
`make_root`/`serve_minted` return annotations to `Path`. 11/11 pass, plus the
serve edit/api suites. Round 2: the double-claim test now pins the
resolver's AMBIGUITY wording (former_ids / exactly one item / refuses to
pick one, no "no item" text) and both claimants by name; two tests added on
the real socket (EditorApp + Client): a retired-id save landing with the
current id/handle in the JSON, and the double claim answering 422 with the
ambiguity refusal. 46 passed with test_serve_edit_http. Round 3: F1 -- the
"collect_former_ids leaves double claims out" claims in resolution.py,
api.py and the changelog were false (the map keeps the FIRST claimant; only
live-id collisions drop out), rewritten, and the real read-route change
(double claim now 404s where it answered the first claimant) is pinned by a
new test; F2 -- _conflict now plans the draft with the resolver's live
handle (threaded patch_ref through all three call sites), so a retired-id
edit on a stale revision returns 409 with a real diff/current_text instead
of the blank screen (new test fails pre-fix, passes post-fix); F3 -- the
designer log's "zero threads, zero sockets / 11 tests" line corrected.

Task finished.

