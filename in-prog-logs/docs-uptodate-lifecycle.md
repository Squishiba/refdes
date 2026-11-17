# Docs up-to-date pass: lifecycle group

Base: fast-forwarded to origin/main (ff-only, no conflicts).

Method: read each page, then verified every command/flag against
`refdes <cmd> --help` and a run in `.scratch/docs-lifecycle`,
`.scratch/boardsproj`, `.scratch/navisproj`, `.scratch/pagesproj`, and
`.scratch/v3test` (absolute `PYTHONPATH=<worktree>/src` for every run);
checked page/type/link names against `refdes schema` and the `$defs`
dump; checked paths and keys against `src/refdes/`. Pages not listed below
were checked clean; the "changed" headings name the edit.

## lifecycle.md

Checked clean. Ran `revision`/`release`/`audit` on a scratch project:
name refusal (`revision ..`, bad chars, exit 2), identical re-stamp
("unchanged"), conflicting re-stamp, blocked release table, `--no-write`
preview, baseline file shape including `hash_format: 6`/`key`/`verdict`,
`uncomparable` report path, and the unwritable-tree text in
`cli.py:795-843`. Rule names/defaults match `model.RELEASE_GATE_DEFAULTS`
and `lifecycle.RULE_NAMES`; hash-format 1-6 descriptions match
`build.hash_payload_builder`; baseline snapshot events confirmed by
stamping then building (`req-pwr-006.html` has the history disclosure and
`.refdes/history/` gets events/objects).

## change-tracking.md

Checked clean. Modes against `model.ON_CHANGE_MODES`; `on_change_for`
precedence against `model.py:719`; missing-`reason` warning only for a
`fields:` override (`parse.py:1170`); body override handling against
`build.py:2625-2637`; history digest covers every field
(`history.semantic_payload`), so the documented timeline exception is
accurate; migration callers checked against
`lifecycle.diff_against`/`former_ids.propose`/`stamp`. "Not built yet"
remains true: no field-level diff/timeline/suspect-link command exists.

## checks.md

Changed: `value` may also be an inline calc span. Reproduced by defining
`Ispan := 0.7 A = 0.7 A` in a body and pointing `checks:` at it — the check
ran ("Ispan violates BND-IO-004"), not "no calc block defines". All other
claims verified: limit parse error and multi-bound note, worst-case and
`(nominal …)` failure lines, body-`yaml`-fence warning, `against:` composite
expansion, `check_severity` scalar/mapping refusals (three exact messages),
`component` mapping in `standards/hardware/v3/base.yaml:250`.

## coverage.md

Changed: `coverable_statuses:` is declared on `requirement` and inherited by
`bound`, not declared on both. Verified five stages, warning texts, blocked
chain text and one-root summary by running a scratch project; `items.json`
coverage shape matches; `hardware@3` `bound extends requirement` and the
three coverage verb pairs checked in `standards/hardware/v3/base.yaml` and
`build._coverage_for`. `stub-tests` run, rerun, and file shape confirmed.

## pages.md

Checked clean. Walked `pages.py`: slug/subfolder naming, `.`/`_` folder
skip, title/order/nav/board/workspace keys, `site.pages`/`site.nav` in
`configcheck.py:70-392`, unknown board/workspace tags as errors. Confirmed a
pages-only project writes only its pages, `index.md` becomes `index.html`,
and a page calc fence is not evaluated. Contents list threshold is
`page.html.j2:7` (`headings | length > 2`).

## output.md

Changed: per-board and per-workspace report lists (add `tree-<scope>`, state
the content gating; a registered board with only `includes:` members still
gets reports); site-nav scope wording; task pane now says `refdes serve`'s
preview is writable and links the browser-editor walkthrough; `items.json`
conditional keys now include `navis`, with a new `### navis` section.

Verified the rest: built a board project and listed `_site` (only
summary/coverage/document/tree scoped pages when the board has no log,
citations or parts); built a Navis project and read the real `navis`
payload; checked `items.json` keys and item shape against
`render.items_json`; theme/CSS, hover previews, margins, tree, vocabulary,
site nav and item-page sections against templates and `render.py`.

Findings, not changed (code, not docs): `refdes index --help` still lists
boards/workspaces/threads/captured as the conditional payload keys but not
`navis` (`cli.py` help text), while `render.items_json` does emit it.

## troubleshooting.md

Changed: documented the hardware@3 `text:` -> `body:` rename diagnostic that
the page's preceding sentence already pointed at. Reproduced exact text for
`requirement.text`, `bound.text`, and `test.method`. Everything else checked
against live output: `refdes.yaml` retired text, required fields
(`bound.limit`, `group`/`test`/`component` `title`, `log` `summary`,
requirement `body` warning), duplicate-key message, surrogate-key
malformed/changed/deleted/older-baseline texts, `keys restore` help,
check messages, inline-calc gate text, calc-fence messages, log seal
messages, citation page errors, and corrupt-store exit postures.

## upgrading.md

Changed: `refdes revise` (deprecated hidden alias) -> `refdes rename` in the
two breaking-change rows. Re-verified the rest of the page against
`refdes calc-rewrite --help`, `refdes standard upgrade --help`, the retired
`refdes.yaml` text, the colon-unit calc error, and the status/link warning;
`refdes init` on this branch writes `hardware@3` and `refdes-project.yaml`.

Could not verify: the page's "0.5.0's init wrote `refdes.yaml` with
`version: 2`" claim. The venv's `refdes` is an editable install of
the main checkout (0.5.0 label, current code), so I cannot run a real 0.5.0
`init` here; the statement matches
`changelog.d/hardware3-init-pins-v3.breaking.md`.

## Tests

`tests/test_docs_anchors.py`, `tests/test_docs_examples.py`,
`tests/test_crossplatform_lint.py`, `tests/test_standard_docs_complete.py`,
`tests/test_schema_doc_key.py`, `tests/test_linkify_anchors.py`,
`tests/test_render_calc_anchors.py`: 74 passed.
`python docs-site/gen_examples.py --check`: up to date.
Full suite run once before pushing. Review rounds were a single
self-review of the diff, which moved the serve sentence after the
read-only paragraph and tightened the per-board wording.
