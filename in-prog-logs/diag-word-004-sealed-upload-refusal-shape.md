# DIAG-WORD-004: sealed upload refusals expose one details shape

Branch: `fix/sealed-upload-refusal-shape-20261015`, base main `7e49a20`
(verified: `git merge-base --is-ancestor main HEAD` -> branch contains main
tip). Owner: Qwen (Sol lane, slot row 66 of `.scratch/PROGRESS.md`).

## Finding, verified PRESENT on current main

`src/refdes/serve/upload.py` builds three refusals with `kind="sealed"`, and
their `details` rows had three incompatible key sets (line numbers at base):

- `_sealed_target_refusal` (:499-505): row keys `{item, source_file, sealed}`;
- `_sealed_replace_refusal` (:540): rows from `_referencing_items` (:300-305)
  plus the `_mark_sealed` flag -- `{item, source_file, srcs, sealed}`;
- `_sealed_capture_refusal` (:575): rows built in `_capture_refusal`
  (:380-398) -- `{item, source_file, src, resolves_to, why, sealed}`.

All three arrive at the client as `refusal: "sealed"`
(`serve/api.py:1036` serializes `details` for every `Refused`), so a client
reading, say, `srcs` on a sealed row finds it missing on the target branch.

## Live proof (before/after)

`.scratch/diag-word-004/probe.py` runs a real `EditorApp` (start/stop,
`Client`) over real HTTP against three served project fixtures: sealed-target,
sealed-replace (pure and mixed sealed+unsealed referrers), sealed-capture,
plus controls (identical-bytes no-op -> 200, unsealed capture -> 422
`refusal=capture`, unsealed replace -> 409 conflict). It is run with
`PYTHONPATH` and `REFDES_SRC_PIN` pinned to this worktree's `src` and asserts
`refdes.__file__` matches before probing. Outputs:
`.scratch/diag-word-004/probe-before.txt` (three divergent key sets) and
`probe-after.txt` (every sealed row carries the core, capture adds its keys
on top, controls byte-identical in shape).

## Consumers (inspected before the change)

- `src/refdes/serve/static/images.js:226-237`: branches on
  `payload.refusal === 'sealed'` and renders `payload.message` only; never
  reads `details`.
- `docs/design/editor-image-upload.md` §10 named the refusals but documented
  no details shape (grep: no "details" in §10).
- Tests: `tests/test_serve_upload.py` reads `details` keys as subsets
  (`item`, `source_file` at :1205-1206; `sealed` flags at :1351-1352);
  no exact-key-set assertion existed, so additive keys break nothing.
  `tests/test_vscode_adapter_contract.py` only gates writes under `--no-write`
  on `/api/assets`.

## Chosen schema

Every `kind="sealed"` details row carries one stable core:
`item`, `source_file`, `srcs` (references naming the file in question --
empty for the target branch, whose reference can never reach disk), `sealed`,
`why` (that row's reason, prose). Branch keys sit on top, never instead: the
capture row keeps `src` and `resolves_to`. Nothing renamed or removed ->
existing readers keep working; new readers branch on nothing.

## Implementation (narrow, at refusal construction)

- `_sealed_target_refusal`: row gains `srcs: []` and `why` (the orphan rule).
- `_sealed_replace_refusal`: fills `why` on every disclosed row (sealed rows
  name the seal rule, unsealed rows name the disclosure), so the mixed
  disclosure is one shape. Safe to mutate: the refusal path returns before
  any `Uploaded`/`Conflict` is built from the same rows.
- `_capture_refusal`: row construction gains `srcs: [leaf]`; the sealed
  variant gets it via the shared rows, the plain capture refusal gains it as
  an additive key.
- Contract documented in `Refused`'s docstring (upload.py) and in
  `docs/design/editor-image-upload.md` §10.

## Tests

Four new route tests in `tests/test_serve_upload.py`, all red on base main
(proved by `git archive main` -> `.scratch/diag-word-004/base-main`, my test
file copied in, `4 failed`) and green here:
- `test_every_sealed_refusal_row_carries_the_same_core_keys` (all three
  branches over HTTP, core keys in every row, branch pins);
- `test_a_sealed_target_row_explains_the_orphan_it_refuses`;
- `test_a_sealed_replace_disclosure_explains_every_row` (mixed set);
- `test_a_plain_capture_row_keeps_its_resolution_and_gains_the_core_list`
  (control: the non-sealed §9.2 rows keep every old key, `srcs` added).

## Runs

- `python -m pytest tests/test_serve_upload.py` -> 108 passed, 1 skipped
  (skip pre-existing: hard-link test).
- `python -m pytest tests -k serve` -> 704 passed, 1 skipped.
- `tests/test_vscode_adapter_contract.py` -> 10 passed.
- Scoped ruff (`E501,RUF059` on the two touched files) identical to base:
  4 == 4 pre-existing, no new findings.

## Status

FINISHED. Committed on the branch, PR opened. No merge, no self-spawned
reviewer.
