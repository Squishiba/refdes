# Serve watches images as build inputs (editor-image-upload 15.1)

Decision: Jared, 2026-09-25 — images are part of the build, so `refdes serve`
watches them and folds them into the revision like every other project input.
This closes open question 15.1 of `docs/design/editor-image-upload.md`; it
does **not** implement upload, and it does not touch sealing or `HASH_FORMAT`
(15.6 stays open).

## What was wrong

`serve/state.py::project_inputs` listed config files, item sources, page
sources, `.refdes/` state and imports — no images. So:

- replacing an image moved no revision token (a body save could not see a
  swap under it), and
- `refresh()` diffed signatures over those same paths and returned `False`,
  so adding/replacing/deleting an image rebuilt nothing.

## What changed

`src/refdes/serve/state.py`:

- new `_asset_files(project)` — walks every declared `site.assets:` directory
  (`project.asset_dirs`) and returns every file under it. Missing directory →
  skipped, exactly as `_search_image_src` / `collect_static_assets` skip it
  (the build only warns there).
- `project_inputs` adds that set. Nothing else in the mechanism moved:
  `signature()` still does the cheap `(mtime, size)` pass, `content_hashes()`
  still fingerprints by whole-file sha256 (the existing spelling — images are
  fingerprinted the way every other input already is, and the poll tick never
  reaches it unless a stat differs), `revision_of()` is untouched, and the
  Poller/debounce logic is untouched. Windows paths go through
  `os.path.join`/`os.path.relpath(...).replace("\\", "/")` like the rest.

Why the whole directory and not the referenced subset: image resolution is a
query. `_search_image_src` matches a bare `src` against any file in any
declared directory, and `collect_static_assets` registers every file there
with no reference needed. So adding `photos/shared/curve.png` can turn a
working `![c](curve.png)` into the ambiguity error, and deleting a file can
turn a working reference into does-not-exist — both without touching any
document. Watching only referenced files would miss both.

## Tests (`tests/test_serve_state.py`)

- `test_every_file_under_a_declared_asset_dir_is_an_input` — nested files
  included; a declared-but-missing directory adds nothing and is not an error.
- `test_adding_replacing_or_deleting_an_image_moves_the_revision` — each of
  the three returns `refresh() is True`, changes the revision, and produces a
  new preview generation.
- `test_a_second_copy_of_a_bare_name_in_another_asset_dir_is_a_change` — the
  §9.1 ambiguity case: no existing file is touched, revision still moves.
- `test_files_outside_the_declared_asset_dirs_are_not_inputs` — a stray
  `.png` elsewhere in the tree and a non-directory lookalike leave the
  signature and revision untouched.
- `test_the_poller_rebuilds_on_an_image_change` — end-to-end through `Poller`.

Full gate: `python -m pytest -q` → 2128 passed; `ruff check --select E9,F
src tests` clean.

## Docs

- `docs/design/editor-image-upload.md` — 15.1 recorded as decided; §2, §8,
  §12, §14 and §16.7 annotated where the decision supersedes the draft.
- `docs/cli-reference.md` (serve section) and `docs/design/browser-editor.md`
  ("Preview freshness") now say the polled inputs include every file under a
  `site.assets:` directory.
- `changelog.d/serve-watches-images.changed.md`.

## Deliberately not done

- Upload, `expected_hash`, §9 conflict checks, the picker — untouched.
- Sealing / `HASH_FORMAT` (15.6) untouched: image bytes are still not in any
  sealed hash. This change is about the serve-side watch/revision only.
- Images outside `site.assets:` directories that resolve relative to a source
  file are still watched only through the source-file-adjacent path they are
  referenced by — i.e. not at all unless they sit in a declared directory.
  That is the same boundary the build's search path draws; widening it would
  mean walking the whole tree, which `docs/markdown.md` explicitly refuses.
