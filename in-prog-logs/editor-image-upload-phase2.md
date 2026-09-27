# editor-image-upload Phase 2 — Conflicts

Branch `editor/image-upload-phase2`, based on origin/main (includes Phase 0
picker #50 and Phase 1 "Bytes" #52). Scope is exactly §17 row "2. Conflicts":
`expected_hash` and the replace path through `_atomic_replace` (§8), the §9.1
ambiguity check, the §9.2 capture check over `Project.image_results`, and the
§9.3 referencing-item disclosure. Explicitly NOT in scope: §10 sealed-target
and sealed-referenced refusals (Phase 3), the client (Phase 4), the docs pass
(Phase 5). No change to `docs/design/editor-image-upload.md` — Phase 1 shipped
without one either, and §17's table is the docs pass's to edit.

## What I read first, and what it settled

- `docs/design/editor-image-upload.md` §8, §9, §11, §14, §17 (the whole
  file), `src/refdes/serve/upload.py`, `src/refdes/serve/api.py`,
  `build._search_image_src` / `_search_image_matches` / `_process_images`,
  `model.Project.image_results`, `serve/edit.py`'s `_atomic_create` /
  `_atomic_replace` / `_restore` / `write_lock_for`, `serve/state.py`'s
  `asset_files` / `_build`, `docs/markdown.md`'s bare-name search section, and
  `tests/test_serve_upload.py` for the fixture style.
- Ran rather than recalled, per AGENTS.md. Two probes in `.scratch/` settled the
  facts the implementation rests on:
  - `probe_phase2.py`: in a *served* project, `image_results` is keyed by
    display id (`"DEC-001"`), each record `{src, ok, rel, dest}`, and a bare
    `curve.png` in `items/decs.yaml` shows up as
    `{"src": "curve.png", "ok": true, "rel": "figures/curve.png", ...}`.
  - `probe_image_results.py`: `load_project` + `parse.load_items` +
    `build.build` populates `image_results` without a live server, and writes
    **nothing** into the project. That is the `built_project()` helper the
    service-level tests use — the same three steps `tests/test_image_hash.py`
    uses, so a test that snapshots the tree around a `store_asset` call is still
    comparing like with like.

## Design decisions taken while reading

- **`store_asset` takes the `Project`, not a root path.** The §9 checks are
  questions about what the *build* resolves. A path cannot answer them, and
  re-deriving the rules here would be a third spelling of image resolution that
  can drift from `build._search_image_matches` and `docs/markdown.md`. So the
  module imports and *calls* the build's own search, and reads the build's own
  `image_results`. The alternative — an optional `project=None` that silently
  skips the checks — is exactly the silent hole this phase exists to close, so
  it was not taken. The six Phase 1 test call sites now build a project first.
- **§9.1's condition is stated as what the build would do**, not as a
  comparison of directory lists: refuse when `_search_image_matches` would
  return more than one candidate *after* this write. Concretely, three guards:
  the leaf is not already one of the matches (a replace adds nothing to the
  search), the destination is on the search path at all (`_on_search_path`, by
  real path, so §4's default destination can never trip it), and there is at
  least one existing match. The design's own words are "if the leaf already
  exists in a *different* declared directory than the destination"; the build's
  version is the same rule with the directory list replaced by the resolution
  the build will actually perform.
- **§9.1 is about *adding* a second file with that leaf, so a replace of an
  already-ambiguous leaf is not refused.** The design's rule is a pre-write
  check, and a replace adds no file to the search: it changes no reference's
  resolution. Refusing it would refuse a repair. Pinned by
  `test_a_replace_adds_nothing_to_the_search_path`.
- **§9.2's scope is exact directory equality, not a prefix.** An item's
  relative lookup base is `dirname(its own source file)`, so only items whose
  source file sits *in* the destination directory can be captured;
  `items/decs/foo.yaml` is not captured by an upload into `items/`. Pinned by
  `test_a_bare_reference_one_directory_away_is_not_captured`.
- **A reference that resolves to *nothing* is a capture too.** The design's
  rule is "whose resolved `rel` is not that directory", and `None` is not that
  directory. The task brief's phrasing is narrower ("currently resolves to a
  different file, or resolves ambiguously"), so I made the superset choice and
  worded the two cases differently: a reference that resolves elsewhere vs. one
  that resolves to nothing today (a build error, which landing the file would
  silently retire). The narrower reading would have let a file land in `items/`
  and turn a sibling document's dangling `![x](todo.png)` into a rendered
  image nobody asked for. Worth Jared's eye if he disagrees — it is one `if`.
- **The current item is not carved out of §9.2.** The design scopes the check
  by directory and never says "except the one you are editing"; a bare
  reference in your own body that a new file would re-point is the same silent
  change, and the refusal names the item so you can see it is yours.
- **A matching `expected_hash` with identical bytes is still §5 row 2** (no
  write, `created: false`, `replaced: false`) rather than a pointless rewrite of
  the same bytes. §5's idempotence outranks the replace.
- **§8's four rows map to three distinct machine-readable outcomes**, because
  the client has to do different things with each: `Conflict` 409 with
  `conflict: "collision"` (§5's differing bytes) or `conflict:
  "expected_hash"` (a hash that no longer matches, or a hash for a file that is
  gone), and `Refused` 422 with `refusal: "ambiguity"` / `"capture"`. The design
  capitalises *Conflict* in §8 and *Refuse* in §9, and that maps exactly onto
  the two existing dataclasses, so I followed its vocabulary.
- **A malformed `expected_hash` is a 400**, not a conflict: a value that could
  never match anything is a typo in the request, not a state disagreement.
- **§9.3 discloses on every outcome that leaves a file at the path** — the
  409 before the author confirms and the 200 after — as `referenced_by` rows
  (`item`, `source_file`, `srcs`), all project-relative. The disclosure before
  is what §9.3 and §15.7 actually ask for; the one after is free, and a client
  that re-issues without re-reading the conflict still learns what moved.
  §9.3's "if any referencing item is sealed, this becomes a refusal instead
  (§10)" is deliberately *not* implemented — that is Phase 3.
- **All three checks run inside the existing write lock**, next to the §5
  table: they are all check-then-act, and an unguarded one can be raced by a
  concurrent upload of the same leaf.
- **A fresh create gets no `referenced_by`** (the file did not exist, so
  nothing resolves to it) — the field is computed, not asserted, which
  `test_a_collision_nobody_references_discloses_nobody` pins.

## Progress

- [x] Read the design and the code (see above), and probed `image_results`
  rather than trusting the docstring.
- [x] `expected_hash` format check, the four §8 rows, and the replace through
  `_atomic_replace` inside the same lock.
- [x] §9.1 ambiguity refusal over `_search_image_matches`.
- [x] §9.2 capture refusal over `Project.image_results`; §9.3 disclosure.
- [x] `api.py`: `expected_hash` from the query, and the new payload fields.
- [x] Tests: the four §14 tests this phase owns, plus 20 more (24 new test
  functions; `pytest` reports 29 new cases, two of them
  parametrized).
- [x] Changelog fragment; full suite + ruff; commit, push, PR, CI green.

## Finished

Task complete. `tests/test_serve_upload.py`: 91 passed / 1 skipped (the
case-insensitive collision, off Windows). Full suite `pytest -q -x` green at
**2454 passed, 2 skipped**. `ruff check --select E9,F src tests` clean.

What landed:

- `src/refdes/serve/upload.py` — `store_asset(project, dest=, name=, data=,
  expected_hash="")`; `Uploaded.replaced` / `.referenced_by`, `Conflict.kind` /
  `.current_hash` / `.current_size` / `.referenced_by`, `Refused.kind` /
  `.details`; `_check_expected_hash`, `_on_search_path`,
  `_referencing_items`, `_ambiguity_refusal`, `_capture_refusal`.
- `src/refdes/serve/api.py` — `expected_hash` query parameter; `replaced` and
  `referenced_by` on 200, `conflict` / `current_hash` / `current_size` /
  `referenced_by` on 409, `refusal` / `details` on 422.
- `tests/test_serve_upload.py` — the §14 tests this phase owns
  (`test_upload_that_would_create_ambiguity_refuses`,
  `test_upload_that_would_capture_a_bare_reference_refuses`,
  `test_replace_reports_every_referencing_item`,
  `test_atomic_replace_rolls_back_on_verify_mismatch`) plus 20 more (24 new test
functions, 29 cases counting the parametrized ones); the six
  Phase 1 service-level call sites now pass a built `Project`.
- `changelog.d/editor-image-upload-conflicts.added.md`.

Difficulties and things worth keeping:

- **Editing tools misplace code if the anchor is not unique.** Two `return
  kind` lines exist in `upload.py` (one in `sniff_image`, one in `_check_type`)
  and an insert anchored on the bare `return kind` landed the §9 block *inside*
  `sniff_image`, which then failed to parse. The file was reassembled with an
  explicit line-range script and the misplaced tail restored. Lesson for the
  next pass: anchor on the whole statement plus its surrounding lines.
- **Reaching `_atomic_replace`'s rollback branch needs sabotage.** The
  verification is a re-read of the file after `os.replace`; the only way to make
  it disagree is to let the real `os.replace` run and then write different
  bytes over the destination. The test patches `serve.edit`'s `os.replace`,
  calls `store_asset`, and `monkeypatch.undo()`s immediately so the patch is
  not live for the assertions.
- **A refusal for a dangling reference is the one place I read the design
  more literally than the task brief** (see the bullet above). It is the only
  interpretive call in this phase; everything else follows the text directly.
- **`image_results` is keyed by display id, not by the `items` dict key.** The
  filter fixture's keys are handles like `~items/decs.yaml:3`, so looking an id
  up in `project.items` directly would find nothing; the check builds an
  `id -> source_file` map from `project.items.values()`.
- **Not done, per §17:** §10's sealed-target and sealed-referenced refusals
  (Phase 3), any client UI (Phase 4), and the docs pass (Phase 5) including
  `docs/markdown.md` and the `browser-editor.md` Deferred/Later lists. So the
  replace path currently changes what a sealed entry's page shows — loudly, in
  the sense that hash format 5 moves that item's `content_hash`, but not by an
  editor-side refusal. That is Phase 3's row.
- **The two "premise" tests are the ones worth keeping.** Each writes the file
  the endpoint refuses to write, and then shows the damage with the build's own
  answers: `items/curve.png` re-points DEC-001's *and* TST-001's image with no
  error anywhere, and a second `curve.png` on the search path produces
  `_search_image_src`'s "is ambiguous ... (figures/curve.png,
  photos/shared/curve.png)" error against `items/decs.yaml`. Without those two
  tests the checks are guarding something a reader has to take on faith.
- **A same-text save does not rebuild**, which cost me one debugging round while
  writing the capture premise: `refresh()` compares content hashes, so re-saving
  identical bytes leaves the revision where it was and the resolution is never
  recomputed. The premise test re-saves with a changed alt text, and the helper
  says why.
- One unrelated flake observed while running the suite: a server thread logged
  `Exception occurred during processing of request` once during a full run and
  not on a repeat, and not in any serve test file run on its own. Pre-existing
  (`BaseHTTPRequestHandler` logging a client that disconnected mid-response);
  it did not fail a test.
