# named-calc-blocks Phase 2 (Fragments)

Worker: refdes-159. Spec: docs/design/named-calc-blocks.md §5.3, §7, §10,
§13 (Phase 2). Depends on Phase 1's `id="calc-<name>"` anchor (merged, #24).
Phases 3 (`{{calcblock}}`) and 5 (docs) deliberately not implemented.

## What landed

- `build.py`: `EXPLICIT_REF_RE`'s fragment group admits at most one colon, so
  `[[ID#calc:name]]` matches at all (it did not before — the whole reference
  failed to match and reached the page as literal text). New module constant
  `CALC_FRAGMENT_PREFIX`.
- `build._linkify`: `_linkify.field_anchor` is now a fragment dispatcher —
  `calc:<name>` goes to the new `calc_anchor`, anything else keeps the
  existing `#field`-against-the-target's-type path unchanged. `calc_anchor`
  resolves against the target's *fence lines*
  (`calc.extract_blocks_with_lines`), not its evaluated rows, so a named block
  that produced no rows is still a name the item has — the same source of
  truth Phase 1 puts the anchor on. A hit returns `#calc-<name>`; the existing
  `link()` tail renders it as `<a class="ref" href="{slug}.html#calc-losses">`
  with the label rules `#field` already uses, so `[[ID#calc:name|text]]` comes
  for free.
- The fig:/cite: fragment warnings are untouched and fire for `#calc:` exactly
  as they do for `#field`, which is what §5.3 asks for. Nothing was added
  there; the regex widening is the whole change.
- A fragment miss renders `<span class="ref ref-missing" title="unknown calc
  block">` with the reference's own text, so the sentence stays readable and
  the miss is visible. Warnings, never errors (§11.9): `refdes build` exits 0.

## Design calls logged (unspecified in §7)

1. **A target with no calc blocks at all.** §7 gives two shapes — "it names:
   ..." and "has calc blocks but none is named" — and neither is true of an
   item that computes nothing. It gets a third message at the same level,
   naming what would make the link work:
   `[[ID#calc:x]]: ID has no calc blocks -- a #calc: fragment names a ```calc
   block given id="...", and this item computes nothing.` Pinned by
   `test_calc_fragment_on_item_with_no_blocks_warns`, including the negative
   (`"it names:" not in msg`) so an empty name list can't come back.
2. **An unknown fragment namespace (`#blox:losses`).** Widening the fragment
   group to admit a colon makes this reference *match*, and §7 has nothing to
   say about it. Leaving it to fall through to the field path would warn "no
   field named 'blox:losses'", which is true but sends the author looking for
   a field. It gets its own warning naming the two fragment kinds that exist.
   This is the §3.4 call applied to the reference side: silently-ignored author
   intent is the failure. Pinned by `test_unknown_fragment_namespace_warns`.
3. **Name order in "(it names: ...)".** Fence order, not sorted — the order
   the item declares them, which is the order the page shows their tables in.
   §7's example (`losses, supply`) is reproduced by declaring them in that
   order in the fixture, so the message is asserted message-for-message.
4. **Attribution.** `file`/`line`/`item_id` of the *referring* item, identical
   to a `#field` miss on the same line — pinned by comparing the two
   diagnostics rather than by a hardcoded line number, because the line number
   is `_linkify`'s existing item-level one and pinning it here would freeze a
   number Phase 2 does not own.

## Tests

`tests/test_calc_block_refs.py` — 10 tests, every §10 Phase-2 row
(links-to-anchor incl. custom text, unknown-name warning, unnamed-block
warning, fig:/cite: warning), message-for-message where §7 specifies.
Sabotage notes inline. Verified by mutation, each time reverting:

- anchor spelled `#calc:name` instead of `#calc-<name>` → 3 failures
- a `#calc:` miss resolving to the page with no anchor and no warning → 4
- the miss promoted from `warn` to `error` → 2 (the exit-0 assertions)
- `#calc:` silently dropped on fig:/cite: + the unknown-namespace warning
  silenced → 2

## Verification

- `python -m pytest -q` — 2093 passed (10 new).
- `ruff check --select E9,F` on `src/refdes/build.py` and the new test file —
  clean.
- No fixture regenerated, no doc edited (§13 puts the docs in Phase 5), no
  raw-byte hash pinned.

Status: Phase 2 complete.
