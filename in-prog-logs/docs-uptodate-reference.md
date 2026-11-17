# Docs up-to-date pass — reference group

Base: `fed21b80` (#488). Scratch projects under `.scratch/` (proj, proj2,
blocksproj, mathproj, upgradeproj, presetproj, presetup, preset3, partsproj,
listproj, boardproj).

## docs/schema-reference.md — changed

- Compared every type/field/link target against `refdes schema --json` in
  `.scratch/proj` (hardware@3, no overlay): six types, all fields, all link
  targets match the page's tables and generated examples. Also matched
  `src/refdes/standards/hardware/v3/base.yaml`.
- `refdes schema --help` and `refdes init` run to confirm the command surface.
- Config keys checked against `_KNOWN_SETTINGS`, `SITE_KEYS`, `ID_KEYS`,
  `TYPE_KEYS`, `FIELD_KEYS`, `LINK_TYPE_KEYS`, `UNITS_KEYS`,
  `STANDARD_KEYS`, `BOARD_KEYS`, `WORKSPACE_KEYS`, `IMPORT_KEYS`
  (`src/refdes/schema.py`, `configcheck.py`).
- Added: `units.aliases:` (accepted; `refdes math.md` documents it, page did
  not), a `## equations` section (`_load_equations`, `EQUATION_KEYS`), and a
  `## Process settings` table for the eight keys the "every key" intro
  omitted (defaults from `model.py`/`schema.py`).
- Corrected: `citations:` entries accept `item:` as an alternative to `path:`
  (`schema_json._FIELD_TYPE_MAP` anyOf; `#176` note in v3 migration), and the
  enforced field types list (`build.validate_items`: date/list/options too).
- Corrected `check_severity:` mapping rule to "cover every status or declare
  default" (`schema.py::_parse_check_severity`).
- Replaced the list-field sample with the real text from `refdes check` in
  `.scratch/listproj`.
- `configuration error: boards…path segments must be unique` reproduced in
  `.scratch/boardproj` and matches the page.
- Could not verify: every future reference to `site.tokens` contrast ratios
  (covered by tests/test_theme.py, not re-derived by hand).

## docs/standard-library.md — changed

- Six types / fifteen verbs / statuses / sets re-checked against
  `refdes schema --json` and `v3/base.yaml`; all match, including "no
  decision type", `legacy_prefixes: [DEC]`, and "no presets".
- `refdes standard add-preset design-debate` on hardware@3 reproduced the
  page's `does not exist for hardware@3 (available: [])` text.
- `refdes standard upgrade --to 3` run in `.scratch/upgradeproj` (v2 project):
  output matches the page's sample, including the capture line and the
  edited-after-captured warning.
- `remove-preset` reproduction in `.scratch/presetproj` matches the page's
  diagnostic and exit 1. `presetup` reproduced the upgrade refusal; the
  page's sample had a trailing period the command does not print — fixed.
- `refdes init` run in a fresh git repo (`.scratch/proj2`) and a nested
  scratch dir: a .gitignore is skipped for entries git already covers, so
  qualified the page's claim.
- `refdes new decision` confirmed stderr + exit 1; `--help` for `init`,
  `standard`, `new` checked.

## docs/blocks.md — changed

- Parameter sets checked against `BLOCK_SPECS` in `src/refdes/blocks.py`:
  index/cascade/compare/tree/calcblock all match the page.
- Failure examples reproduced in `.scratch/blocksproj`; the `{{index
  by="pageno" type="log"}}` declared-fields list was stale — replaced with
  the actual hardware@3 list from `refdes build`.
- Other sampled messages (unknown type/parameter, missing parameter) match.

## docs/parts.md — changed

- `refdes build` on `.scratch/partsproj` produced `parts.html`, and `refdes
  audit` printed the `Parts:` section with every part number; page matches.
- `refdes new component --list` output matches the page's skeleton.
- Changed "walks only `item.links`" to "walks only authored links"
  (`workspaces.py` iterates `resolved_links`; the semantic claim is unchanged).

## docs/math.md — checked clean

- Calc sample output re-run in `.scratch/mathproj` (0.2981 W, 1.26 in²,
  0.2366 W/in²) matches the page.
- Reproduced the unit-assertion error, unit/variable warning, and
  `unknown unit 'wat'`; text matches.
- Functions list, block-name grammar (`BLOCK_NAME_RE`), equation cycle/arity
  messages, `equations:` shape, and `source()`/lockfile claims checked against
  `src/refdes/calc.py`, `schema.py`, `citations.py`.
- Sampled, not exhaustive: every inline-calc/live-editor sentence was checked
  against `serve/static/live-calc.js`, not driven in a browser.

## docs/themes.md — checked clean

- Generated token tables verified current with `python docs-site/gen_themes.py
  --check` and `tests/test_themes_page.py`.
- Prose claims (default emits no file; light/dark routing; token validation
  limits) checked against `src/refdes/theme.py`. No edit.

## docs/vocabulary.md — checked clean

- Generated block verified with `python docs-site/gen_examples.py --check`
  and `tests/test_vocabulary_page.py`; the term list matches `refdes schema`.
- Prose references (`refdes former-ids propose --confirm`, `refdes id`,
  `vocabulary.html`) checked against `refdes --help`. No edit.

## Tests run

- `tests/test_docs_anchors.py`, `test_docs_examples.py`,
  `test_themes_page.py`, `test_vocabulary_page.py`,
  `test_crossplatform_lint.py`: 68 passed.
- `docs-site/gen_examples.py --check` and `gen_themes.py --check`: clean.
- Full suite once before push (see PR).

## Notes / not reached

- No code changed. No browser run (not required for these pages).
- Did not re-run every historical migration example in the standard-library
  page beyond the v2→v3 walkthrough above; source `migration.yaml` was read.
