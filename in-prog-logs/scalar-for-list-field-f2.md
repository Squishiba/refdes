# F2 — a scalar where a list belongs is now a build error

Task: fix the confirmed bug in `in-prog-logs/user-sim-release-gate-run1.md`
§2, finding **F2** — `tags: "power, analog"` (a quoted scalar) written for a
list-typed field was silently accepted, silently stored as the *one* tag
`"power, analog"`, and the build was green.

Status: **finished**. Merged as a PR off `origin/main`; see the PR for the
final commit.

## The bug, confirmed first

Reproduced in `.scratch/f2` (kept, per AGENTS.md) before touching anything:
a project on the bundled `hardware@3` standard with

```yaml
  - id: CMP-010
    title: Part with SCALAR tags
    part_number: TPS123
    tags: "power, analog"
```

gave, via `refdes check` (run as
`PYTHONPATH=<repo>/src python -m refdes.cli check` in the scratch project —
there is no installed `refdes` console script in this environment):

```
2 items, 0 errors, 0 warnings
exit=0
```

and, through the loader, `CMP-010 tags == 'power, analog'` (a plain string)
against `CMP-011 tags == ['power', 'analog']` for the list spelling. The
report's API observation (`GET /api/item/CMP-010` → `["power, analog"]`) is
the same fact seen from the other side; the loader is the source of it.

## Root cause, re-verified (line numbers from the report were current)

`src/refdes/parse.py::_build_item` merged a declared field's value straight
onto the item — `item.fields[key] = _strip_lines(value)` at line 446 before
the edit, with no check that a field whose `FieldSpec.type` is
list-shaped actually received a Python list. Both serializations funnel
through `_build_item` (called from `parse_markdown_file` and
`parse_list_file`), so that one site is the whole loader.

The editor's create path already had the equivalent check:
`src/refdes/serve/edit.py:961` (`if fspec.type in NON_SCALAR_FIELD_TYPES`),
refusing with *"field 'tags' is a list field: collections are not created
here -- create the item and edit the collection after"*. The constant it
consults was defined at `serve/edit.py:757` and re-aliased at
`serve/api.py:133`. So the tool was inconsistent with itself: the editor
refused loudly, the loader accepted silently and wrongly. The editor's
posture is the correct one and the loader was the half that was wrong.

## What changed

1. **`src/refdes/model.py`** — `NON_SCALAR_FIELD_TYPES` moved here from
   `serve/edit.py`, next to `FieldSpec` (it is a fact about the shape of a
   declared field, and `model` is the layer both `parse` and `serve` can
   import: `schema.py` imports `parse`, so `parse` importing anything from
   `serve` — or even from `schema` — would be a layering inversion). The
   docstring records *why* it is one constant: the two halves disagreed, and
   the loader was the wrong one.

2. **`src/refdes/serve/edit.py` / `src/refdes/serve/api.py`** — both now
   import the name from `model` rather than defining or aliasing it, so
   `edit.NON_SCALAR_FIELD_TYPES` and `api.NON_SCALAR_FIELD_TYPES` still
   resolve for anything that has always read them from those modules (they
   are the same object, asserted in a test).

3. **`src/refdes/parse.py`** — new `_reject_scalar_collection()` (plus a
   small `_value_shape()` so the message says "a string" where the author
   wrote a string, not `str`), called from the declared-field branch of
   `_build_item` before the value is stored. A field whose type is in the
   set, given anything that is not a `list`, is a `project.error`.

## The decisions worth recording

**Refuse, don't split.** The fix does not guess a delimiter. A comma split is
right for `"power, analog"` and silently wrong for a tag that legitimately
contains a comma — and it would replace a visible wrong value with an
invisible wrong value, which is strictly worse than what we had. This also
matches the editor, which already refuses.

**Error, not warning.** A warning here would reproduce the original harm in
a new place: the report's own point is that `refdes ls --tag analog` still
"finds" the item, because tag matching is a substring test, so the wrong
value looks right everywhere a newcomer would look. A warning is easy to
miss and the build still goes green.

**Error, not a coercion into a one-element list.** The value is still stored
as authored (unchanged from before), so downstream code still has something
to read while the build is red; what the check forbids is the *silence*. No
attempt is made to normalise it.

**Null is left alone.** A bare `tags:` is YAML null, and the loader already
has a diagnostic for exactly that case (coalesce to the field's `default`,
with a warning — `parse.py`'s explicit-null branch). Reporting one keystroke
twice helps nobody, so `_reject_scalar_collection` returns early on `None`.
Verified by running it, with a defaulted list field:

```
WARNING items/cmp.yaml:3 [CMP-010] — 'tags' was written as an explicit null
(a bare tags: with no value) -- treating it as absent and using the default
['untagged'] instead of leaving it unset and unvalidated.
```

**A value inherited from `defaults:` is reported at the defaults block.** The
key the author has to edit is in the `defaults:` block, not in whichever item
happened to be diagnosed first. The loader tracks the block's own first-key
line (`__line__` on the raw mapping) and reports that, the same line
`_warn_dead_defaults_status` uses for a dead defaults entry. It does not
track per-key lines inside a mapping, so this is block granularity, not the
`tags:` key's own line — consistent with every other parse diagnostic, which
is item-granular.

**Links stay lenient.** `satisfies: REQ-001` as a bare scalar is *not* this
bug: a link verb takes a list of targets and a scalar names exactly one, so
one target in and one edge out, nothing lost or misread. The report called
that leniency intentional; it is unchanged and pinned by a test, because a
later sweep at "scalars in the loader" is exactly the kind of change that
would take it by accident. The check reads `fspec.type` and is only reached
from the *field* branch of the merge loop, never the *link* branch.

## The message

```
ERROR   items/cmp.yaml:3 [CMP-010] — field 'tags' is a list field, but it
was given a string 'power, analog' -- write it as a list, one entry per value
(tags: [first, second]). A scalar is never split; it is kept as one entry:
the comma is part of the value, so a search for either of those values
matches only by substring, and the stored value is never equal to either of
them.
```

It names the field, the declared type, what was found, and what to write.
The last clause is conditional: for `tags: power` (one value, no comma) the
message says instead that the build cannot tell whether you meant one value
or several — a substring search *does* find that one, and a diagnostic
claiming otherwise would be a second wrong thing in a message whose job is
to be believed.

## Tests

`tests/test_scalar_for_list_field.py` (11 tests, new file):

- the report's repro verbatim, through the CLI: exit 1, and the message
  names the field, the type and the value found;
- the stored value is still the scalar (not split, not wrapped) while the
  build is red — the silence is what's forbidden, not the load;
- the list spelling of the same project still builds with 0 errors;
- a *second* list-typed field on the same type is caught too (proves it
  reads `FieldSpec.type`, not the name `tags`), and so is a mapping value;
- a bare null still takes the pre-existing explicit-null path;
- a scalar inherited from `defaults:` is reported at the block, for every
  item that inherits it, and a list-valued default with per-item overrides
  is untouched;
- the Markdown front-matter form is checked the same way;
- `satisfies: REQ-001` as a bare scalar still produces exactly one resolved
  edge (asserted on `resolved_links`, not raw `links`);
- `edit.NON_SCALAR_FIELD_TYPES is api.NON_SCALAR_FIELD_TYPES is
  model.NON_SCALAR_FIELD_TYPES` and the set's contents — this is what rules
  out a second hand-maintained copy, which is how the original bug happened.

**Confirmed the new tests fail without the fix**: with the one call site in
`parse.py` temporarily stubbed out, the six tests that assert the new
behaviour fail and the five regression guards pass. Restored immediately
afterwards (verified with `git diff --stat`).

## Verification run

- `pytest -q` → **2698 passed, 2 skipped** (before this change: 2687 passed,
  2 skipped — the 11 new tests and nothing else).
- `ruff check` on the four source files I touched and the new test: 4
  findings, all pre-existing on `main` (3 × `UP037`, 1 × `DTZ011`,
  confirmed by running ruff over the same files extracted from `HEAD`). No
  new findings. A green `ruff check .` is not a gate on this repo (AGENTS.md
  — ~99 pre-existing findings); this was scoped to the files touched.
- `refdes check` on this repo's own project: 1 error, which is the
  pre-existing `DEC-PWR-001` thermal failure the report also describes
  (finding F4), not something this change introduced, and no new
  "list field" diagnostics.
- Docs example tests are part of the suite above, so no doc example in the
  tree uses a scalar for a list-typed field.

## Also changed

- `docs/schema-reference.md` — a short paragraph next to the "enforced
  today" field-type note, with the example diagnostic, the no-splitting
  rule, the link exception, and the null case. No new page: this belongs
  with the field-type reference that already exists.
- `changelog.d/scalar-for-list-field.breaking.md` — filed as **breaking**,
  not fixed: a project that has a scalar on a list-typed field today will
  stop building until it is written as a list. That is the intended
  consequence, but it is still a change an existing project has to make.

## Known adjacent gap, deliberately not fixed here

A list-typed field's **schema `default:`** is not type-checked —
`configcheck.py` validates a field declaration's keys but not the shape of
its `default` value, so `tags: { type: list, default: "power, analog" }` in
`refdes-schema.yaml` would hand every inheriting item the same scalar. It is
the same class of mistake from the other direction (declared configuration
rather than authored content), a schema author's error rather than a
content one, and out of scope for a fix pinned to a content repro. Worth a
follow-up; noted here so it isn't rediscovered from scratch.
