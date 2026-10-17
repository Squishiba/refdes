# R10-X1: a `---` inside a fenced code block does not split the item

Parser change to `md_front_matter_blocks` (src/refdes/parse.py), the single
splitter shared by the item loader, patcher, revise and serve/edit — the fix
lands there, one call site, all consumers stay consistent by construction.

## Repro (verified, run 10's shape)

Fresh `refdes init` project under `.scratch/r10x1/`, a log item whose body
carries a ` ```yaml ` fence containing `---\nid: LOG-PWR-001\nchecks: ...\n---`.
On main: `refdes ls` listed the phantom and `refdes check` reported the split
(the fenced text became a real front-matter block — here "item has no
'type'"; with `type:` inside, run 10 saw `duplicate id`). After the fix: one
item, fenced text is body prose, exit clean of split artifacts.

## Splitter mechanics

`md_front_matter_blocks` collected every `^---[ \t]*$` line (FENCE_RE) and
paired them; a pair whose next line looks like a YAML key and whose content
parses as a mapping became an item. Code fences were invisible to it.

Fix: new `_code_fenced_lines(lines, start)` returns line indices strictly
inside a *closed* fenced code block; fences opened inside the first
front-matter region are ignored (that region is YAML, scanned from the first
block's close). `fence_idx` is filtered by that set before pairing. Rules:
opener = <=3-space indent + 3+ of one of ``` / ~~~ (backtick fence info
string may not contain a backtick); closer = same char, run >= opener,
nothing after; fences don't nest. Unclosed opener protects nothing — today's
behavior for the rest of the file (least-surprising fallback, tested).

## Blast radius (measured before the change, scanner in .scratch/scan_fences.py)

- `items/**/*.md`: zero `---` lines inside closed fences.
- `tests/**/*.md`, `items/**/*.yaml`: zero.
- `tests/*.py` inline markdown strings: fenced bodies are `calc` blocks only,
  none containing `---`.
- `docs/*.md`: 53 fenced `---` lines, but docs pages render via
  `FRONTMATTER_RE` (pages.py:64, single-doc), not the splitter — unaffected.
- `docs/design/candidate-parts.md` §7.3 fences `---` lines are the *extracted
  example's* front-matter delimiters (tests/test_candidate_parts_doc.py
  strips the fence first), not inside a fence in the parsed file — unaffected,
  full suite confirms.

No existing file changes meaning; nothing found that required stopping.

## Tests

tests/test_fenced_frontmatter_split.py, red on main (8 failed), green after:
backtick + tilde fences, longer closer with inner shorter fence, 3-space
indented opener, 4-space indent is not an opener (still splits),
`---` outside fences still splits (pin), unclosed opener (pin),
info-string line inside a fence does not close it, backtick-in-info-string
line is not an opener, e2e R10-X1 repro, two-sections-only-later-fenced,
byte-for-byte round-trip after load, list-file `body: |` unaffected.

## Adjacent surfaces checked, not touched

- `_item_spans` (revise.py, links.py) and `ids._front_matter_end` scan raw
  FENCE_RE for each item's *front-matter close*, which always precedes any
  body fence — their spans are unchanged by this fix.
- #322's inert-fence warning (build.py `declares_inert_keys`): verified still
  firing for its shape. It stays silent for the delimiters-included paste
  shape (`safe_load` raises on the multi-document stream) — pre-existing
  R10-F1-family gap, out of scope, recorded in the PR body.
- docs/checks.md's inert-fence paragraph: the fix makes its "renders as
  literal text ... silently never runs" claim true for the
  delimiters-included shape, which previously split and went live. No
  statement made false.

## Review round (PR #331, head b2785d2) — silent-swallow regression

The reviewer's probe (.scratch-style, their x1probe): item A's body carries
an UNCLOSED ` ```python ` fence; item B follows with real front matter and a
closed ` ```text ` fence in its own body. A's opener pairs with B's fence's
*closer* as its own close, so my protection swallowed B's whole item — main
loads A+B, b2785d2 loaded only A, with no diagnostic. A phantom (the
original bug) is loud; a vanished item is silent. Invariant adopted: no item
that loads today may silently stop loading.

Decision: a fix cannot tell a pasted example from a swallowed item (they are
structurally identical), so suppression is made LOUD. `md_front_matter_blocks`
gains a fourth return, `fence_warnings`: every fenced `---` with a key-shaped
line after it (the pairing loop's opener range) reports
`FENCED_FRONT_MATTER_WARNING` at its line; `parse_markdown_file` reports it
via `project.warn` (lowest severity, file:line). A deliberate paste costs
one warning — accepted, stated in docs/authoring.md and the changelog
fragment. All 5 call sites unpack the 4-tuple (patcher/revise x2/serve-edit
ignore warnings; the loader reports).

New tests (red on b2785d2, 14 failing after the contract change): exact
repro (1 block, 1 warning at B's `---`), B-with-no-fence (splits silently,
unchanged), unclosed-in-A + two later items (B warned, C loads), e2e through
`load_items` (warning on the normal channel, A loads, B suppressed), and the
paste case asserts its one warning; the split-pins assert zero warnings.
Scan re-run: items/ still 0 fenced `---` → repo's own project loads with 0
new warnings (`refdes check`: 0 "fenced code block" lines). Full suite
4038 passed, 2 skipped; ruff E9,F clean on all touched files.

## Status

Finished. Full suite: 4038 passed, 2 skipped. `ruff check <touched> --select
E9,F` clean. PR opened, not merged.
