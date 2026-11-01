# fix-navis-flow-seq-mint (run-15 F15-1)

## Cause (corrected after the PR #408 review round)

Nothing to do with Navi markers. A YAML list file whose WHOLE list is a
flow sequence -- `items: [{id: ..., ...}]`, no marker at all -- cannot
receive the surrogate `key:` line the load-time mint writes: the item's
`source_line` is the `items: [{...}]` line, which is not a `- ` list
entry, so `ids.insert_into_list` refuses (returns None). `keys.plan_missing`
reported the bare `could not write key ... back into the source` and
`missing_assignments` minted a fresh key every run (new key each run,
exit 1, bytes untouched). The markdown branch just above already handled
the same class deliberately with an actionable flow-style-front-matter
message.

## Decision (coordinator, made)

Keep it an ERROR (an item with no key may not persist); only make the
YAML message the same class as the markdown one. No new warning code, no
exit-code change, no keyless-with-warning. Navi plan-time refusal work
dropped -- the matrix confirms the Navi mint path never writes bytes and
never errors on its own for these files (marker in a flow-seq body:
listed keyless, bytes untouched, the single ERROR is the key path).

## What changed

- `src/refdes/keys.py`: shared wording helper `_flow_style_key_hint`;
  markdown message text kept byte-identical (guard test added); YAML
  list branch now emits
  `could not write key K back into the source: key cannot be added to
  this flow-style list; rewrite it in block style (one `- id:` entry
  per line)`.
- `tests/test_keys_flow_style_list.py`: red-first repro (exactly the
  report's file), churn guard (3 runs), shape matrix. Refused shapes
  (exit 1, message, bytes untouched): flow sequence, several entries,
  nested flow, multi-line flow entry, CRLF and BOM flow sequence.
  Minted shapes (exit 0): block list, flow map inside a block list
  (key minted inside braces -- Test B regression), quoted body in a
  flow map, anchor/alias (key lands on the anchored entry), merge key,
  BOM block list. Multi-document file: pre-existing parse error
  ("expected a single document"), exit 1, bytes untouched. `items: []`:
  clean exit 0.
- `changelog.d/flow-list-key-mint-message.fixed.md`.
- No docs change: no page named this limitation (the flow passages in
  docs/markdown.md and docs/cli-reference.md describe the *Navi* mint
  refusal, which is accurate as written).

## Verification

- Red first: 9 tests fail on the bare message, then 17/17 green after
  the message change; markdown front-matter message frozen by a green
  guard test.
- CLI repro before: fresh key each run + bare message; after: actionable
  message, bytes identical across runs.
- Differential: no-marker project (block-list file) builds byte-identical
  under origin/main code vs HEAD code (run twice).

Status: finished.
