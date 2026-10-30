# Live inline-calc docs (slice C) — 2026-10-30

Task: document the live inline-calc editor feature (slices A/B, PRs #386
and #388, design `inline-calc-live-editor-design-20261020.md`) per that
design's §4 slice C. Docs-only: no code touched.

## What landed

- `docs/design/inline-calc-later.md`: `Live editor updates` status line →
  implemented, recording the owner decisions from design §6 (400 ms
  debounce with blur/focus flush; panel under the textarea beside the
  pickers; stale-only auto-fill, default ON, `localStorage` key
  `refdes.live-calc.autofill`; idempotent Fill; Case A `insertText` undo
  browser-tested on Chromium and Firefox, Case B splice fallback with
  panel warning and session stand-down; preview pane stays the
  as-published view, owner D2; `check`/`build` remain the verdict), and
  a preamble clause so the "None is implemented" claim stays true.
- `docs/design/browser-editor.md`: one pointer sentence in "Editing and
  previewing bodies" naming `POST /api/item/<ref>/calc`, stating the
  calc half of the unsaved-preview paragraph landed and the
  rendered-fragment half did not (route table in `api.handle` re-read:
  no unsaved-preview route exists).
- `docs/math.md`: author paragraph in "Inline calc" — live recalc while
  typing, ok/stale/error rows with computed values, Fill on stale rows,
  autofill checkbox default ON per browser, one-Ctrl+Z undo, Case B
  caveat, `check`/`build` remain the verdict. Field-reference form
  (`ITEM.$field`) was already documented in the same page; not
  duplicated.
- `changelog.d/live-inline-calc-editor.added.md`: the feature fragment.
  #388's commit message says "the fragment lands with slice C", so this
  covers the route + panel as one user-visible change; #387's field refs
  already have `calc-field-refs.added.md`.

## Verified (claim → command → observed)

- Stale/missing vocabulary → `refdes check` on a scratch project (worktree
  src via PYTHONPATH) → `ERROR ... inline calc Vhalf := 3 V *: stored
  result missing; write '= <quantity>'` and `WARNING ... inline calc Vbad:
  stored result says 5 V, now computes 4 V`; `1 items, 1 errors, 1
  warnings`.
- Route contract → `refdes serve --port 8753` from the worktree,
  `POST /api/item/DEC-001/calc` with a draft body → 200 JSON: `Vbad`
  stale (computed `4 V`, checker message), `Vout` ok (`4.436 V`),
  `Vhalf := 3 V *` error (no result range, message above). Missing
  `text`/non-object `fields` → 400; unknown ref → 404.
- Panel rows, Fill-on-stale-only, autofill default (pref null → fills
  applied), autofill off across reload + item switch with rows still
  rendered, ok-window literal byte-stable (`= 4.4 V` kept), one-Ctrl+Z
  undo of a Fill, Case B (`insertText` forced false) splices with panel
  notes `native undo may not cover these fills` + session stand-down,
  blur-evaluates/refocus-applies → Playwright, Chromium (`drive.mjs`)
  and Firefox (`ff.mjs`), recipe from the slice B scratch dir with port
  switched to 8753; all cases green, evidence JSON in `.scratch/pptr/`.
- Panel under the textarea → `item.js` mount point re-read at HEAD (the
  live-calc panel appends after the body control, beside the pickers).

Not reproduced: the Case B *trigger* in Firefox (its `insertText`
succeeds, so Case A always runs there); what was verified in Firefox is
that the session stand-down flag is honored. Docs text says "where a
browser's native undo cannot carry the edit" — no per-browser claim.

Server stopped after verification; port 8753 confirmed free.

## Status

Finished. `pytest tests/test_docs_anchors.py tests/test_docs_examples.py
tests/test_standard_docs_complete.py tests/test_site_assets_confinement.py`
→ 31 passed.
