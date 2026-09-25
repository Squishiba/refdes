# Editor image upload design doc

Task: draft `docs/design/editor-image-upload.md` — the design behind the one
deferred item of `docs/design/browser-editor.md` that has no spec behind it:
"Image upload/copy and binary conflict policy" (`browser-editor.md:1072`).
Docs only; no implementation.

## Status

Finished. One new file: `docs/design/editor-image-upload.md`. Branch
`ao/refdes-164/editor-image-upload`, PR open against `main`. Not merged.

## What landed

- **§2 what exists today**, every claim verified against the tree or a run:
  the delta gate already refuses a body edit that references a file not on
  disk, and the text-only `source_overlay` cannot pre-stage a binary, so
  upload-before-save ordering is forced rather than chosen; images are absent
  from `serve.state.project_inputs`, so an upload moves no revision and triggers
  no preview rebuild; `_atomic_create`'s `os.link` is already a
  create-must-not-exist binary write; `EDITOR_CSP` already allows a `data:`
  preview; the v1 "existing images by picker" item never shipped.
- **§4-§6 destination, naming, limits.** Default destination is the item's own
  source directory (the one place a reference can never drift); collisions
  refuse rather than suffix; type is sniffed from bytes, not extension or
  client `Content-Type`; SVG refused on the CSP argument, not taste.
- **§7 the upload never touches a body.** Client inserts into the draft; the
  ordinary `set_body` path writes it. Orphans accepted, never auto-deleted.
- **§8-§9 what a binary conflict is** — three distinct things: `expected_hash`
  mismatch at the destination, new search-path ambiguity, and capture of an
  existing bare-name reference. The last two are conflicts against documents the
  author is not editing, and both are computable before the write from
  `Project.image_results`.
- **§10 seals.** A seal hashes body text, not image bytes, so replacing a file
  behind a sealed entry changes what it shows while the seal still verifies.
  Recommendation: refuse such a replace from the editor; the `build`-side check
  is left open because it costs a `HASH_FORMAT` bump.
- **§11-§13** transport (`POST /api/assets`, raw bytes, no multipart), the
  forced preview rebuild, and why the git-status objection is the weakest of the
  original five.
- **§14** 21 named tests, **§15** 10 open questions each with a recommendation,
  **§16** 11 rejected options, **§17** 6 phases with Phase 0 = the picker that
  never shipped.

## Deliberately not done

- **No `changelog.d/` fragment.** Precedent: the two previous design-spec-only
  commits (`f1697d3` named-calc-blocks proposal, `87c32e5` thread-workbench)
  carry none. A design spec for an unimplemented feature is not a user-visible
  change; the fragment belongs with the implementation.
- **No changes to `browser-editor.md`.** Its Deferred and Later lists still
  describe reality — upload is deferred, and this spec is proposed rather than
  decided. Update both when Jared decides.

## Verification done

Three probe scripts under `.scratch/` (gitignored), run against `src/`:

- `probe_edit_missing_image.py` — `apply_edit` + `SetBody` referencing
  `figures/curve.png` with no such file → `Invalid: blocked: the edit would
  leave 1 error(s): image src 'figures/curve.png' does not exist`, source file
  unchanged. This is §2's ordering constraint and §7's whole justification.
- `probe_image_overlay.py` — `serve.state.project_inputs` over a project
  holding `items/figures/missing.png` returns only `items/dec-a.md` and the two
  config files; the image is not a semantic input. Once the bytes exist, the
  build resolves the reference and `project.assets` gains the hashed leaf.
- `probe_overlay_binary.py` — an overlay entry naming a `.png` path is inert:
  the candidate build still reports the image missing and `project.assets`
  stays empty. Kills the "validate upload and body edit as one candidate" idea
  (§16.6).

No test-suite or ruff run: the change is one markdown file, no `.py` touched.

## Decisions needed from Jared

§15's ten questions. The two that change the shape of the feature: whether
images ever enter the revision token (§15.1), and whether `refdes build` should
error when a sealed entry's image bytes change (§15.6).
