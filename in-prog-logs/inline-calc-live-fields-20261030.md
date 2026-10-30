# Inline-calc live fields (slice C / G1) — 2026-10-30

Task: make the browser editor's live-calc panel compute spans from the
unsaved draft's `fields` bag — spans of the edited item that name one of
its own fields (`ITEM.$field`) evaluate against the drafted value;
cross-item `$` refs keep reading saved. Design:
`in-prog-logs/inline-calc-live-editor-design-20261020.md` §3.2–3.4, §4 G1,
§6.4–6. Base: main at `6b89e38` (PR #388), branch
`feat/inline-calc-live-fields`.

## What landed

- `src/refdes/build.py` — `_make_calc_resolver` takes an optional
  `fields_overlay=(item, fields)`; the field read overlays the draft bag on
  the saved fields **only when the resolved target is the edited item**
  (identity through `_key_index`, so composite-key refs to it are covered
  too). `preview_inline_spans` consumes `fields` (truthy bag => overlay)
  and now installs `CALC_WARNINGS_KEY` (collected, dropped — the 3-state
  panel never surfaces warnings) and `FIELD_FIELDS_KEY`, so the
  hyphenated-field error names the declared fields exactly like check.
- `src/refdes/serve/api.py` — `/calc` `fields` bag values must be scalars:
  collections and `null` are 400 ("fields takes scalar values: collections
  and null are not editable"), mirroring the save route's set_field rule.
- `src/refdes/serve/static/live-calc.js` — controller gains
  `fieldsChanged()` (same 400 ms debounce as body keystrokes).
- `src/refdes/serve/static/editor.js` — `writeDraft` calls
  `liveCalc.fieldsChanged()` after every field input. Field typing with
  the textarea unfocused is display-only (§3.5); focusing the body applies
  the fill under the normal caret/auto-fill rules.

## Tests (red-first, all proven red before implementing)

- `tests/test_calc_preview.py` — own-field draft bag read, blank/whitespace
  cleared field, non-quantity field message, unit-assertion and
  hyphenated-field messages with declared-field listing, cross-item refs
  read saved, `REQ-001` collision computes the calc value, undeclared bag
  keys ignored, bag does not mutate the project, and the differential
  matrix `test_preview_with_bag_equals_check_after_saving_the_same_fields`
  (11 inputs: preview row per label == `refdes check` diagnostic /
  `calc_values` after saving the identical fields).
- `tests/test_serve_calc_preview.py` — bag is validated, carried, and
  consumed; non-scalar values 400. The old inertness test
  (`test_a_fields_bag_is_validated_carried_and_ignored`) was intentionally
  flipped to `..._and_carried` — inertness was the slice-B contract; this
  slice is exactly the change of that contract.
- `tests/test_serve_live_calc_e2e.py` —
  `test_editing_a_field_moves_the_panel_without_saving`: /calc with the bag
  flips the row error→stale byte-identically to what the saved project
  reports, and `set_field`+`set_body` lands the same build.
- `tests/test_editor_live_calc.py` — node harness scenario `fieldFire`:
  field keystroke debounces (399/401 ms), sends
  `{fields:{status:"open"}, text:T1}`, one panel render, textarea untouched.
  Proven red by unwiring `editor.js` (harness exits nonzero), restored.

## Verification

- New tests red (10 failures) → green (42) after implementation.
- Static suites + node harness: 55 passed.
- Full suite: 5539 passed, 2 skipped.
- `ruff check` clean on every touched file; api.py keeps exactly the six
  pre-existing findings (lines 300/318/503/606/608/631).
- Real browsers (this tree's src served on 8761 — 8754 was taken by a
  concurrent session's server, left alone): Chromium 16/16 (new `item16`)
  and Firefox 17/17 (new `ff16`): open the field-span item (error row),
  type `3 V` in the title FIELD input → `ok`, type `4.5 V` → `stale`
  (computes 4.5 V), status stays `unsaved`, Fill lands `= 4.5 V`. Body
  typing/regression cases all pass in both browsers.

## Notes / not verified

- Panel collision rows show `ok` computing the calc value; the collision
  WARNING is not surfaced by the 3-state panel (unchanged from slice B) —
  the differential test pins value agreement, not warning text.
- The task named `tests/test_serve_live_calc_route.py`; no such file
  existed, route tests went into `tests/test_serve_calc_preview.py`.
- Field values that YAML-list items store as non-string scalars (ints)
  reach the overlay raw, same as the save route — no extra coercion.
