# serve: browser-editor refdes buttons (toolbar slice 2)

Task: implement slice 2 of `editor-format-toolbar-design-20261029.md` on the
rebased branch (branch is exactly origin/main `09c15cc` after
`git rebase --onto origin/main c35ab7b`; slice 1 shipped in PR #393).

## What landed

- `pickers.js` (new): shared candidate machinery — `PICKER_LIMIT` 5000,
  `displayHalf`/`displayId`/`rowLabel`/`matchesFilter`/`candidatesFor(types)`.
  `links.js` refactored onto it (behavior unchanged); `formatbar.js`'s
  reference picker imports it too. Wiring pinned in
  `test_serve_static.py` (both modules must `from './pickers.js'`).
- `formatbar.js`: skeleton exports (single source of truth, parsed by
  Python tests), `REFDES_OPS` (span/calc-fence/figure/value via the shared
  `applyEdit` mutator), `createReferencePicker` (filter input, rows,
  cap/failure notices, arrows/Enter/Escape, focus restore), refdes button
  group (reference/figure/calc/span/value/image/source) in
  `createFormatBar({ isSaving, focusPanel })`, aria-haspopup/expanded,
  detach() closes the popover.
- `editor.js`: image/source pickers hoisted above the bar; `focusPanel`
  focuses the first control in the panel, falling back to focusing the
  panel container (panels fetch lazily — no control exists at click time).
- `style.css`: `.fmt-refdes` group, `.fmt-picker*` popover.

## Red-first evidence

`tests/test_editor_skeletons.py` first failed with the right red
("formatbar.js must export the skeleton string SPAN_SKELETON"), then 9
passed. Measured (fixture probe, `.scratch/skel2/`): span → `inline calc
name := 0 | V: stored result missing; write '= <quantity>'`; fence →
`calc 'name': unknown name 'expr'`; figure/value skeletons warn only
(never error), so the skeleton tests filter to level==error. The §H-4 save
gate measured live: 422 `kind:"invalid"` + snapshot_tree unchanged;
completing the span saves 200 `applied`.

## Bugs the harnesses caught (pre-browser)

- Fence skeleton selected `` ```ca `` not `name` (off-by-the-fence-opener
  in `applyCalcFence`) — fixed to `nameAt = textStart + 7`.
- `onOpenChange:` as an option key tripped the CSP inline-handler text
  rule — renamed to `setExpanded`.
- preventDefault text-count pins needed scoping per handler (mousedown
  guard now appears 3×: core buttons, refdes buttons, picker rows).

## Test status

Full touched battery green: skeletons, format_bar, refdes_buttons,
serve_static, link_undo, live_calc, serve_edit_http, serve_calc_preview —
128 passed. Node harness `test_editor_refdes_buttons.py` covers: insert
semantics (caret & selection, astral-safe), fences balanced after the
enclosing fence, isSaving gate, read-only no-bar, picker open/filter/pick/
caret-pick/Escape/keyboard/cap-notice/failure-banner/display-id (no `@key`
leak), Image/Source focus, `PICKER_LIMIT === 5000`.

## Real-browser checklist (both PASS, port 8753, headless)

`.scratch/pptr/drive2.mjs` (Chromium) and `ff2.mjs` (Firefox), 11 checks
each: 7 labelled refdes buttons; span name-selected; fence appended at
end with name selected; figure/value caret inside brackets; picker opens
(filter focused, 3 rows), 'rail' filter → 2 title matches, picking
DEC-003 inserts `[[DEC-003]]` and restores focus; Escape closes;
skeleton save blocked with the stored-result message and text kept;
completed span saves (status 'saved'); Image focuses `.images-edit`;
one Ctrl+Z removes the skeleton.

Driver lessons (not product bugs): the fixture item titles contain 'rail'
so a 1-row expectation was wrong; the live-calc autofill rewrites the
stale span mid-test (baseline must be taken after it settles, and the
save-completion check must read `.edit-status` because the success note
is cleared by the onSaved refresh); the images panel root is
`.images-edit`; serve `/api` accepts the header token once the launch
URL visit has set the cookie.

## Notes

- Server untouched; no `[[cite:id]]`, Navi, or font-setting changes —
  out of slice.
- `ruff check` clean on the touched py files (pre-existing repo-wide
  findings untouched).
- Status: finished.
