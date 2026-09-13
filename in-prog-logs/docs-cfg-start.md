# docs-cfg-start — user-facing docs for the two-file config split (backlog finding 28)

Branch: `ao/refdes-59/root`, fast-forwarded onto `feat/config-split`
(`git merge --ff-only feat/config-split` -> 4c4b8ea confirmed via
`git merge-base --is-ancestor 4c4b8ea HEAD`).

Scope: README.md, docs/getting-started.md, docs/cli-reference.md — the
first-run surface. Nothing else touched (no tests/, src/, CHANGELOG.md,
changelog.d/, docs/design/backlog.md).

## What I checked before writing anything

- `src/refdes/scaffold.py` — `init()` writes `refdes-project.yaml` only
  (line 91); refuses only when `refdes-project.yaml` already exists
  (lines 92-93). No other file is written by `refdes init`.
- `src/refdes/schema.py` — `PROJECT_SETTINGS_NAME = "refdes-project.yaml"`
  is the marker `find_config()` walks upward for; `SCHEMA_NAME =
  "refdes-schema.yaml"` is optional (`_load_schema_overlay` returns `{}`
  when absent) and validates to exactly `types:`/`link_types:`/`field_sets:`;
  `LEGACY_CONFIG_NAME = "refdes.yaml"` raises `LEGACY_CONFIG_ERROR` naming
  both replacements. `history.default` is the project-wide on_change default
  (line 455); per-field `on_change:` lives on the schema field spec
  (line 496).
- `src/refdes/cli.py` — `-c/--config` help says "path to refdes-project.yaml"
  (line 854); `init` parser help/description say "write a minimal
  refdes-project.yaml ... no types:/link_types:/field_sets:" (lines 1025-1031);
  `standard upgrade` writer bumps `standard.version:` in refdes-project.yaml.
- `src/refdes/revise.py` — plain `revise` "only ever touches item files,
  never [the settings file's] own schema declarations" (lines 687-691), so a
  hand-rolled schema's `types:`/`link_types:` edit must be the author's own,
  in `refdes-schema.yaml`.
- This repo's `refdes-project.yaml` registers two boards (worked example the
  README points at).

## Edits

README.md
- Commands block comment: "write a minimal `refdes-project.yaml`".
- Change tracking: rewrote "Set per field in `refdes.yaml`" -> per-field
  `on_change:` lives in the schema (a project's own fields in
  `refdes-schema.yaml`), the project-wide default in `history:` in
  `refdes-project.yaml`. Simple rename would have been wrong here: per-field
  on_change is not a settings-file key.
- Multiple boards: repo link `refdes.yaml` -> `refdes-project.yaml`.

docs/getting-started.md
- "A project is any folder containing `refdes-project.yaml` — the file is
  the project marker, and it holds every project setting."
- Added the optional-schema-file sentence ("If you define types of your own,
  they go in an optional `refdes-schema.yaml` beside this file — that one
  holds only `types:`, `link_types:`, and `field_sets:`"), since the tree
  below previously implied one combined file.
- Project tree: `refdes.yaml` -> `refdes-project.yaml`.

docs/cli-reference.md
- `-c/--config` row: "Use this `refdes-project.yaml`."
- `refdes init`: writes a minimal `refdes-project.yaml`; refuses if
  `refdes-project.yaml` already exists.
- `refdes standard upgrade --to N`: bumps `standard.version:` in
  `refdes-project.yaml`.
- `refdes revise`: schema to move with the data is `refdes-schema.yaml`
  (never `refdes-schema.yaml`'s own `types:`/`link_types:` is touched; the
  author pairs the rename with their own edit there).

## Verification

- `Select-String -Path README.md, docs/getting-started.md, docs/cli-reference.md
  -Pattern "refdes\.yaml"` -> no matches. No deliberate legacy mentions kept:
  the tool's own error message is the right place for readers to meet
  `refdes.yaml`'s retirement, and a first-run tutorial doesn't need it.
- Tests: no code touched; pytest still red from unrelated work (see below).

## Judgement calls

1. README Change-tracking sentence: renamed to the truth rather than
   mechanically. Per-field `on_change:` is a schema-field declaration
   (refdes-schema.yaml or the bundled standard), not a settings-file key;
   `refdes-project.yaml` holds only `history.default:`.
2. Getting-started: added the `refdes-schema.yaml` mention to the init
   paragraph rather than only renaming, because the "one file" tree made the
   old layout look like the whole story. Kept it to one sentence.
3. Describe the legacy error? Decided against in all three files — it's the
   tool's own error text, readers will see it verbatim when they hit it.

## Status

Finished. pytest number unchanged from other work's red state (noted in
report); no code touched.