# BUG 1 — the editor's create path ignored the destination file's `defaults.prefix`

Task: fix the confirmed bug in `in-prog-logs/user-sim-release-gate-run1.md`
("BUG 1"), plus decide the `status: draft` question the same report raises.
Status: **finished**, both parts, with the second one in scope deliberately
(it is the same bug, not a second one).

## What was wrong

`POST /api/items/create` minted ids from the *type's* bare prefix and never
looked at the file it was about to write into.

Reproduced first, before touching anything, at `.scratch/bug1-repro/`
(kept, per `AGENTS.md`):

```python
from refdes.serve.edit import CreateRequest, create_item
create_item(".", CreateRequest(who="t", type="requirement",
                              fields={"title": "Third, via the editor."}))
```

on the report's file (`defaults: {type: requirement, prefix: REQ-SYS, ...}`,
two items already `REQ-SYS-001/002` after `refdes id`) gave:

```
Created(item_id='REQ-001', ...)
```

and `refdes check` then said, as a **warning** only, so the build stayed
green and exited 0:

```
WARNING items/reqs.yaml:13 [REQ-001] — id 'REQ-001' does not match this
  item's prefix 'REQ-SYS' (from defaults:)
```

The id was in `.refdes/ids.yaml` (burned under `REQ: 1`) by then. Exactly
the report.

## The fix

### 1. `ids.plan_new_id` takes the destination's prefix (`src/refdes/ids.py`)

New keyword `prefix_hint: str = ""`, used as
`prefix = prefix_hint or prefix_for_type(project, type_name)`. That is
literally `prefix_for`'s rule (`ids.py:203`: `item.prefix_hint` first, type
prefix otherwise) applied to an item that does not exist yet — the caller
supplies the same override the loader would have parsed onto it.

I chose this over "compute the prefix in `edit.py` and pass a finished
string" because the *rule* stays in one place: `prefix_for`/`format_id`/
`plan_new_id` all still agree on what a prefix is, and the editor gains no
second opinion to drift. The parameter is also load-bearing in two places
inside `plan_new_id`, not one: the explicit-override prefix check now
judges against the effective prefix too (a `REQ-050` override into a
`REQ-SYS` file is refused, and the refusal says the prefix came from
`defaults:`).

`allocate()` needed no change: it plans an `Item` the loader already parsed,
so it already had `item.prefix_hint`.

### 2. `edit.py` resolves the destination's own `defaults:` (`_resolve_destination`)

`_resolve_destination` now returns `dest["defaults"]` for both existing-file
shapes, and `_create_locked` / `preview_creation` hand `defaults.prefix` to
`plan_new_id`. Structurally:

- **append-yaml** — `data.get("defaults")` was *already being read* in this
  function for `dest["type"]` (`file_type`). One line, nothing new parsed.
- **append-md** — this was the part the task asked me to work out, and the
  answer is not "the markdown case has no file-level override". A
  multi-item markdown file declares the same file-wide `defaults:`, in its
  **first front-matter block** (`parse.py`, `parse_markdown_file`: "If the
  first block's only key is `defaults:`, it is not an item -- its mapping is
  merged under every item that follows, the same way `defaults:` works in a
  list file"). So the same override applies, and the item appended there
  inherits it like any other. Verified: an md file whose first block says
  `prefix: REQ-SYS` now yields `REQ-SYS-003` from the create path.
- **new-md** — no file exists, so there is no `defaults:` block to inherit.
  The type's bare prefix is not a fallback here, it is the *only* answer
  available, and it is what `refdes id` gives an item in a file with no
  defaults. `dest` for `new-md` carries no `defaults` key at all, which
  keeps the shape honest rather than pretending to an empty block.

To read the markdown block without re-implementing "which block is the
file-wide one", I factored the existing 5 lines of `parse_markdown_file`
into `parse.front_matter_defaults_block(blocks)` (`src/refdes/parse.py`) and
had `parse_markdown_file` call it. So the editor and the loader cannot
disagree about which block is the file's defaults — same splitter
(`md_front_matter_blocks`), same "only key is `defaults`" test (`_only_key`),
same stripped mapping. Returns `None` for "no defaults block", `{}` for an
empty one, because `parse_markdown_file` needs to tell "block zero was
consumed" from "block zero was an item" and truthiness cannot.

Note: reading the destination file moved earlier, out of the YAML branch
into the shared "the file exists" path, so both append shapes read it once.
The refusal texts (`could not read {rel}`, `{rel} does not parse`) are
unchanged, just raised a few lines earlier for `.md`.

### 3. The `status: draft` question — same bug, fixed too

**It is the same bug, not a different one**, so I fixed it rather than
noting it. `status: draft` was not the editor inventing a value: it is
`scaffold.initial_field_values` correctly applying the *type's* declared
`default: draft` — the field-set resolution `refdes new` shares, kept
intact. What was wrong is that the editor applied it as an **explicit item
line** into a file whose `defaults:` said something else, so each created
item *overrode* the file. Same root cause one level down: the create path
resolving values from the type while ignoring the destination.

Fix: `_item_lines` takes the destination's field names as `inherited` and
skips a field whose value is only the type's fallback (a value the author
supplied in the form is always written — overriding the file is what
supplying one means). A created item in a `defaults: {status: active}` file
now carries no `status:` line and resolves to `active`.

What I deliberately did *not* touch: `board:`/`workspace:`. They have no
type-level `default:`, and the editor writes them only when the form
supplied one, so there is no fallback-to-contradict case there — the rule is
complete without them.

## Tests

`tests/test_serve_create.py` (new section "the destination file's own
defaults", plus a `prefixed_root` fixture and a `STATUS_SCHEMA`):

- `test_create_uses_the_destination_files_prefix_not_the_bare_type_prefix`
  — the report's repro. Asserts `REQ-SYS-003`, that no bare `REQ-` id is in
  the file, and that `REQ-001` is **not burned** in the ledger (the report's
  point that repairing it doesn't undo the burn).
- `test_the_created_id_is_the_one_refdes_id_would_have_assigned` — the
  stated guarantee as an equality rather than a literal: two identical
  projects, one filled by `ids.allocate()`, one by `create_item`, same id.
  Written as an equality on purpose so it keeps holding if the numbering
  ever moves.
- `test_create_in_a_markdown_file_honours_its_first_block_prefix` — the
  append-md case.
- `test_create_in_a_brand_new_file_numbers_from_the_type` — the new-md case.
- `test_preview_shows_the_destination_files_prefix_too` — the preview half
  (`GET /api/create/preview` showed `REQ-004` and saving wrote
  `REQ-SYS-003`, so the form's central promise was false for prefixed
  files).
- `test_explicit_id_override_is_judged_against_the_destination_files_prefix`.
- `test_a_field_the_destination_defaults_supply_is_not_written_onto_the_item`
  — the `status` half, including that an author-supplied `status` still is
  written.

`tests/test_ids.py`: `plan_new_id(prefix_hint=...)` unit tests (separate high
waters per series; empty hint is the bare prefix, not `""`; the explicit
override is judged against the hinted prefix).

`tests/test_parse.py`: `front_matter_defaults_block` — first block only,
only when it is a `defaults` block, `None` with no front matter, `{}` for an
empty one, and `None` for a non-first `defaults:` block (which the loader
treats as an error, never a second application point).

## Verification

- `pytest` — **2635 passed, 2 skipped** (was 2625 passed before; +10 new
  tests). Run against a venv installed editable from *this* worktree
  (`/tmp/opencode/rd-venv`), not the one that happened to be on the box —
  the pre-existing `/tmp/verify-pr63-venv` has an editable install pointing
  at a different checkout and silently tests that tree instead. Worth
  knowing before trusting a green run here.
- `ruff check` on the six files I touched, `--select E,F,I,W,B,SIM,UP,C4,RET`:
  14 findings, **all 14 pre-existing** — verified by running the same check
  over `git show HEAD:<file>` for each. My changes added zero.

## Docs

- `docs/ids.md` § Prefixes: the 1-2-3 precedence list was silent on who
  honours it. Added a paragraph saying whatever mints an id follows it —
  `refdes id` and the editor's New Item form alike — and that a brand-new
  file has no `defaults:` to inherit. (Checked `docs/authoring.md:30`/`:146`
  and `docs/design/browser-editor.md` too: both attribute `prefix:` handling
  to "the ID allocator" generically and stay correct, and the design doc's
  "the ID shown before saving is the ID the item gets"
  (`browser-editor.md:1186`) is now actually true for a prefixed file
  rather than aspirational.)

## Files changed

| file | what |
| --- | --- |
| `src/refdes/ids.py` | `plan_new_id(prefix_hint=...)`; override refusal names the `defaults:` |
| `src/refdes/parse.py` | `front_matter_defaults_block()`, factored out of `parse_markdown_file` |
| `src/refdes/serve/edit.py` | `dest["defaults"]`; prefix threaded to create **and** preview; `inherited` fields |
| `docs/ids.md` | one paragraph in § Prefixes |
| `changelog.d/editor-create-destination-defaults.fixed.md` | two bullets |
| `tests/test_serve_create.py`, `tests/test_ids.py`, `tests/test_parse.py` | 10 tests |

## Left alone, deliberately

- **BUG 2** (re-minted key orphans composite links, misdiagnosed) and
  **BUG 3** (`--reseal` unwrites history) from the same report. Different
  subsystems, different fixes; this branch is BUG 1 only.
- No `revise`/repair path for ids already burned in the wrong series by the
  old editor. A project that hit this has `REQ-001` burned and possibly on
  disk. The report says repair means a hand-edit or a `revise` mapping; that
  is a migration question, not a bug fix, and inventing one here would be
  scope creep on a change that is already two fixes.
