# Three confirmed message-wording bugs (F7, L3, L6) — done

Task: fix the three small wording bugs in `in-prog-logs/user-sim-release-gate-run1.md`
§2 (F7, L3, L6), as three independently-testable edits, each with a test.

## F7 — the append-only error named a flag the printing command doesn't have

`src/refdes/seal.py:335` built the hint as `--reseal` / `--reseal {board}` and
dropped it into "... or run with {hint} if the edit is deliberate." `verify()`
has two callers and one of them is `refdes check` (see the `reseal=` argument at
`build.py:2891` and its `False` at `cli.py:178`/`cli.py:286`), and `refdes check`
has no `--reseal` at all — the suggestion is only a usage dump and exit 2 there.

Fixed by a new `_reseal_hint(board)` helper (`seal.py:52`) that spells the command
out: `refdes build --reseal {board}`, `refdes build --reseal` unboarded.

**Slightly beyond the letter of the report:** the *other* half of the same
defect — the deleted-sealed-entry error in `_report_deleted`
(`seal.py:403`, "restore it, or run with {hint} if the removal is deliberate") —
had the identical bare-`--reseal` hint and is quoted verbatim in
`docs/design-log.md:94`. Leaving one fixed and one broken in the same function
pair would be knowingly shipping half a fix, so it routes through the same
helper. The report did not name it; flagging that here.

Docs quoting the messages verbatim were updated so they don't now lie:
`docs/design-log.md:83` and `:94`.

Verified live (throwaway project in `.scratch/msgfix/sealproj`):

```
$ refdes check
ERROR   items/log.yaml:3 [LOG-001] — LOG-001 is append-only and has been modified
        since it was sealed. Append a new entry with `amends: [LOG-001]` instead,
        or run with refdes build --reseal if the edit is deliberate.

$ refdes build --reseal     # the suggested command, run verbatim
WARNING items/log.yaml:3 [LOG-001] — resealed after an edit to a sealed entry ...
```

## L3 — malformed sentence in the missing-image error

`src/refdes/build.py:2365` built `searched` as a fragment
(`"the site.assets directories: ..."` or `"no site.assets directories are
declared to search"`) and then wrapped it as `(searched {searched})`, which only
fits the populated branch. `searched` now holds the *whole* parenthetical
(`"searched the site.assets directories: ..."` / `"no site.assets directories
are declared to search"`), so both branches read as one clause. The populated
branch's text is byte-identical to before.

Verified live (`.scratch/msgfix/proj`):

```
# no site.assets declared
... image src 'board.png' does not exist (no site.assets directories are declared to search)
# site.assets: [shots, more]
... image src 'board.png' does not exist (searched the site.assets directories: shots, more)
```

## L6 — Python repr() in user-facing prose

The report named one instance exactly and two by description. The two
descriptions turned out to be the *same* line, `build.py:566`, which had both
defects at once: a bracketed list of allowed target types, and the raw
`target_id` — a `DISPLAY-ID@key` composite whenever the target has been
link-expanded — quoted mid-sentence. So this is two lines, not three:

- `build.py:235` — `f"{fspec.choices}"` → `", ".join(fspec.choices)`. The
  `{value!r}` on the offending value stays: quoting a scalar is prose, quoting a
  list is a debug print.
- `build.py:566` — `", ".join(allowed)`, and `target_ref = target.id or target.key`
  hoisted above the error so the message names the *resolved* reference instead
  of the raw composite. `target_ref` is the same value the two lines below it
  already used for `resolved_links`/`backlinks`, so this is `Item.resolved_links`
  vocabulary (`model.py:470`) rather than raw `Item.links` (`model.py:464`) — the
  bare, always-current spelling, per `AGENTS.md`. Bonus: the stale-label hazard
  `_unknown_key_message` (`build.py:483`) goes on about is absent by
  construction, since this is the live item's own id.

Declared order is preserved in both (not sorted), so the lists read in the order
the schema declares them.

Verified live, on a real composite written by the tool itself:

```
$ grep constrained_by items/part.yaml
    constrained_by: [REQ-002@ecn36jvt1f6]
$ refdes check
ERROR   items/part.yaml:3 [CMP-001] — constrained_by may point at bound, but REQ-002 is a requirement
```

### Left alone, deliberately

`grep -rn "must be one of" src/refdes/*.py` shows ~8 more list-repr messages in
the **config/schema validation** family (`schema.py:138`, `parse.py:416`,
`standards.py:109`, …), and `tests/test_project_settings.py:227` pins one of
them as a regex. That is a different subsystem from the item-level diagnostics
this task scoped, so I did not touch it — but it is the same genre and the same
shape, and a follow-up pass would be a clean, mechanical `", ".join(...)` across
that family.

Two docs quotes were updated (`docs/troubleshooting.md:61` for the enum message,
`:164` for the link-type message) because they reproduce the messages verbatim
and would otherwise be the stale copy the reader finds first.

## Tests

- `tests/test_seal.py::test_the_violation_hint_names_a_command_the_printing_command_actually_has`
  — asserts the full hint text for the boarded and unboarded cases *and* for the
  deletion half, plus that no message can suggest a bare `--reseal` again.
- `tests/test_image_search.py::test_the_missing_image_sentence_is_grammatical_with_and_without_assets`
  — pins both parentheticals exactly, in one test, because the bug was that the
  two branches disagreed.
- `tests/test_build.py::test_the_enum_error_lists_its_choices_as_prose_not_a_python_list`
  and `::test_the_wrong_link_type_error_names_the_bare_display_id` — new
  "diagnostic prose" section at the top of the file. The link test mints a real
  key with `keys_mod.mint()` and writes the composite by hand; a literal
  placeholder key would have tripped the §6 corruption lint instead (keys are
  exactly 11 characters — found the hard way).

Three existing tests pinned the old strings and were updated to the new text
rather than loosened: `test_extends.py:412`, `test_revise_migrations.py:116`
(`may point at ['bnd']` / `['component']`).

Suite: `2611 passed, 2 skipped` — run with `--ignore=tests/test_schema_json.py`,
which cannot import `jsonschema` in this environment. That is an environment gap,
unrelated to this change and untouched by it.

`ruff check` on the five touched files: 3 findings, all three also present on
`HEAD` for the same files (two pre-existing `I001` import-order blocks, one
`SIM115`). No new findings; per `AGENTS.md` the unrelated pre-existing ones are
left alone.

## Three changelog fragments

`changelog.d/append-only-reseal-hint.fixed.md`,
`changelog.d/missing-image-sentence.fixed.md`,
`changelog.d/diagnostics-no-python-repr.fixed.md` — one per finding, since each
is a separate change with its own audience sentence.

## Status

Finished. Nothing left half-done; the only open thread is the config-validation
`must be one of [...]` family noted above, which was out of scope.
