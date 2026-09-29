# Perf: editor save — one build instead of two

Task: `src/refdes/serve/edit.py` does two full project loads per save
(`loader.load_readonly` = `load_tree` + `build`). Investigate whether the
"before" load genuinely needs its `build()`, and cut it if it doesn't.

## What I measured first (not taken from the planning pass)

Synthetic corpora under `.scratch/perf-editor-save/` (`gen.py` = plain
requirement items, `genreal.py` = the repo's own `refdes-project.yaml` /
hardware@3 with markdown bodies, calc blocks and checks). Phase attribution
script: `.scratch/perf-editor-save/phase.py`, which mirrors `_apply_locked`
step for step with timers.

`projreal` (1224 requirements incl. long-bodied markdown items, 200 decisions,
200 tests), min of 5 runs:

```
1 before load_readonly       min=  210.6
6 patch                      min=  126.9
8 after load_readonly        min=  204.9
9 blocking_diag              min=    0.6
10 atomic_replace            min=    1.3
(everything else              min=    0.0)
SUM                          min=  544.5
split of one load: load_tree=56.6ms  build=150.2ms
apply_edit end-to-end:       min=  559.2
```

So per save: two loads ≈ 415ms of ~545ms, and **`build()` is 150ms of each
load's 210ms** — the parse/key-mint/link-expand half (`load_tree`) is only
~57ms. The other big chunk is `patcher.plan_patch`+`apply_patch` at ~127ms,
which is out of scope here (different module) but is the answer to the
planning pass's "remaining ~418ms unattributed": it is not unattributed, it is
the patcher.

## What the before snapshot is actually used for

Read every consumer in `_apply_locked` (edit.py) and the code each one calls:

| use | needs build output? |
| --- | --- |
| `_find_item` → `project.items` / `item_by_ref` / `items_by_id` | no — parse |
| `item.external` | no — `imports.load_imports`, which runs in `load_tree` |
| `_item_path` → `project.root`, `item.source_file` | no |
| `_conflict` → `before.root` | no |
| `seal.is_sealed` → `project.types`, `local_items`, `project.boards`, `load_seals` (disk) | no — and it deliberately walks *every declared board* rather than `item.board`, i.e. it is written to work pre-board-resolution, which is a build step |
| `_resolve_link_op` → `project.types`, `project.accepts_type` (`subtype_map` recomputed from `types`), `links.composite_for` (`item.id`/`item.key`; keys are minted in memory by `keys.mint_missing` in `load_tree`) | no |
| `_accept_pins` → `sources.accept_plan` → `propose_payload` → `_item_units`/`_item_names`, which read **`item.calcs`** | **YES** — `item.calcs` is populated by `build._run_item_calcs` (build.py:1271) |
| `_blocking_diagnostics` → `_errors(before)` | **YES** — but only when the candidate has an error to compare |
| `_blocking_diagnostics` → `len(before.local_items)` | no |

So: the full build is load-bearing for the before snapshot in exactly two
places — an accept (`request.pins` non-empty), and the delta gate's error-set
comparison. The gate only ever reads `_errors(before)` for keys that are in
`_errors(after)`: **with no error in the candidate, the before build's output
is never read at all.**

## Why deferring the build is safe (and why the accept is excluded)

- `load_readonly(config)` is literally `load_tree(config, require_ids=False,
  write=False)` + `build(project, seal_write=False, reseal=False)`, so the
  deferred form is the same two calls with a gap between them.
- Nothing between the two points writes to disk when `request.pins` is empty:
  `file_revision`, `is_sealed`, reading the target file, `patcher.plan_patch`,
  `_resolve_link_op` are all read-only, and `_accept_pins` returns immediately
  with no pins. `build()`'s own disk reads (`pages/`, images, `.refdes/`
  seals, `.refdes/citations.yaml`, `.refdes/history/`) therefore see exactly
  the tree an eager build would have seen — `tests/test_no_write.py`'s
  `test_load_readonly_leaves_whole_project_tree_byte_identical` is the
  existing proof that a `load_readonly` build writes nothing.
- `citations.verify` is documented hermetic ("touches no network") and there is
  no cross-build global cache in the build path (only `dates`' `lru_cache` and
  a thread-local MarkdownIt parser; `calc.set_unit_aliases` is re-set from the
  same config by both builds).
- The accept keeps the eager full build for two independent reasons: `accept_plan`
  reads `item.calcs` (build output), and `_accept_pins` *writes*
  `.refdes/citations.yaml`, which is state a build reads — building `before`
  after that write would not be the same build. `tests/test_serve_sources_accept.py`
  also monkeypatches `edit_mod.loader.load_readonly` for the non-overlay load;
  keeping `load_readonly` on the accept path leaves those tests untouched.

## Design

`_load_before(config, full=bool(request.pins)) -> (project, built)`:
`load_readonly` when `full`, otherwise `load_tree` only. Just before the gate,
`if not built and _has_gate_errors(after): build_mod.build(before,
seal_write=False, reseal=False)`. `_has_gate_errors` is `_errors`' own filter
(`level == "error"`, `code != CHECK_VIOLATION`) as a predicate, so the before
build happens exactly when the gate could read something from it. Same pattern
in `_create_locked` (`_creation_blocking` has the identical shape).

Both loads stay inside `write_lock_for(root)`; the overlay load stays the only
validation before bytes are written; the revision check, the sealed/imported
refusals and the `_accept_pins`/`_undo_accept` ordering are untouched.

## What the second pass found: deferring the build also deferred its `except`

The eager `load_readonly` sat inside `try/except Exception` returning
`Refused("the project did not load: ...")`. The deferred build did not, and a
project that *parses* but whose *build* raises is not hypothetical: `build()`
reads `.refdes/citations.yaml`, `.refdes/history/events/*.yaml` and image files,
none of which `load_tree` touches, and `build()` has no `try/except` of its own.
(`.refdes/`'s other state -- the seals and the boards manifest -- *is* read
during `load_tree`, by `keys.report_deleted_keys`, so those fail where they
always failed.) Two consequences, both reproduced by
`.scratch/perf-editor-save/raises.py`:

- the exception escapes `apply_edit`. `serve.api.handle` has no catch-all, so
  the browser gets a closed connection with no response, not a refusal; and
- even where the failure is shared by both snapshots (a corrupt lockfile breaks
  the candidate load too), the candidate load now fails *first*, so the refusal
  reads "the edited project did not load" when the edit has nothing to do with
  it.

Fix: `_build_before()` runs the deferred build and returns the eager load's
refusal reason verbatim. The gate calls it, and the candidate-load `except`
calls it too -- one extra build, on a path that is already refusing -- so an
unbuildable project is still blamed on the project. `raises.py` scenario A (a
corrupt `.refdes/citations.yaml`) now reports `same: True` across both
implementations.

The one difference the change cannot remove, stated plainly: **work not done
cannot fail.** A project that parses but will not build used to refuse every
save, including the save that would fix it. A clean candidate no longer builds
the on-disk snapshot, so that repair goes through. Narrow -- it needs a build
failure the overlay does not share -- and in the direction the delta gate
already faces (a pre-existing error never blocks the repair that is the reason
for the edit), but it is a difference.
`test_a_clean_save_never_builds_the_snapshot_it_compares_against` pins it rather
than leaving it to be rediscovered.

## Verification

- `pytest tests/` -- **2769 passed, 2 skipped** (run on the branch rebased onto
  `origin/main`; 2719 before the rebase). Six tests in all: the two build-counting
  ones, an unbuildable project refused as the project
  (`test_a_project_that_will_not_build_is_refused_as_the_project`, a real corrupt
  `.refdes/citations.yaml`, no monkeypatching), a raising deferred build coming
  back as a `Refused` and not an exception, the clean-save difference above, and
  `test_a_board_field_suggests_a_file_already_on_that_board` in
  `test_serve_create.py` -- which is the reason `create_item` keeps its eager
  build: `suggest_destination` reads `item.board` (edit.py:1112), and only
  `boards.resolve()` assigns it.
- `ruff check src/refdes/serve/edit.py --select I,F` -- clean. CI's
  `ruff check --select E9,F src tests` -- clean.
- `.scratch/perf-editor-save/equiv.py` -- **16/16 scenarios identical** between
  the eager `_load_before` and the shipped one: result kind, result repr and
  every byte of the tree (minted keys and revisions normalised). Covers clean
  edits, an introduced error, an already-broken field, a repair elsewhere on a
  broken item, a markdown body edit, three link cases, the sealed refusal, the
  unknown item, the conflict and four create cases.
- `.scratch/perf-editor-save/ab.py projreal REQ-PWR-0007 body` -- one process,
  one corpus, min of 5, on the rebased branch:

  ```
  eager before build (old)           Applied  min=  533.9  med=  546.6
  deferred before build (new)        Applied  min=  387.2  med=  394.0
  clean save: 533.9 -> 387.2 ms   (27% off)
  eager, candidate with an error     Invalid  min=  528.2  med=  544.7
  deferred, candidate with an error  Invalid  min=  529.3  med=  544.9
  ```

  A clean save gives up the before build's ~150 ms; a save the gate blocks costs
  what it cost before, because it needs that build.

## Status

Done. Both loads stay inside `write_lock_for(root)`; the overlay load is still
the only validation before a byte is written; `expected_revision`, the sealed
and imported refusals and the `_accept_pins`/`_undo_accept` ordering are
untouched; `create_item` keeps its eager build (the destination it suggests
comes from `item.board`, which only `boards.resolve()` assigns). Landing as one
commit with the changelog fragment.
