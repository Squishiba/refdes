# fix(index): name the conditional navis key in `refdes index --help`

Task: the help for `refdes index` lists the payload's conditional keys
(boards/workspaces, threads, the capture pair) but omits `navis`, which
`render.items_json` emits when the project has Navis markers. Help text
only — no behaviour change.

## Verification before changing anything

- `git fetch origin main && git merge --ff-only origin/main`: already
  up to date; tip was #492 (> #402 size gate). Clean tree.
- Ran `refdes index --help` (absolute PYTHONPATH=src, venv python -m
  refdes.cli): confirmed the omission — the description lists boards,
  workspaces, threads and the captured/edited_after_captured pair, no
  `navis`.
- Read render.py `items_json`: `navis` is added only when
  `navis_mod.projection(project)` is non-empty (render.py:908-910) —
  "absent key, not null", the same convention as `boards`/`threads`.
  Row shape (navis.py `projection` docstring): `{key, text,
  source: {item, key, file, line}, archived, snapshot, text_changed}`.
- Built a scratch project under `.scratch/index-navis-key/` (config
  split per the two-file rule: site/on_change in refdes-project.yaml,
  the `note` type in refdes-schema.yaml; one `<!--navi: ... -->` marker
  in a front-matter item file). `refdes index --no-write` printed
  `navis: [{key: null, text: "Model worst-case copper temperature.",
  source: {...}, archived: false, snapshot: null, text_changed:
  false}]` — key present, list of rows, as docs/output.md §`navis`
  documents.

## Change

- src/refdes/cli.py: added `navis when it has Navis markers,` to the
  index description's conditional-keys list, matching the existing
  "X when <condition>" style.
- docs/cli-reference.md `refdes index` entry: its parenthetical listed
  the conditional keys and omitted `navis`, so it got the same
  sentence-half (`navis` too when it has Navis markers).
- changelog.d/index-help-navis-key.fixed.md added.

## Tests (red-first)

Extended tests/test_index_help.py (the file that already pins this
help text and checks named keys against a real payload):

- `test_index_help_names_the_navis_key_as_conditional`: pins the new
  phrase. RED before the change (assert failure on the old help),
  green after.
- `test_a_project_with_a_navis_marker_carries_the_navis_key`: runs
  `index` on a marker project and asserts the payload's navis rows.
  Passed before the change too (the payload always carried the key —
  the bug was help-only), and stays green; it keeps the help honest
  the way the file's docstring prescribes.
- Extended the plain-payload posture check: a marker-free project's
  payload must not carry `navis` (added to
  `test_the_named_keys_are_the_ones_a_real_payload_carries`).

Evidence: pre-change run — `1 failed, 5 passed` (the help-text test,
AssertionError on the old help). Post-change — `6 passed`.
Neighbours: tests/test_navis_cli.py, tests/test_navis_archive_cli.py,
tests/test_pr_size.py, tests/test_docs_context_refs.py — all pass.
`ruff check src/refdes/cli.py tests/test_index_help.py` scoped run.

Full suite: run once before pushing with the documented command
(`-n 4 --dist worksteal`); result recorded in the PR thread.

Status: finished.
