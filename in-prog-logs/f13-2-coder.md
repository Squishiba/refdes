# f13-2 — the editor write route refuses the keyless item's handle

Task: in a project with no surrogate keys minted, `/api/items` hands the
browser the keyless handle `~<relpath>:<line>`, the read route resolves it,
and editor.js posts exactly that to `POST /api/item/<handle>/edit` -- which
answered 422 `refused: no item '~...' in this file (it holds: REQ-001)`
because `serve/edit.py:_apply_locked` passed `resolved.handle` (the model
dict key) straight to `patcher.plan_patch`, whose aliases are only the
file's `id:`/`key:` values.

## What I did

- `src/refdes/serve/edit.py` (`_apply_locked`): translate the patcher ref
  -- `patch_ref = item.key or item.id or resolved.handle` -- so a save
  planned through the keyless handle is planned against the spelling the
  file carries (key when keyed, display id when keyless). The
  `resolved.handle` echo in `Applied` is unchanged (the read route echoes
  the same `~` handle for the same ref, so the parity of
  `payload["handle"] == GET["handle"]` holds for every spelling).
- `changelog.d/editor-save-keyless-handle.fixed.md`.
- A test module `tests/test_serve_edit_keyless_handle.py` was written and
  run here (yaml-list save via `~items/reqs.yaml:4` with comments
  surviving, md-front-matter save via `~items/notes.md:2`, display-id
  control, stale-line refusal with a byte-identical tree, forged-handle
  404/422, and a 409 conflict under the keyless handle keeping its diff),
  then REVERTED in a follow-up commit because that path is outside this
  coder's allowed globs -- the designer owns the test side. The fix was
  re-verified after the revert by a scratch drive of the same scenarios
  against a live `EditorApp`: `.scratch/f13-2-check/check_f13_2.py`, all
  six checks pass from a fresh project (key-handle save remains pinned by
  the untouched `test_the_keyed_handle_from_the_row_saves_the_yaml_item`
  in test_serve_edit_http.py, green in the suite runs below).

## Fix-site justification (one sentence, as the contract asks)

The edit route translates the keyless handle: the patcher's contract is
"ref is a display id or key, matched against the parsed `id:`/`key:`
values in this text", and a `~relpath:line` handle is not a file spelling
-- teaching the patcher the model's dict-key format and path/line
validation (which needs the project root the patcher never sees) would
widen its contract, while the route already has the loaded model, the
path, and the lock, and the handle's freshness is proven there by the
resolver's exact dict-key hit against the tree loaded from disk under the
write lock.

## Validation of the handle's relpath:line

Kept, not guessed: `resolution.resolve_ref` accepts a `~` spelling only by
exact `project.items` dict hit; the dict key is minted at parse from the
item's current `source_file:source_line`, and `_apply_locked` reloads from
disk under the write lock, so a stale line (file edited, item moved) and a
handle naming no item's definition both resolve to nothing -> the ordinary
"No item in this project" refusal (422), nothing patched. A conflict under
the keyless handle plans its draft against `patch_ref` (the file spelling),
so the 409 keeps its diff -- the `~` spelling never reaches the patcher.

## Known fallout (NOT touched, per the task's file rules)

Two pre-existing tests pin the OLD behavior and now fail -- they are
acceptance-side pins for the bug being fixed, owned by the designer:

- `tests/test_serve_edit_http.py::test_the_keyless_provisional_handle_still_refuses_and_writes_nothing`
- `tests/test_serve_edit_retired_ids.py::test_both_routes_accept_the_same_spellings_keyless`
  (the `ref == provisional` branch: asserts 422 "in this file"; now 200
  applied, which is the parity the test's own docstring demands).

Everything else green: the six serve-edit modules, test_patcher.py,
test_patcher_links.py, test_serve_api/state/create/custom_config = 293 +
394 passed, 2 failed (the two pins above). `ruff check` on the two touched
files: no new findings (one pre-existing DTZ011 in edit.py:1441, present
on the clean tree, untouched).

Status: finished.
