# F3 — a confidently-misspelled field name is now a build error

Task: fix finding **F3** of `in-prog-logs/user-sim-release-gate-run1.md`
(§"F3 — a misspelled field is only a warning, so the build goes green without
the field"). Explicitly approved by the project owner as a **deliberate,
breaking severity change** — the decision is made; this log records the
implementation, not a debate about whether to do it.

Status: **finished**. Committed and PR'd against `main`.

## The breaking part, stated plainly

Any project that has a field name which is a confident near-miss of a declared
field of the same type now **fails its build** where it previously passed with
one warning. `partnum: TPS123` on a `component` was
`WARNING … 0 errors, 1 warnings`, exit 0; it is now
`ERROR … 1 errors, 0 warnings`, exit 1 for both `refdes check` and
`refdes build`. The value is still loaded, so the fix is a one-word rename in
the item file — but until someone makes it, CI is red. That is the intended
outcome: the warning was describing the bug (a field silently missing from the
report it feeds) without failing anything.

The lenient half is unchanged on purpose: an unknown field with **no** close
match is still a warning, same wording, same `_suggest` hint, exit 0. Novel
metadata, forward-compat fields, deliberate extra data — none of those have a
typo interpretation, and the repo already treats "unrecognized input with no
clear correction" as forward-compatible elsewhere (`serve/filters.py::parse_filters`:
*"Unknown parameters are ignored (forward-compatible); known ones are validated
here so a typo is a 400 rather than an empty list"*). Same split: confident
correction → fail; no correction → stay lenient.

## What changed

`src/refdes/parse.py`, `_build_item`, the catch-all `else:` for an undeclared
key (was lines 564–589). It already had three branches — preset-provided link
(error), confident **link**-verb match (error), everything else (warning) — and
the second one is the pattern this change follows:

```python
link_match = difflib.get_close_matches(key, sorted(spec.links), n=1, cutoff=0.6)
field_match = difflib.get_close_matches(key, sorted(spec.fields), n=1, cutoff=0.6)
...
elif field_match:
    project.error(
        f"unknown field {key!r} on {spec.label.lower()} -- did you mean "
        f"the field {field_match[0]!r}? A misspelled field name silently "
        f"drops it instead of erroring.",
        file=rel, line=line, item_id=item.id or "?",
    )
```

- `spec.fields` is the declared scalar-field name set, the same source the
  warning branch's `_suggest(key, sorted(known_keys))` already draws from
  (`known_keys = set(spec.fields) | set(spec.links) | RESERVED | OVERRIDABLE`).
  Nothing new was invented; the new match is deliberately narrower than the
  hint's set — see the `boardd` case below.
- Cutoff stays **0.6**, the same constant the link branch and `_suggest` use.
  No opt-out, no new setting.
- Branch order is preset → link → field → warn, so branch 1 (link-verb typo)
  is byte-for-byte untouched and still wins when both could match.
- Message wording deliberately mirrors the two neighbours: *"did you mean the
  link 'satisfies'? A misspelled link name silently drops the edge instead of
  erroring"* / *"did you mean the field 'part_number'? A misspelled field name
  silently drops it instead of erroring"*. One family, three cases.

### Parity on storing the value (asked for explicitly)

Checked the existing link-verb error branch: after `project.error(...)` it
**still** runs `item.fields[key] = _strip_lines(value)` — that line sits after
the whole `if/elif/else`, so all three branches store the value under the
typo'd key. The new field branch inherits that same line, so it stores too.
Reasoning for keeping the parity rather than refusing more fully: the build is
red either way, so the storage is not a leniency the author can miss; it is the
difference between a red build whose item still contains the text you wrote and
a red build that also destroyed it (and, per F2's reasoning in
`scalar-for-list-field-f2.md`, what the check forbids is the *silence*, not the
load). Two unknown-key error paths disagreeing about whether your text survives
would itself be a bug. Pinned by
`test_the_typo_value_is_still_loaded_parity_with_the_link_branch`.

## Manual repro, before and after

Scratch project: `.scratch/f3/my-board/` (bundled `hardware@3`, no overlay),
`items/bad3.yaml` holding the report's `CMP-003` with `partnum: TPS123` plus two
correctly-spelled parts, so the item count matches the report's `3 items`.

**Before** (HEAD's `parse.py`, run from `.scratch/f3/before/src`):

```
WARNING items/bad3.yaml:16 [CMP-003] — unknown field 'partnum' on component. Did you mean 'part_number'?
3 items, 0 errors, 1 warnings
exit=0
```

which is the release-gate report's output verbatim (modulo line number, since
the scratch file spells out `defaults:`).

**After** (this worktree's `src`):

```
ERROR   items/bad3.yaml:16 [CMP-003] — unknown field 'partnum' on component -- did you mean the field 'part_number'? A misspelled field name silently drops it instead of erroring.
3 items, 1 errors, 0 warnings
exit=1
```

`refdes build` on the same project:

```
ERROR   items/bad3.yaml:16 [CMP-003] — unknown field 'partnum' on component -- did you mean the field 'part_number'? A misspelled field name silently drops it instead of erroring.
build completed with errors (use --keep-going to exit 0)
3 items, 1 errors, 0 warnings
site written to .scratch/f3/my-board/_site
exit=1
```

**The lenient half, unchanged** — `.scratch/f3/my-board-lenient/` with
`thermal_model: yes` (no declared key within 0.6 of it), run against *both*
trees, identical output, exit 0 both times:

```
WARNING items/novel.yaml:6 [CMP-010] — unknown field 'thermal_model' on component.
1 items, 0 errors, 1 warnings
exit=0
```

### How "before" was run, and an environment note

The `refdes` console script in this environment is dead: its editable install
(`__editable__.refdes-0.5.0.pth`) points at `/tmp/w-pr59-merge/src`, which no
longer exists, so `import refdes` fails and `refdes check` cannot run at all.
This shell also refuses a `PYTHONPATH=…` command prefix, so the usual
`PYTHONPATH=src python -m refdes.cli` from the F2 log is unavailable too.

What I did instead, kept entirely inside `.scratch/`: copied `src/` to
`.scratch/f3/before/src`, reverted the one hunk in that copy, and verified the
copy is **byte-identical to HEAD** by blob hash —
`git hash-object .scratch/f3/before/src/refdes/parse.py` ==
`git rev-parse HEAD:src/refdes/parse.py` == `81227cb7b5d3fb9a9796b96c42a7f21fc672af2f`.
`.scratch/f3/run.py` then selects which tree to import by path and calls
`refdes.cli.main`, which is the same entry point the console script uses. Flag
for a human: if you want the before/after re-run with the real `refdes` command,
reinstall (`pip install -e .`) into the venv first.

## Tests

New file `tests/test_scalar_typo_error.py`, 9 tests, on the bundled
`hardware@3` standard (no overlay) so it is the report's own schema:

- `test_confident_scalar_field_typo_is_a_build_error` — loader level: exactly
  one **error**, right item id and file, names `part_number`, and no warning
  mentions the key any more.
- `test_check_exits_1_on_a_scalar_field_typo` / `test_build_exits_1_on_a_scalar_field_typo`
  — both CLI surfaces exit 1 with the typo and the correction in stderr.
- `test_the_corrected_spelling_builds_green` — the same item spelled correctly:
  exit 0, no unknown-field diagnostic either way, `fields["part_number"]` set.
- `test_the_typo_value_is_still_loaded_parity_with_the_link_branch` — see the
  parity section above.
- `test_the_typoed_part_is_absent_from_the_parts_index` — states the harm the
  warning used to hide: `citations.by_part_number()` has no `TPS123` key and no
  `CMP-003` in any entry. The build is red now, so nobody reads that index by
  accident.
- `test_a_field_with_no_close_match_is_still_only_a_warning` — exit 0 and the
  message pinned **verbatim**: `"unknown field 'thermal_model' on component."`.
- `test_a_hint_pointing_at_a_non_field_stays_a_warning` — `boardd:` is close to
  `board`, which is an overridable reserved key rather than a declared field of
  `component`, so severity stays a warning and the hint text is pinned verbatim:
  `"unknown field 'boardd' on component. Did you mean 'board'?"`. This is the
  boundary between the new error and the unchanged hint: the error matches
  `spec.fields`, the hint matches `known_keys`.
- `test_a_link_verb_typo_still_reports_as_a_link` — branch 1 unchanged: still
  an error, still says *"did you mean the link 'satisfies'"*, and asserts the
  word "field" is absent so a later sweep at field names cannot re-point it.

### Existing tests

`grep -rl "unknown field" tests/` → `test_links.py`, `test_scaffold.py`,
`test_schema_json.py`, `test_parse.py`, `test_parse_markdown.py`. Each was read:

- `test_links.py::test_unrecognized_field_far_from_any_link_still_only_warns`
  (`completely_unrelated_nonsense`) — no-match case, still passes.
- `test_schema_json.py::test_generated_schema_does_not_reject_what_check_only_warns_about`
  (`datasheets` on a `requirement` whose only field is `text`) — checked the
  ratio: `difflib.get_close_matches('datasheets', ['text'], cutoff=0.6)` is
  empty, so it is still a warning and the test still passes.
- `test_scaffold.py::test_unknown_link_matching_a_preset_names_it`
  (`resolved_by`) — the preset branch, which is first and untouched.

**No existing test had to be updated.** The full suite was run on a clean tree
first (2713 passed, 2 skipped) and again with only the `parse.py` change and no
new test (2713 passed, 2 skipped) — so nothing on `main` hard-coded a
confidently-typo'd scalar field name as expecting a warning. The repo's own
`items/` is clean of them too, which is why the self-building tests stayed
green. Final count with the new file: 2722 passed, 2 skipped.

## Docs

- `docs/authoring.md` — the paragraph that said *"An unknown field is a
  **warning**, not an error, and the value is kept"* with the `sorce` →
  `source` example. `sorce` is a confident match (ratio 0.91), so that page was
  demonstrating the old severity with an input that now errors. Rewritten: the
  error case with its new message, why a field is the link-verb loss one level
  down, and the still-lenient case with its own example.
- `docs/troubleshooting.md` — same entry (`unknown field 'sorce'. Did you mean
  'source'?` / *"A warning."*) updated to the new message and severity, with
  the no-match case named as the one that stays a warning.
- Checked and deliberately left alone: `docs/links.md`'s `follows:` note
  (*"the build still succeeds — an unnoticed thread, not a failed one"*) is
  still true — `follows` is within 0.6 of no field, link verb, or reserved key
  on any bundled type, so it stays in the warning branch.
  `docs/cli-reference.md`'s `unknown field 'label' on spec` sentence is likewise
  still true for its own example (`label` matches nothing at 0.6).
- `configcheck.py` and every other module's project-config-level "unknown
  setting" logic: untouched, as instructed — different mechanism, different
  surface.

## Changelog

`changelog.d/scalar-field-typo-error.breaking.md` — `breaking` category per
`changelog.d/README.md` ("Breaking first" in Keep a Changelog's set, matching
`scalar-for-list-field.breaking.md` from F2). Says what changed, why, the exact
new message, that both commands exit 1, that only the confident match changes
severity, and what an affected project has to do.

## Verification

- `pytest tests/test_scalar_typo_error.py -q` → 9 passed.
- `pytest tests/ -q` → **2722 passed, 2 skipped**. Baseline on a clean tree was
  2713 passed, 2 skipped, and the delta is exactly the 9 new tests.
- `ruff check src/refdes/parse.py --select I,F` → All checks passed (exit 0).
  `ruff check tests/test_scalar_typo_error.py --select I,F,E501` → clean too.
  (The repo's bare `ruff check .` has ~99 pre-existing findings and is not a
  gate — see AGENTS.md.)

## Difficulties

- The dead editable install plus the `PYTHONPATH=` prefix refusal meant there
  was no direct way to run the CLI against either tree; worked around as
  described above with a blob-verified baseline copy in `.scratch/`, so the
  before/after evidence is still reproducible and honest.
- Two of the new tests were wrong on first run and are now correct: the
  diagnostic is reported at the **item's** line (6), not the offending key's
  line (8), and a helper that both created a project and loaded it hit
  `FileExistsError` on `items/` (now `mkdir(exist_ok=True)`).
- Choosing what "confident" should match against. Matching `known_keys` (what
  the hint uses) would have promoted typos of reserved keys — `titel`, `bord`,
  a mistyped `former_ids` — to errors as well, which is a wider break than the
  approved one. Matching `spec.fields` keeps it to declared fields of the item's
  own type, which is exactly the case F3 describes. `test_a_hint_pointing_at_a_non_field_stays_a_warning`
  pins the line.
- Known false-positive shape, accepted with the change: a *deliberate* field
  that happens to sit within 0.6 of a declared one — `sources:` next to a
  declared `source:` (ratio 0.92) — now errors and tells you to rename. The
  link branch has had this exact property since it landed (`satisfies` vs a
  hypothetical `satisfye` field), the cutoff was explicitly out of scope here,
  and the fix is one keystroke with a red build telling you where. Worth
  remembering if a real project ever reports it.
