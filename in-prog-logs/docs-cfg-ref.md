# docs-cfg-ref — user-facing docs for the two-file config split (backlog finding 28)

Branch `ao/refdes-60/root`, fast-forwarded with `git merge --ff-only
feat/config-split` onto `4c4b8ea` ("tests: migrate cfgsplit-b-d fixtures to
the two-file config"). `git log --oneline -1` confirms the tip is `4c4b8ea`;
tree clean after the merge.

Scope: prose updates in `docs/multi-board.md`, `docs/standard-library.md`,
`docs/schema-reference.md`, `docs/troubleshooting.md`, plus this log. No
`src/`, `tests/`, CHANGELOG.md, changelog.d/, or backlog touched.

## What I verified before writing (per AGENTS.md "name the file")

- `src/refdes/schema.py` — `PROJECT_SETTINGS_NAME = "refdes-project.yaml"`
  (the marker, `find_config` walks up for it), `SCHEMA_NAME =
  "refdes-schema.yaml"` (optional overlay; `_load_schema_overlay` accepts
  only `types:`/`link_types:`/`field_sets:`, and errors on anything else),
  `LEGACY_CONFIG_NAME = "refdes.yaml"` with `LEGACY_CONFIG_ERROR` naming
  both replacements. Settings keys are site/id/boards/workspaces/units/
  history/standard/equations/imports plus the process settings (sigfigs,
  item_layout, ..., release_gate).
- `src/refdes/scaffold.py` — `refdes init` writes **only**
  `refdes-project.yaml` (`_init_yaml`: site:, standard:, id:) plus
  `.vscode/settings.json`; no `refdes-schema.yaml` ever.
- `src/refdes/imports.py` — import diagnostics carry `file="refdes-project.yaml"`.
- `src/refdes/schema_json.py` `write_schema` — the `.refdes/schema.json`
  stale check compares against the **newer** mtime of
  refdes-project.yaml/refdes-schema.yaml; `src/refdes/cli.py` `cmd_check`
  warns ".refdes/schema.json was older than refdes-project.yaml -- refreshed".
- Ran the tool against this branch's source (PYTHONPATH to this worktree's
  src, venv python):
  - legacy-only dir → `configuration error: refdes.yaml is retired. Split
    it into the two files it became: ...` (exit 2) — matches
    `LEGACY_CONFIG_ERROR`.
  - empty dir → `configuration error: no refdes-project.yaml found in ...
    or any parent directory -- that file is the project marker, ...`
  - `refdes init` in a fresh dir → wrote `refdes-project.yaml` (site/
    standard/id) + `.vscode/`, no schema file; `init --help` and `--help`
    both say "refdes-project.yaml".

## Edits per file

- **docs/multi-board.md** — 5 hits. Prose + both example-file comment
  headers and both `ERROR refdes.yaml — import ...` samples renamed to
  `refdes-project.yaml` (imports:/site: are settings keys, so the renamed
  file is right). Diagnostics verified against imports.py.
- **docs/standard-library.md** — intro now says the `standard:` pointer
  lives in `refdes-project.yaml` and most projects have no
  `refdes-schema.yaml`; `standard:` example blocks labelled
  `# refdes-project.yaml`; every types:/link_types:/field_sets: example
  block labelled `# refdes-schema.yaml`; "Opting out" rewritten (see
  calls); `refdes init` paragraph says it writes only refdes-project.yaml
  and no schema file; editor-support overlay named; mtime sentence updated
  to the two-file comparison.
- **docs/schema-reference.md** — intro rewritten to the two files; top-level
  key map split into the two files with their own comment banners; `standard`
  section's "this file" claims pointed at the right file; field_sets/
  link_types/types example blocks labelled `# refdes-schema.yaml`;
  "Starter types" notes most projects have no schema file; item-level
  `history` no longer "part of `refdes.yaml`" but the counterpart to the
  `history:` setting in refdes-project.yaml.
- **docs/troubleshooting.md** — the "no config found" entry renamed and
  body rewritten (marker + search-upward); **new entry** for the legacy
  `refdes.yaml is retired...` error (the task's "may want"); "unknown type"
  entry now points at merged schema = standard (+presets) or your own
  `refdes-schema.yaml`.

## Judgement calls

1. The last sentence of "Opting out" — "A config written before this
   feature shipped needs no changes to keep working" — is now false (a
   pre-split `refdes.yaml` refuses to load). Rewrote it to say the
   vocabulary is unchanged and the split only relocates schema keys into
   `refdes-schema.yaml` and settings into `refdes-project.yaml`.
2. The `.refdes/schema.json` mtime check is against the *newer* of the two
   config files (schema_json.py takes max), though the CLI warning message
   only ever names refdes-project.yaml. Doc says "whichever ...
   changed most recently", which is the true mechanism.
3. Kept the example `standard.version: 2` untouched (pre-existing,
   hardware@3 example drift predates and is unrelated to this change).
4. The only remaining `refdes.yaml` occurrences are inside the new
   troubleshooting legacy-error entry (heading quotes the error; body
   explains "delete refdes.yaml: nothing is read from it any more") — both
   deliberate.

## Gates

- `git grep -n "refdes\.yaml"` on the four doc files → only the two
  deliberate troubleshooting hits above.
- `python -m pytest tests/ -q` (venv python, `PYTHONPATH` to this
  worktree's `src`): **72 failed, 608 passed, 11 errors in 26.04s** —
  the pre-existing red baseline from other in-flight work that owns
  `tests/` (failures are in test_stub_tests / test_imports /
  test_parse_markdown, none related to docs). A docs-only diff cannot
  change this number; noted for the record rather than used as a gate.
- `git status --short` before commit — the four files plus this log.

## Status

**Finished.** Committed locally on `ao/refdes-60/root`, not pushed.