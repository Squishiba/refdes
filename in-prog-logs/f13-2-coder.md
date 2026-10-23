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
- `tests/test_serve_edit_keyless_handle.py` (new, 7 tests, all pass):
  yaml-list save via `~items/reqs.yaml:4` (comments survive),
  md-front-matter save via `~items/notes.md:2`, controls (display-id save
  on the keyless project, key save on a minted project), stale-line
  refusal (file header inserted -> handle moved -> 422 "no item", tree
  byte-identical), forged-handle refusal (404 read + 422 write, nothing
  written), and a 409 conflict under the keyless handle keeping its diff.
- `changelog.d/editor-save-keyless-handle.fixed.md`.

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
