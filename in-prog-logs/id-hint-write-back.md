# `refdes id` write-back: replace the hint line, don't shadow it

Task: fix the verified bug where `refdes id` inserts a *second* `id:` line
above a quoted bare-number hint (`id: '007'`), leaving the hint in place.

## What was actually wrong

`ids.insert_into_markdown` / `ids.insert_into_list` decide whether to replace
an existing `id:` line or insert a new one by looking at **only the line the
item starts on** (`item.source_line`). For markdown that is the first key of
the front-matter block; for a yaml list entry it is the `- ` line.

A hand-written item leads with `type:`/`title:`, so a hint written after them
was never on the line being examined. The regex missed, the code fell through
to "insert", and the file ended up with both `id: REQ-007` and `id: '007'`.
YAML resolves a repeated key to the *last* one, so the hint won and:

- the item reloaded as `007` (a pending item with a numeric hint),
- `refdes check` reported `id: 007 has no prefix yet` (parse.py:877),
- a second `refdes id` refused it as a burned-number collision.

Reproduced end to end on `main` (`.scratch/repro`, `.scratch/repro2`,
`.scratch/repro3` in the worktree) before touching anything.

The bare-key form (`id:` with no value, from `refdes new`'s scaffold) had the
**same** defect for the same reason and is fixed by the same change: the item
reloaded as having no id at all (`item has no id`).

## The fix

- New `_find_key_line` searches a bounded range for a line that is exactly
  `<entry key column>key: <value>` and nothing else.
- Bounded by `_front_matter_end` (next `---`, by the parser's own fence rule,
  so the search cannot reach the next item's block) for markdown, and by the
  first dedented line for a list entry.
- The **key column** is the safety property that makes the widened search
  safe. A sibling key, a nested mapping/sequence, and a block scalar's body
  are all at other columns -- and YAML requires a block scalar's body to be
  indented *past* its key, so no such line can ever sit at the entry's key
  column. `_entry_key_column` exists because `LIST_ENTRY_RE` only yields the
  entry's *minimum* column: `- type: requirement` followed by `    id: '007'`
  is valid YAML and the ordinary shape.
- Matches quoted (`'007'`, `"007"`) and unquoted `007` text, and a bare key
  when `old_value` is None.

## Second bug found by the required CRLF test

`ids.allocate` read the file in default text mode, which had already
translated every CRLF to LF *before* `newline = "\r\n" if "\r\n" in text`
ran -- so that check could never be true, and `refdes id` silently converted
a whole CRLF file to LF for a one-line edit. Fixed with `newline=""` on the
read, matching every other writer in the codebase (`keys.py:669`,
`links.py`, `revise.py`).

**Left alone, out of scope:** `former_ids.confirm`
(`src/refdes/former_ids.py:182-184`) has the identical read/detect pair and
the identical CRLF-to-LF bug. One word to fix, but it is a different command
and this task was scoped to the `refdes id` write-back.

## Tests

16 new tests in `tests/test_ids.py`, all end-to-end through
`cli_mod.main(["-c", ..., "id"])` where it matters:

- markdown hint under other keys, single- and double-quoted
- yaml list hint under other keys, single- and double-quoted
- CRLF markdown file: the hint's line replaced, no lone LF anywhere else
- unquoted `id: 007` end to end: refused, file byte-identical, nothing burned
- each end-to-end case then asserts `refdes check` is clean **and** a second
  `refdes id` is a no-op (the two symptoms of the leftover hint)
- writer unit tests for the search boundaries: the next block/entry, a nested
  key, and a block scalar's body are all out of reach
- a list entry whose keys are aligned past the `- ` column

## Docs / changelog

- `docs/cli-reference.md`: the "Known issue (verified against `hardware@3`,
  not yet fixed)" blockquote under `refdes id` is gone, replaced by one
  sentence saying the hint line is replaced wherever it sits.
- `changelog.d/id-hint-write-back.fixed.md`, two bullets (hint write-back,
  CRLF).

## Gate

`python -m pytest -q -x` -> 2154 passed. `python -m ruff check --select E9,F
src tests` -> All checks passed.

## Finished

Yes.
