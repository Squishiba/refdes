# design-status sweep

## Task

Third docs/design Status pass. #488 fixed W5b, the Navis panel plan and
`thread-workbench.md`. This pass re-reads every `docs/design/*.md` Status line
(and any implementation-status section) against main and edits only wording
that is provably stale. Plan bodies are not rewritten. `backlog.md` is
report-only by design.

## How I verified

- Base after `git fetch origin main && git merge --ff-only origin/main`:
  `e6e3eb82` (#490), no local commits first.
- Read the Status line/paragraph and implementation-status sections of all 28
  files. For every shipped/not-shipped claim I checked the tree, not memory:
  `grep` of `src/refdes/`, `editors/vscode/`, `items/`, and the repo root.
- `gh pr view` on every PR I cite: #384 (H9, MERGED 2026-10-29), #347
  (slice-2 hash, MERGED 2026-10-23).
- Webviews/V1/V2 in `editor-vscode-adapter.md`: no `webview` implementation
  string in `editors/vscode/*.js`; V1/V2 stay design only.
- Search: no item-search code in `src/` or `editors/` (`form-ingestion.md`
  likewise has no `ingest` code), so both stay proposed.
- Threads Phase 4b: still not landed — `refdes-schema.yaml` bridge is present
  and `items/decisions/dec-pwr-001-regulator-topology.md` still carries
  `type: decision`.
- H9 landed: `f460e46f` = #384; `lifecycle.py:1079` and `render.py:478`
  (`history_disclosure`) are in the tree.
- Slice 2 landed: `build.py` `HASH_FORMAT = 6`, `calc_hash_for` present; #347.

## Table

| file | status before | verdict | evidence |
| --- | --- | --- | --- |
| backlog.md | several implemented-things marked outstanding (H9 line 2977-2986; threads quote line 2984) | needs human (report only) | #384 landed H9; brief says do not edit backlog statuses |
| browser-editor.md | architecture decided; v1 shipped; Later remains | ok | `serve/edit.py` journal, pickers/upload/PDF code present; rendered-fragment half absent |
| calc-sources.md | Reviewed; landed sections | ok | `sources.py` readers incl. `page_candidates` |
| candidate-parts.md | shipped | ok | `blocks.py` `{{compare}}` :550; v3 `component.status` includes `rejected` :255 |
| composition.md | decided; engine landed | ok | `standards.py._expand_include` :429 |
| editor-image-upload.md | implemented | ok | `serve/upload.py`, `api.py` upload route |
| editor-pdf-picker.md | implemented P-A/B/C | ok | `sources.page_candidates` :1124/:1582 |
| editor-source-picker.md | implemented; one e2e row design only | ok | `sourcepicker.js` present; named e2e test absent as stated |
| editor-vscode-adapter.md | partially implemented; V1/V2 + webviews design only | ok | no webview code in `editors/vscode/` |
| extends.md | implemented | ok | `standards.py._resolve_extends` :635 |
| form-ingestion.md | proposed; no code | ok | no `ingest` matches in `src/` |
| index-blocks.md | implemented | ok | `blocks.py` index/cascade :918-922 |
| inline-calc-later.md | notes; live updates implemented | ok | #386-#388 in history |
| inline-calc.md | slice 2 would "land with this PR" | fixed | landed in #347; `HASH_FORMAT = 6` |
| item-search-hover.md | proposed; no search code | ok | no search implementation found |
| keys.md | fully implemented | ok | `keys.py`, `adopt.py` |
| lifecycle.md | implemented | ok | `cli.py:cmd_revision/cmd_release` |
| living-notes.md | says H9 not landed | fixed | H9 = #384 |
| living-notes-plan.md | implemented H1–H9 | ok | H9 code in `lifecycle.py`/`render.py` |
| named-calc-blocks.md | all five phases landed | ok | `{{calcblock}}` `blocks.py:809` |
| navis-vscode-panel-plan.md | implemented in 0.2.0 | ok | fixed by #488; `package.json` 0.2.0 |
| seal-marker-identity.md | proposed; no `deleted:` namespace | ok | no `deleted:` in `history.py` |
| stale-arithmetic-signal.md | implemented | ok | `lifecycle._stale_arithmetic` :1179 |
| standard-library.md | implemented | ok | `standards.py` bundles |
| threads.md | H9 and Phase 4b remain later | fixed | H9 #384 landed; Phase 4b still not landed |
| thread-workbench.md | W5a/W5b landed | ok | fixed by #488 |
| thread-workbench-w5b-plan.md | implemented | ok | fixed by #488 |
| vocabulary-review.md | findings; §1.7 quoted superseded plan header | fixed | plan now H1–H9; H9 #384 |

## Edits

- `living-notes.md`, `threads.md`: H9 landed, #384.
- `inline-calc.md`: slice-2 work landed in #347.
- `vocabulary-review.md`: §1.7 quote updated to match the plan's H1–H9 header.
- `changelog.d/design-status-sweep.fixed.md` added.

## Left alone / needs a human

- `docs/design/backlog.md` still says living-notes H9 "has not landed" and
  quotes threads.md's pre-#384 status (lines 2977-2986). Report-only per the
  brief.
- `threads.md`'s Phase 4b panel is genuinely still unbuilt, so its remaining
  "later work" wording was kept.

## Checks

- `tests/test_docs_anchors.py`, `tests/test_crossplatform_lint.py`.
- `python docs-site/gen_examples.py --check`.
- Full suite once before pushing.
