# changelog fragment audit (unreleased changelog.d/)

Scope: all 444 fragments in `changelog.d/` (README.md skipped). `release.py`
folds every fragment into CHANGELOG.md's `[Unreleased]`, so each is
release-note text and every backticked command, flag, command id, path,
route and config key it cites must exist. Ground truth was produced by
running, not remembering: `PYTHONPATH=<abs worktree>/src
/home/jorb/work/venv-refdes/bin/python -m refdes.cli <cmd> --help` for every
command, greps of `editors/vscode/package.json` + `extension.js`,
`src/refdes/serve/api.py`, `tools/docs_context/server.py`,
`src/refdes/standards/hardware/v3/base.yaml`, a scratch project's
`refdes schema --json`, and existence checks for paths.

Extraction (scripts in `.scratch/audit/`): 428 `refdes ...` command strings
covering all 24 top-level commands and the subcommands `navis ls|all|show|
archive|restore`, `standard add-preset|upgrade`, `keys adopt|restore`,
`former-ids propose`, `history capture|redact|migrate-seals`; 40 unique
`command + flag` pairs; 18 backticked `refdes.*` ids; 24 `/api/...` routes;
192 repo paths; the 60 most-cited colon-keys.

## Verified classes (how, and result)

- CLI commands: every cited command/subcommand appears in `--help` output
  run against this tree. OK.
- `refdes revise` (16 fragments): retired in name only — `refdes revise
  --help` exits 0 (alias of `rename`, stderr note), exactly as
  `rename-replaces-revise.changed.md` describes. OK, not phantoms.
  `refdes revise apply` (duplicate-mapping-key.breaking.md:33): "apply" is
  the mapping-file positional, not a subcommand; the sentence names the
  command, and the form is `refdes revise <mapping>`. OK (reads as the
  command + its argument list in context).
- Flags (40 pairs): each verified against that command's `--help`. Two look
  wrong but are deliberate: `refdes fetch --url` is the *announcement* of
  the rename to `--path` (citation-path.breaking.md); `refdes serve
  --token=…` is the abbreviation hazard the fragment says `serve` now
  refuses (serve-port-token-file.added.md). OK.
- VS Code / JS / Python ids: `refdes.refreshIndex` (package.json:35,
  extension.js:1204), `refdes.docsContext.url`, `refdes.editor.font` (
  fontsetting.js:11, localStorage), `refdes.live-calc.fallback` /
  `refdes.live-calc.autofill` (live-calc.js:21,28), `refdes.draft.corrupt.
  v1.<handle>` (drafts.js:14), `refdes.model.read_only_refusal`
  (model.py:902), `refdes.threads.threads_projection` /
  `refdes.threads.project_derived` (threads.py:330,685), `refdes.__version__`
  / `refdes.get_version` (__init__.py:7,20), `refdes.yaml` (retired
  filename, named as such in context). All exist. OK.
- Routes: `/api/items`, `/api/revision`, `/api/item/...` (edit/calc/
  continue/sources...), `/api/create/*`, `/api/images`, `/api/assets`,
  `/api/items/create`, `/api/navis*` all in serve/api.py; `/api/ask` and
  `/api/focus` in tools/docs_context/server.py:268-304 (the docs-context
  viewer is a `tools/` tool, "not shipped in the package" is true:
  pyproject packages are `src/` only). OK.
- Paths: all 192 exist. OK.
- Colon-keys (item front-matter, list-file, schema, config): all cited keys
  found in v3 base.yaml, the scratch project's schema JSON, or quoted in
  src (e.g. `conforms_to:` at schema.py:1033 / build.py:1174;
  `records:` is the hardware@2 verb `follows:` replaces, v2 base.yaml:76).
  OK.

## WRONG claims fixed

| fragment | claim (backticked) | verified against | fix |
| --- | --- | --- | --- |
| navis-lock-tooltip.fixed.md | `refdes.navisRefreshIndex`; "a click on the lock explains itself" | registered command is `refdes.refreshIndex` (package.json:35, extension.js:1204); the tooltip is a status-bar hover | renamed; "click" → "hovering" (in-prog-logs/navis-lock-tooltip.md line 6 same fix) |

## "Nothing visible yet"-family fixed (shipped in this same release)

Each said its feature was unwired/invisible "yet"; the completing fragment
is in this same unreleased set, so for a release-notes reader the claim is
false. Each was rewritten into a same-release pointer:

- tick-pane-model / task-pane-save-context / tick-save-model → wired by
  tick-save-ui ("can now save"); tick-save.js:111 POSTs
  `/api/item/<ref>/continue`.
- continue-endpoint ("No UI reaches it yet") → same, tick-save.js.
- navis-vscode-post, navis-vscode-actions-logic ("commands come in the next
  slice") → navis-vscode-actions: `refdes.navisArchive/Restore/Mint` are
  registered (extension.js:1212-1214).
- editor-journal-module ("saves not journaled yet, no command reads the
  journal") → editor-journal-wiring + `refdes recover` (in `--help`).
- pdf-source-picker ("accepting ... not here yet") → source-picker-accept +
  pdf-picker-accept fragments.
- source-picker-accept ("editor panel is the next slice") /
  source-picker-reads ("... are later slices") → source-picker-panel
  fragment.
- editor-edit-ui ("Link editing, item creation and id/key editing are still
  later slices") → link editing (browser-editor-links) and item creation
  (browser-editor-create) ship here; id/key editing does not — the wording
  keeps that exclusion.
- navis-slice-1 ("... by later slices") → mint/archive/site panels ship in
  this set (navis-slice-2, navis-site-panel).
- threads-identity-phase1 ("`follows:` isn't part of the bundled standard
  yet") → v3 base.yaml:166 declares it; rewritten to name hardware@3.
- docs-context-server ("while this fragment is still unreleased") →
  fragment-lifecycle meta-text dropped; facts kept.

## Not a defect (checked, kept)

- tick-pane-draft-ui "nothing is saved to the project yet" — permanent
  property of a per-tab draft.
- theming-token-layer "No visible change" — accurate description of a CSS
  token refactor.
- design-doc-status-lines / agents-keys-status — record their own doc fixes;
  verified their code citations (keys.malformed_key_message, adopt.py,
  links._planned_target, etc.) exist.
- "not shipped in the package" (docs-context tools) — true (pyproject
  packages `src/` only).

## Checks run

- No `tests/test_changelog_fragments.py` exists; `grep -rn changelog tests/`
  shows only comments pinning code behavior (test_thread_cli.py:755,
  test_serve_edit_response_paths.py:412) — no test pins fragment text.
- docs-site build (CI docs.yml) builds `docs-site/`, a separate refdes
  project; it does not read `changelog.d/`.
- `refdes --version` prints `refdes 0.5.0`, matching version-flag.added.md.
- Crossplatform lint + full suite: see below.
