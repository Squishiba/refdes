# editor-image-upload.md §17 Phase 0: the existing-image picker

Branch `editor/image-picker-phase0`, based on `origin/main` at `16bbc64`. Scope is
exactly §17's row "0. Picker": list the images the project already has, and
insert a relative reference into the open item's draft body. No upload, no
`POST /api/assets`, nothing from Phase 1 onward, no seal/HASH_FORMAT/conflict
work touched.

## Read first (the claims this implementation rests on)

- `docs/design/editor-image-upload.md` — §2 (what exists), §3, §4, §7 (the
  reference is inserted by the client into the draft; the server composes the
  path; alt defaults to the filename stem; never an empty alt), §14, §17.
- `docs/design/browser-editor.md` — Goals ("Existing images by picker; no
  upload" in "What v1 must deliver" item 5), Security (no generic file-read
  endpoint; the token gates reads too), Phasing "Later".
- `src/refdes/serve/api.py`, `src/refdes/serve/edit.py`, `src/refdes/serve/server.py`,
  `src/refdes/serve/security.py`, `src/refdes/serve/state.py`, `src/refdes/serve/preview.py`.
- `src/refdes/build.py` `_process_images` / `_search_image_src` /
  `_search_image_matches` / `collect_static_assets`.
- `docs/markdown.md` "Images and other local files" (relative lookup always
  wins; bare filename searched on `site.assets:`; two matches is an error).

## Two findings that shaped the design (both verified by running, not reading)

1. **`loader.load_readonly` runs the real build** (`loader.py:169` calls
   `build_mod.build(project, seal_write=False)`), and `build()` calls
   `collect_static_assets` (`build.py:2830`), which identity-maps **every** file
   under a declared `site.assets:` directory into `project.assets` — no
   reference needed. So the preview generation the server already serves carries
   `assets/figures/curve.png` verbatim, and `GET /preview/assets/<rel>` returns
   the bytes today. Probe: `.scratch/probe2.py` printed
   `assets/figures/curve.png` in the generation for an image **no body
   references**, and `.scratch/probe_picker.py` got a 200 for it.
2. **Therefore the picker needs no binary transport at all.** The thumbnail URL
   is the build's own answer — `project.assets[rel]` — served by the existing
   `_preview` surface, whose confinement is `PreviewManager.open_file`'s
   realpath `commonpath` check, gated by the session cookie, `nosniff`,
   `mimetypes.guess_type`, `PREVIEW_CSP` (`serve/preview.py:107-121`,
   `serve/server.py:436-453`). This is §16.10's rejected "generic file-read
   endpoint", avoided rather than built: the client names no path at all, and the
   reachable set is exactly the set a `refdes build` already publishes. It also
   means `citations.authorize_source_path`'s confinement is *not* needed here:
   there is no client-supplied path to confine. (Checked `citations.py:131-183`
   and `:481-506` before deciding — the source-picker design is still
   unimplemented and its endpoint takes a client path; this one does not.)

## Shape

- `GET /api/images?item=<handle>` — item-scoped, because the reference has to be
  relative to that item's own source file (the resolution rule in
  `docs/markdown.md`). Rows carry `rel` (project-relative, the build's own
  spelling), `name`, `alt` (filename stem, never empty), `bytes`, `src` (the
  path from the item's source file), `markdown` (the exact text to insert,
  composed server-side), and `thumb` (the preview URL from `project.assets`).
  Plus `asset_dirs` and `total`. No absolute server path leaves the process, the
  `shown()` posture of `api.py:310-316`.
- The walk is `state._asset_files`'s walk — the same one the revision token
  already watches and `collect_static_assets` already publishes — so the list
  can never name a file the build would not resolve. The extension filter on top
  is a *display* filter and says so; the build itself resolves by exact
  filename with no extension test.
- `src/refdes/serve/static/images.js` — the picker, in the shape `links.js`
  established: a filter input, a candidate list, a button per row. No inline
  script, no `eval`, imports `api.js`, no new op name.
- Insertion goes through the one draft: `setDraftBody` via the body textarea's
  own commit (`editor.js`), then the ordinary Save posts `set_body` with the
  ordinary `expected_revision` and the ordinary delta gate. No new server op,
  no new write endpoint.
- Read-only: nothing in the slice writes a file, so a `--no-write` server serves
  the picker normally (pinned by a test).

## Notes / difficulties

- The body textarea is built in `item.js` through `editor.bodyControl(value,
  existing)` but the picker needs to insert into it, so `createEditor` now keeps
  the current textarea in a local and hands the picker an `insert(text)`
  callback. The picker section is returned to `item.js` and placed in the Body
  section, under the textarea, where a body-insert control belongs.
- The inserted text wraps itself in blank lines unless the caret is already at a
  paragraph boundary, and a path containing a space or parenthesis is written
  `<…>`-wrapped — composed in Python so the client composes nothing.
- The thumbnail can 404 in one window: an image added after the snapshot the
  preview was rendered from. The row swaps in a text placeholder on `error`
  (`addEventListener`, never an inline handler).
- **A finding that changed the payload.** A filename markdown would
  percent-encode (a space, a non-ASCII character) cannot be referenced by any
  spelling at all: markdown-it emits `figures/thermal%20curve.png` and
  `_process_images` resolves the *rendered* `src` without decoding it, so the
  save is refused with "image src ... does not exist" (probe:
  `.scratch/probe4.py`). Verified against the renderer directly
  (`MarkdownIt("gfm-like", {"html": False, "linkify": False})`, the same
  construction `build.py:2685` uses). The picker therefore marks such rows
  `insertable: false` with the reason attached, instead of handing over text
  that cannot work. The predicate is `quote(src) == src`, which is conservative
  in the safe direction: a name it refuses can still work when typed by hand
  (`a(b).png`, `a#b.png`), a name it accepts is one no encoder rewrites.
- `state._asset_files` became `state.asset_files`: the picker's list and the
  revision token's watched set are now literally the same walk rather than two
  copies that have to be kept in agreement.
- One thing `test_serve_static.py`'s brace-balance check taught me: it does not
  understand comments, so an apostrophe in a JS comment can unbalance the
  parse. Reworded the comment rather than the check (the check is load-bearing
  for the no-Node claim).

## Status

Finished: endpoint, static module, wiring and styles, `tests/test_serve_images.py`
(23 tests), the `tests/test_serve_static.py` additions, docs notes in
`docs/design/browser-editor.md` and `docs/design/editor-image-upload.md`, and
`changelog.d/editor-image-picker.added.md`. `pytest -q -x` is green locally
(2320 passed, 1 skipped) and `ruff check --select E9,F src tests` is clean; the
PR's own CI run is the last gate.
