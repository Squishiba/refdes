# live inline-calc, slice A: read-only preview route

Design: docs/design/inline-calc-live-editor-design.md (PR #350), Slice A
tasks B1/B2/B3. Plan confirmed with the user before starting; the one
contract change we agreed: the response's `revision` is THE ITEM'S FILE
REVISION (same string as `GET /api/item/<ref>` `edit.file_revision`), not
the project-wide `/api/revision` revision.

## Done

- B2 (`src/refdes/inline_calc.py`): `InlineSpan.result_col` — content-relative
  column of the `=` separator, set in `parse_span`'s readings branch. Only
  consumer is B1's result-range math.
- B1 (`src/refdes/build.py`): `PREVIEW_SPAN_LIMIT = 200` +
  `preview_inline_spans(project, item, body_text, *, fields=None)` +
  `_preview_inline_span`, inserted after `_run_item_calcs`. Fences on the
  draft are evaluated into a local env (so dup-name fires across fence/span
  spellings) with `start_line = offset + 1`; fence diagnostics are not
  reported (the save-time 422 owns fences, §3.3). Spans are capped at 200 in
  source order. `fields` is accepted-and-unused (§3.4) — pinned by a test.
  Messages are the R12 diagnostic vocabulary verbatim, prefixed
  `inline calc {label}: `; `computed` is `format_value(value, sigfigs)`.
- B3 (`src/refdes/serve/api.py`): `POST /api/item/<ref>/calc` registered in
  `handle()` beside the `/edit` branch. Guard order: 400 (non-object body /
  text required / fields must be an object), 404 (`_find_item`), 403 (reuses
  `edit_state`, so sealed/imported bodies answer with the same reason the
  write path gives). 200 = `{revision: <item file revision>, spans: [...]}`,
  plus `truncated: true` only when the cap bit. Unknown request keys are
  ignored (forward-compat posture, §3.3).
- Tests: `tests/test_calc_preview.py` (12 unit) +
  `tests/test_serve_calc_preview.py` (13 HTTP, live `EditorApp` +
  `serve_support.Client` posture of `test_serve_edit_http.py`). The fidelity
  pins: message parity vs the real build (same text written to disk, and via
  `loader.load_readonly(overlay=...)`), and `snapshot_tree` byte-identity
  across every route guard. Full suite green: 5064 passed, 2 skipped.

## Findings on the way

- `tests/conftest.py:13` inserts `../src` at `sys.path[0]` — so a
  `PYTHONPATH=`-based mutation test silently passes against the worktree's
  own src. The mutation runs therefore ran pytest inside full throwaway
  copies of `src/` + `tests/` under `.scratch/` (mut-a, mut-b).
- M1 (oracle mutation — drop the `inline calc {label}: ` prefix): fails
  `test_ok_stale_and_missing_result_rows`,
  `test_status_and_messages_are_what_the_real_build_reports`,
  `test_source_refusal_message_is_the_builds`,
  `test_the_response_shape_is_the_contract`,
  `test_the_route_and_a_full_overlay_build_agree_on_every_status` — the
  oracle diff is exactly the prefix, e.g.
  `'stored result says 5 V, now computes 4 V' != 'inline calc Vbad: stored
  result says 5 V, now computes 4 V'`.
- M2 (inertness mutation — write `computed` into `item.calc_values`): fails
  `test_preview_mutates_nothing` — the snapshot diff shows
  `('Vbad','4 V'),('Vout','4.436 V'),('Vref','5.1 V')` appearing on
  DEC-001 where the pre-state was empty.
- Differential: `refdes build` of a calc-heavy fixture (fence + inline span
  + cross-item ref + source citation) is byte-identical between
  `git archive origin/main`'s tree and this worktree (run-old4/run-new4
  under .scratch/, `diff -rq` clean). Surrogate-key minting is
  session-scoped, so the comparison mints once in the shared fixture first
  and diffs two rebuilds — a fresh-copy-per-side comparison diffs keys, not
  behavior.
- Fixture gotcha: `types:` in `refdes-project.yaml` is a hard error
  (hardware@3, per AGENTS.md); the scratch fixture needed
  `refdes-schema.yaml`.

## Not done (deliberate)

- No changelog fragment: this slice ships behind no behavior change for the
  CLI; the fragment lands with slice C (panel UI) per the design's release
  note.
- Field-reference mode (the `fields` bag being *read*), the fill/apply
  affordance, the §3.6 revision-guard wiring on the client: slices B/C.
