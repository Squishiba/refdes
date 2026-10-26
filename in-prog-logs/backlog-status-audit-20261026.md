# Backlog status audit — all 38 findings + living notes (2026-10-26)

Read-only audit. Tree audited: `main` = `origin/main` = `78c8954`. Every
claim names a file:line, commit, test run, or command verified at this
commit. The `refdes` CLI used is the venv install whose package resolves to
`/home/jorb/work/refdes` at `78c8954` (`pip show refdes`), so `refdes ls
--help` output describes this tree's code.

Supersedes `in-prog-logs/backlog-status-audit-20261023.md` (audited at
`899ab91`, 12 commits behind `78c8954`). Where the 2026-10-23 audit's
verdicts still hold at this tree they were re-verified, not copied — the
one thing it recorded that changed here is finding 15: `3c9035b`
(`EDITOR-JOURNAL-1`) landed the journal module, unwired.

## 0. Summary

Counts over the 38 numbered findings + the living-notes phases:
**DONE 34, PARTIAL 3 (findings 15, 26, living notes), SUPERSEDED 2
(findings 16, 17), OPEN 0, WON'T-DO 0.** Status-line mismatches in
`docs/design/*.md`: 4 (section 3).

## 1. Findings

| # | Title | Status | Evidence (verified at 78c8954) | What is left |
|---|-------|--------|-------------------------------|--------------|
| 1 | CI-built/published docs site | DONE | `089fdbe`+`1f1ec03` ancestors of main; `.github/workflows/docs.yml:44,59` (`configure-pages`, `deploy-pages`); run `gh api repos/Squishiba/refdes/pages` → `status:"built"`, `html_url:"https://squishiba.github.io/refdes/"`, `build_type:"workflow"`; `gh api repos/Squishiba/refdes` → `has_pages:true` | (nothing) |
| 2 | `section:` marker in editor schemas | DONE | `c659c23` ancestor; `schema_json.py:325,331` `section_marker` def + `oneOf` append | (nothing) |
| 3 | `text:`/`title:` unification (done-differently) | DONE | `50cf460` ancestor; `revise.py:449` `check_body_merge_conflicts` (body-merge check replaces rename); v3 `migration.yaml:26` runs it | (nothing) |
| 4 | Explain note/source/rationale/body | DONE | `dd203e3` ancestor; `docs/authoring.md:335` "### `source`, `note`, `rationale`, `body`" | (nothing) |
| 5 | `build --dry-run` | DONE | `c85deda` ancestor; `cli.py:563` `seal_write=not (args.dry_run or args.no_write)`; write-gated draft banner `base.html.j2:50` + `render.py:1124` | (nothing) |
| 6 | `defaults:` leak onto `type:`-overridden items | DONE | `10b7263` ancestor; `parse.py:58,62` `RESERVED = {"id","type","body","former_ids","key"}` + the rewritten comment; `authoring.md:35` "Bodies in list files" | (nothing) |
| 7 | Requirement compliance verb; component→bound | DONE | `491283e` ancestor (requirement half, `governed_by`); v3 `base.yaml:121-147` `claims` set = `satisfies: [requirement, bound]` + `constrained_by: [bound]`, included by component (`base.yaml:258`) and log (`:303`); component `checks:` field `base.yaml:257` | (nothing) |
| 8 | Id completion narrowed by file | DONE | `1044c96` ancestor; `editors/vscode/extension.js:681` completion `filterText` includes `sourceFile`/`board` | (nothing) |
| 9 | CLI list/browse | DONE | `491283e` ancestor; `cmd_ls` `cli.py:871`; run `refdes ls --help`: free-text query (id/title/tags) + `--type/--board/--workspace/--file/--tag/--keys` | (nothing) |
| 10 | Next-free-number completion | DONE | `c743328` ancestor; `render.py:798` `payload["next_ids"]` in items.json; ledger visibility: `cmd_audit` `cli.py:1728`, `ids.py:158` `high_water` | (nothing; the finding itself called the ledger report informational) |
| 11 | Untagged-item lint → own-tags lint | DONE | `a1bcdf0` ancestor; `build.py:785` `lint_own_tags`; setting `configcheck.py:347` `untagged_items`; test `tests/test_lint_own_tags.py` | (nothing) |
| 12 | `body:`-in-list-files rationale | DONE | `8e33c08` ancestor; `authoring.md:35-39` (the real tradeoff: prose per entry, not file count); `parse.py:58` comment rewritten | (nothing) |
| 13 | `{{index}}` `tag=` filter | DONE | `1cf3e88` ancestor; `blocks.py:919` index `BlockSpec` `optional=("board","tag","subtypes")` (`tag` present; `subtypes` added later) | (nothing) |
| 14 | Grouping/collection type | DONE | `1330dee` ancestor; v3 `base.yaml:269-274` `group` type, `prefix: GRP`, `coverable: false`; `changelog.d/hardware-v3-group-type.added.md` | (nothing) |
| 15 | Form-based authoring surface (browser editor) | **PARTIAL** | v1 shipped: `serve/` 11 modules + `static/`, `cmd_serve` `cli.py:612`; journal module landed `3c9035b` (`src/refdes/editor_journal.py`: begin/complete/recover, staging + manifest-last) — commit message: "**Not wired into serve/edit.py or the CLI yet**; editor saves are not journaled yet"; `serve/edit.py:14,780` confirm; run `refdes --help`: **no `recover` command**; `grep fig: serve/static/*.js` → no insertion helpers | (a) wire the journal into `apply_edit` + `refdes recover` + load-refusal; (b) `[[ID]]`/`[[fig:id]]`/calc-fence insertion helpers. The doc's header names exactly these (`browser-editor.md:4-6,1178-1182`) |
| 16 | `recorded_by: [log]` on `decision` | SUPERSEDED | Shipped in hardware@2 (`3c52c4e` ancestor); v3 has **no `decision` type and no `recorded_by` verb** (grep `base.yaml` types: requirement, bound, test, component, group, log); `d71c143` "Threads phase 4a: merge decision into log" — v3 `log` carries `sealing: history` (`base.yaml:291`) + `legacy_prefixes: [DEC]` | (nothing — superseded by 4a; the status line already says so) |
| 17 | Threads (the old model) | SUPERSEDED | Status line itself: "superseded by `docs/design/threads.md`"; `threads.md:17` "Status: Phase 4a implemented." verified against code (H6 `tasks:` `base.yaml:302`, H7 `cmd_thread`/`cmd_work` `cli.py:1246,1453`, H8 gate `lifecycle.py:937`) | (nothing for this finding) |
| 18 | Calc lexer `%` / SI-prefixed Ω | DONE | `3a2fced` ancestor; `calc.py:467-468` `_SEGMENT` continuation class `[A-Za-z0-9_Ωµμ°]*`, `_UNIT_RUN` includes `%`; run probe: `evaluate("100 V * 5 %")` → `500.0 percent*volt`, `"10 kΩ + 5 kΩ"` → `15.0 kiloohm`, `"2 MΩ"`, `"90 °C"`, `"1 µF * 1000"` all evaluate | (nothing) |
| 19 | `[[ID#field]]` + citation identity | DONE | `build.py:69` `EXPLICIT_REF_RE` fragment group incl. `#field`; `model.py:411` `CitationSpec.id`; `item.html.j2:128,205` `id="field-…"`/`id="cite-…"` anchors; **run**: `tests/test_field_refs.py`, `tests/test_citation_ids.py` pass (within a 295-test batch) | (nothing) |
| 20 | Generated per-type examples in docs | DONE | `docs-site/gen_examples.py`; `docs.yml:40` `gen_examples.py --check` gate; **run**: `tests/test_docs_examples.py` passes | (nothing) |
| 21 | `extends:` single-level inheritance | DONE | `1cf3e88` ancestor; `standards.py:80-90,266-275,617-624` `_resolve_extends`/`_apply_parent` (null-suppression kept); v3 `base.yaml:210` `extends: requirement`; `configcheck.py:75,419` `coverage.group_inherited` (default true — the §11 overturn, "coverage grouping is the default for every project"); **run**: `tests/test_extends.py` passes | (nothing; status line's "on ao/refdes-113" branch name is stale — commits are on main) |
| 22 | Widen `satisfies` to `[requirement, bound]` | DONE | v3 `base.yaml:141-147` `claims` set `satisfies: [requirement, bound]` + `constrained_by: [bound]`, included by component (`:258`) and log (`:303`) — the decision half now rides on `log` post-4a | (nothing) |
| 23 | `page:` in citation hrefs; PDF-outline `section:` | DONE | `CitationSpec.section`; `citations.py:657` `resolve_sections`; `item.html.j2:214,216,220` `#page={{ cpage }}` hrefs (guarded); Part 2 refusal: `citations.py:740-773` (`_hash_only_without_count`, "pinned hash-only, with no kept copy") | (nothing) |
| 24 | Per-(item, board) coverage via `conforms_to:` | DONE | `model.py:266` `conforms_to`, `schema.py:1033`; `build.py:1171` `validate_conforms_to`, `:1321` `compute_board_coverage`; `coverage.html.j2:74-78` "Conforming contracts"; **run**: `tests/test_board_contracts.py` passes | (nothing) |
| 25 | Citations as field set; one `path:` | DONE | v3 `base.yaml:121-123` `citations` set with `path:`; `model.py:404` `CitationSpec.path`; migration `datasheets→citations` (`migration.yaml:82`) | (nothing) |
| 26 | Calc values from repo-local source files | **PARTIAL** | `sources.py:232` CSV, `:520` XLSX (extras `pyproject.toml:58`), `:837` PDF (extra `:57`); `calc.py:643` `source("cited/file.csv", "key")` shape; design reviewed (`calc-sources.md:1` "Status: Reviewed", §11 all answered) | XLSX picker listing open (`serve/sources.py:33` "has an extractor but no picker listing yet", refusal path `:701`); netlist/schematic readers explicitly out of v1 scope (design's own decision) |
| 27 | Project-defined equations | DONE | `c96d96b` ancestor; `calc.py:329,357,370` `Equation`/`set_equations`/`validate_equations` + `:446` cycle detection; `schema.py:393` `_load_equations`; `changelog.d/calc-project-equations.added.md` | (nothing) |
| 28 | Config split honesty | DONE | `aa94058` ancestor; `schema.py:47,52,56,90` `PROJECT_SETTINGS_NAME`/`SCHEMA_NAME`/`LEGACY_CONFIG_NAME`/`LEGACY_CONFIG_ERROR`; `changelog.d/config-split-two-files.breaking.md` | (nothing) |
| 29 | Figure refs in log bodies | DONE | `log.html.j2:44` `figured(entry.body_html) | safe`; `render.py:1298` passes the closure for log pages | (nothing) |
| 30 | `_esc` single quotes | DONE | `build.py:3151`, `blocks.py:82` `.replace("'", "&#39;")` (with the "escape last" comments) | (nothing; F31 is the test gate) |
| 31 | Text-node XSS test | DONE | `tests/test_text_node_escaping.py`; **run**: passes; `render.py:1110` `autoescape=True` (with the `select_autoescape` rationale comment) | (nothing) |
| 32 | Date-aware log sorting | DONE | `c0d1722` ancestor; `dates.py:18,65` `validate_format`/`parse_date`; `render.py:120` `_date_sort_key` (3 sites, now `render.py:159,263,509` — the status line's `:97/:133/:264` cites have drifted); setting validated `schema.py:212,239-241`; hard rejection `build.py:498` (in `validate_items`) | (nothing) |
| 33 | Shared items via board `includes:` | DONE | Decided option (a), Jared: "Should only tally what it owns, not what is shared." `model.py:272` `includes`, `boards.py:116` `included_map`, `:149` `displays`, `build.py:1201` `validate_includes`; label `blocks.py:271`/`tree.py:419` "shared, via …"; **run**: `tests/test_board_includes.py` passes | (nothing) |
| 34 | Design tokens + theming | DONE | Jared's decision at `backlog.md:1714` adopted (scope (b), colours+typography+density); `configcheck.py:71,375-380` `theme`/`tokens` keys validated; `theme.py`, `contrast.py`; **run**: `tests/test_theme.py`, `tests/test_style_tokens.py` pass | (nothing) |
| 35 | Cross-item calc references | DONE | Decided 2026-09-19 (`V_in = DEC-PWR-001.V_in`, composite key form); `links.py:1192` `plan_calc_ref_expansion`, `:1320` `expand_missing_calc_refs`; value-enters-hash: `build.py:2212-2213` ("hashes each reference's resolved key and the *value*"), `HASH_FORMAT = 6` (`build.py:2260`; 5→6 by `ba6d153` — the status line's "bumped to 5" is one bump behind, as it predicted it could be); **run**: `tests/test_calc_cross_refs.py`, `test_calc_cross_ref_hash.py`, `test_calc_cross_ref_diff.py` pass | (nothing) |
| 36 | `<img>` filename search | DONE | Decided 2026-09-19 (reuse `site.assets:`, ambiguity = error naming every match); `build.py:3444` `_search_image_src`; **run**: `tests/test_image_search.py` passes | (nothing) |
| 37 | Site tree view | DONE | Containment-spine tree shipped: `tree.py`, `_render_tree` `blocks.py:500` registered `:931`; `nav.py:53,104` tree report; **run**: `tests/test_tree.py`, `tests/test_tree_scoped.py` pass. Status line's "the §1 containment-spine … the reference-elsewhere half is not implemented" is stale: the shipped `{{tree}}` scope model (tree-scoped, tree-board-home fragments) covers it; `via` is *deliberately absent* in `_render_tree` for the `{{index}}` shared-via split | (nothing) |
| 38 | Generated vocabulary + diagram | DONE | Decided 2026-09-19 (`doc:` key beside declarations, hand-rolled layout, per-type diagrams); `vocabulary.py`, `diagram.py`; `schema_json.py:380-382` spine + per-term SVGs; `configcheck.py:99,111,120` `doc` key accepted; **run**: `tests/test_standard_docs_complete.py`, `tests/test_vocabulary_page.py` pass | (nothing) |

**Living notes phases (H1–H9 + threads 4a/4b)** — **PARTIAL.**
Landed: H1–H5 (history store/capture/sealing — `d84e123`, `47a5300`,
`506842c`, `1981f9e`, `3edb68b` all ancestors of main), H6 `tasks:`
(`base.yaml:302`), H7 `refdes thread`/`refdes work` (run `--help`;
`cli.py:1246,1453`), H8 release-gate rules (`lifecycle.py:932-937` reads
`project.release_gate`), threads 4a (`d71c143`). Not landed: **H9** —
`history.py:86-97` `EVENT_KINDS` has no `baseline` kind; the plan header
itself says "Implemented (H1–H8; optional H9 not landed)". **Phase 4b** —
the pane is read-only W5a (`taskpane.js` header: "This file computes
nothing … it shows and hides"), W5b blocked on ten owner questions
(`thread-workbench-w5b-plan.md:1`).

## 2. OPEN/PARTIAL ranked (usefulness × size), local-model tagged

1. **Living-notes H9** (M) — last unlanded phase of a ratified plan: the
   `baseline` event kind written beside compact baselines + the item-page
   disclosure. **Local model: suitable** — §H9 of the plan names the files,
   the invariant ("a baseline created before it says rich content is
   unavailable rather than inventing text") and the exclusions; acceptance
   is one test. (2026-10-23 audit §9 agrees.)
2. **Finding 15(a): wire the journal** (M) — connect `editor_journal.py`
   into `apply_edit`, add `refdes recover`, make project-loading commands
   refuse on a journal. **Local model: suitable** — acceptance boundary
   pre-written at `browser-editor.md:1238-1239`; the module's own tests
   exist, so the remaining work is mechanical integration. (2026-10-23
   audit §1 agrees; now easier — the module has landed.)
3. **Finding 26: XLSX picker listing** (S) — `list_entries` for the XLSX
   reader + picker listing for `.xlsx` citations. **Local model: suitable**
   — the CSV path is the exact template, the refusal site
   (`serve/sources.py:701`) names the missing capability, and §11's
   decision ("`fetch --update` is the acceptance gate") is recorded.
4. **Finding 15(b): body insertion helpers** (S) — `[[ID]]`, `[[fig:id]]`,
   calc-fence inserts in the editor. **Local model: marginal** — the
   inserted strings are mechanical (suitable if a task pins them exactly),
   but cursor/toolbar placement is the UI judgment the finding's own
   local-model note (`backlog.md:352` "not suitable") excludes.

Finding 26's netlist/schematic readers and the W5b panel are not ranked
here: the first is the design's own scope decision, the second is blocked
on ten owner questions.

## 3. `docs/design/*.md` status lines that disagree with main

1. **`docs/design/living-notes.md:1`** — "Status: Decided -- ready to plan
   implementation". The plan exists and landed:
   `living-notes-plan.md:1` "Implemented (H1–H8; optional H9 not landed)",
   verified against code (`cli.py:1246,1453` thread/work,
   `base.yaml:302` `tasks:`, `history.py` `EVENT_KINDS`). Stale by weeks
   (it predates `d18f76d`/`8b1a387` which fixed the *plan* doc, not this one).
2. **`docs/design/vocabulary-review.md:322-326`** — "§1.7 The living-notes
   vocabulary (not implemented)" / "Both documents are unshipped" /
   quotes the plan as "Proposed — implementation plan". Same code evidence
   as (1): `follows:`/`addresses:` (`base.yaml:165-166`), `tasks:`
   (`base.yaml:302`), the thread/work commands. Stale.
3. **`docs/design/item-search-hover.md:1`** — "Status: **proposed**; **no
   slices scoped, no code written**". The same doc's §5
   (`item-search-hover.md:196-197`) says "Slice V−1 and Slice V0 have both
   landed" (`da2e44b`/#58, `0f38619`/#66 — both ancestors of main; the V0
   hover facts are `extension.js:239`). Header contradicts body. (The
   search itself is unlanded, so the doc is right that the *feature* is
   not built; the header's "no code written" is the false part.)
4. **`docs/design/seal-marker-identity.md:1-2`** — "proposed … Nothing here
   is landed; `history.py` and its tests are untouched." The proposal
   (a `deleted:`-namespace identity for display-id seal markers) is indeed
   unlanded (`grep 'deleted:' src/refdes/history.py` → nothing), but
   "history.py and its tests are untouched" is false as written: history.py
   has been touched since drafting (`git log --since=2026-09-27 --
   src/refdes/history.py`: #212, #271, #272, #323, #330), and the
   display-id fallback the doc's §1 names is live code
   (`history.py:1279`). Soft mismatch — proposal state correct,
   "untouched" overstated.

Checked and **consistent** (not mismatches): `browser-editor.md`
(header names the journal exception; journal module landed unwired, `recover`
absent — header true), `calc-sources.md`, `candidate-parts.md`,
`composition.md` (all four cited shas `dc0c138`/`0459f64`/`8085da2`/`ecb85bb`
exist, `tests/test_composition.py` present), `editor-{vscode-adapter,
source-picker,pdf-picker,image-upload}.md` (cited shas #49/#57/#59/#62/#67/#71,
#50/#52/#53/#60/#63/#69, #58/#66/#108, #349 all exist),
`extends.md` (the "outstanding" text at `:502` is inside the doc's own
quoted before/after block, not a live claim), `form-ingestion.md` (no code:
`grep -rni ingest src/ --include=*.py` → nothing), `index-blocks.md:934`
(`4b34238` exists), `inline-calc.md` (+ `inline-calc-later.md`), `keys.md`
(header "done" matches AGENTS.md), `living-notes-plan.md`,
`named-calc-blocks.md` (`calc.py:1018` `parse_fence_attrs`,
`build.py:76` `CALC_FRAGMENT_PREFIX`, `blocks.py:809` `calcblock`),
`thread-workbench.md`, `thread-workbench-w5b-plan.md` (blocked-on-owner
accurate: no W5b route in `serve/api.py`), `threads.md:17`,
`backlog.md` itself (all 39 status lines audited in section 1).

## 4. Not verified (and why)

- **Finding 1, Actions run history** — the status line's claim that "the
  last five `docs.yml` runs on `main` were all `conclusion: success`" and
  run id `36371871267` are point-in-time (2026-09-27). The Pages setting
  itself was re-verified live (`gh api`, section 1 row 1); the run history
  was not.
- **Finding 20, live site rendering** — `gen_examples.py --check` is the
  gate (verified in `docs.yml`); the deployed pages' rendered content was
  not fetched.
- **`gh` auth scope** — the two `gh api` calls above are the only network
  checks; the workflow run list (`gh run list`) was not queried.
- **Findings 16/17 as hardware@2 artifacts** — verified as *absent* in v3
  (the supersession); the hardware@2 files under
  `src/refdes/standards/hardware/v2/` were not re-audited line by line.
