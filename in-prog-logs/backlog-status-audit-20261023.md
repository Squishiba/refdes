# Backlog status audit — which decided items are not yet implemented (2026-10-23)

Read-only audit. Tree audited: `899ab91` (= `origin/main` at audit time;
branch `audit-backlog-status-20261023`). Every claim below names the file,
command, or commit checked at that commit. The `refdes` CLI used is the
editable install whose `.pth` points at `/home/jorb/work/refdes/src`, a
checkout of the same `899ab91` — verified with
`cat .../site-packages/__editable__.refdes-0.5.0.pth` and
`git -C /home/jorb/work/refdes log -1` — so `refdes --help` output
describes this tree's code.

Items audited: the ten `Status:` lines in `docs/design/backlog.md` at
approx. lines 329, 581, 1431, 1714, 2008, 2264, 2565, 2582, 2919, 2976
(lines 2565 and 2582 are both in finding 37, so ten lines = nine findings),
plus the Status lines of `docs/design/{form-ingestion,item-search-hover,
inline-calc-later,thread-workbench-w5b-plan,candidate-parts,
named-calc-blocks,stale-arithmetic-signal}.md`. 16 items total.

## 0. Summary

| # | Item | Verdict | Size | Local-model suitable |
|---|------|---------|------|----------------------|
| 1 | backlog finding 15 — browser editor v1 (form surface) | PARTIAL | M (journal) + S (helpers) | yes (journal), marginal (helpers) |
| 2 | backlog finding 21 — `extends:` type inheritance | DONE | — | — |
| 3 | backlog finding 33 — shared items via board `includes:` | DONE | — | — |
| 4 | backlog finding 34 — design tokens + site theming | DONE | — | — |
| 5 | backlog finding 35 — cross-item calc references | DONE | — | — |
| 6 | backlog finding 36 — `<img>` filename search + freeze | DONE | — | — |
| 7 | backlog finding 37 — site tree view | DONE | — | — |
| 8 | backlog finding 38 — generated vocabulary + diagram | DONE | — | — |
| 9 | backlog — living notes phases | PARTIAL | M (H9) | yes |
| 10 | form-ingestion.md | BLOCKED ON A DECISION | — | — |
| 11 | item-search-hover.md | BLOCKED ON A DECISION | — | — |
| 12 | inline-calc-later.md | NOT STARTED (by design) | L | no |
| 13 | thread-workbench-w5b-plan.md | BLOCKED ON A DECISION | — | — |
| 14 | candidate-parts.md | DONE | — | — |
| 15 | named-calc-blocks.md | DONE | — | — |
| 16 | stale-arithmetic-signal.md | DONE | — | — |

Counts: DONE 10, PARTIAL 2, NOT STARTED 1, BLOCKED ON A DECISION 3.

Queueable work in this audit's scope is exactly three things: the browser
editor's transaction journal + `refdes recover` (item 1a), the body
insertion helpers (item 1b), and living-notes H9 (item 9). Everything else
is done in code, parked behind an owner decision, or explicitly not
decided.

"Pending release" (items 6, 7, 8) is a release-process state, not
unimplemented work: the code, tests, and `changelog.d/` fragments are all
in the tree; `release.py` folds fragments into `CHANGELOG.md` on release.

## 1. backlog.md ~329 — finding 15: form-based authoring surface (browser editor)

**Decided:** a VS Code–proposed webview form became, by
`docs/design/browser-editor.md` option B, a local `refdes serve` with a
separate `/edit/` application over the plain files; architecture and v1
scope decided 2026-09-16. The Status line itself says "architecture
decided … shipped since, and still moving", with "the remaining v1 slices"
outstanding.

**Evidence.** `refdes --help` lists `serve`. `src/refdes/serve/` exists
with 11 files (`api.py edit.py filters.py preview.py resolution.py
security.py server.py sources.py state.py upload.py __init__.py`) over
`static/` (17 JS/CSS/HTML files incl. `editor.js`, `create.js`,
`filters.js`, `links.js`, `images.js`, `sourcepicker.js`, `drafts.js`).
`cmd_serve` registered (`src/refdes/cli.py:2956`). The doc's own header
(`browser-editor.md:1-7`) names what is not shipped: (a) "**The
transaction journal of item 9 is the known exception**: `serve/edit.py`
implements the design's transaction model 'minus the journal, which is a
later slice'" — confirmed: `serve/edit.py:14` carries that comment,
`:772` says "Bytes restored from memory, not a transaction journal", and
`refdes --help` has **no `recover` subcommand**; (b) v1 checklist item 5
(`browser-editor.md:1178-1182`) marks the image picker shipped and states
"the `[[ID]]`, `[[fig:id]]`, and calc-fence insertion helpers are still
outstanding" — confirmed: `serve/static/*.js` contains insertion only via
the image picker and source picker (`editor.js:102,123`); no `fig:` string
appears in any `serve/static/*.js`.

**Verdict: PARTIAL.** v1 shipped except (1a) the transaction journal +
`refdes recover`, and (1b) the `[[ID]]`/`[[fig:id]]`/calc-fence insertion
helpers. The design's "Remaining work is the 'Later' list" (header) —
that list is explicitly not v1.

**Size.** 1a: M — `serve/edit.py` journal write path, new `recover` CLI
command, load-refusal in project-loading commands, tests. 1b: S — one JS
file + a Python-side test of inserted text per helper.

**Local model.** 1a: **yes** — the acceptance boundary is already written
in `browser-editor.md:1238-1239`: "Killing the process between two
replacements leaves a visible `.refdes/editor-transaction/`; every
project-loading command refuses until `refdes recover` restores it."
Mechanical, testable, contract-complete. 1b: **marginal** — the inserted
text is mechanical, but cursor/toolbar placement is the UI judgment this
file's own finding 15 note excludes from small-model work; suitable only
if the task pins exact inserted strings and the DOM contract.

**First tests.** 1a: crash-simulation test — drive `apply_edit` to write
the first replacement, kill between replacements (test hook), then assert
`.refdes/editor-transaction/` exists and `refdes check` exits nonzero
naming it, and passes only after `refdes recover`. 1b: a serve-statics
test that invoking the `[[ID]]` insert helper on a fixture body yields
exactly `[[DEC-PWR-001]]` at the recorded cursor position.

## 2. backlog.md ~581 — finding 21: `extends:` single-level type inheritance

**Decided:** universal (Liskov) substitution, no opt-in marker, single
level, `bound extends requirement` in hardware@3 (hash-neutral), coverage
grouping default `true` (overturning the spec's own recommendation).

**Evidence.** Engine: `ab55e27` (phase 1), `37071ea` (phase 2 consumers +
`coverage.group_inherited`), `b176b25` (phases 3–4, `bound extends
requirement` + resolved-schema oracle), `7018af0` (overlay
`links: {verb: null}` follow-on, §12) — all on `main` (`git log
--oneline --grep="extends.md"`). Code: `TypeSpec.extends`
(`src/refdes/model.py:316`), `subtype_map`/`is_subtype`
(`model.py:375-387`), ALLOW-side widening `with_subtypes`
(`src/refdes/build.py:1010-1011`), coverage grouping
(`src/refdes/render.py:178-182`), `group_inherited: bool = True` default
(`model.py:973`), recognised key (`src/refdes/configcheck.py:87`), and
`extends: requirement` at `src/refdes/standards/hardware/v3/base.yaml:210`.
Tests: `tests/test_extends.py`, 53 tests, 764 lines.
`_check_overlay_link_nulls` is gone (grep: no match in `src/`).

**Verdict: DONE.** The status line's "implemented on ao/refdes-113" is
stale as a branch name — the commits are in `main`'s history.

## 3. backlog.md ~1431 — finding 33: shared items on board pages via `includes:`

**Decided:** option (a) display-only — boards name groups via
`includes:` (groups only); shared items are displayed labelled "shared,
via GRP-X" and never tallied; display/count separation via two
predicates.

**Evidence.** `includes: list[str]` on the board spec
(`src/refdes/model.py:272` — the entry's ":174" line cite has shifted);
`included_map()` `src/refdes/boards.py:116` and `displays()`
`boards.py:149` exist exactly as the entry cites; the label is
`src/refdes/blocks.py:271` and `src/refdes/tree.py:419` ("shared, via
…"); `shared_via` flows through `render.py:1296+`; tests
`tests/test_board_includes.py`; fragment
`changelog.d/board-includes.added.md`.

**Verdict: DONE**, "with it the asymmetry this entry argued for", as the
entry itself says.

## 4. backlog.md ~1714 — finding 34: design tokens, `site: theme:`, `site: tokens:`

**Decided:** token-layer refactor as a provable no-op first, then named
built-in themes, token overrides merged over the theme, name/completeness
validation with did-you-mean, contrast checking (error built-ins / warning
project themes); refusals as listed.

**Evidence.** No-op proof gate: `tests/test_style_tokens.py` (exists).
Theme machinery: `src/refdes/theme.py`, `src/refdes/contrast.py`
(both exist); `site:` allowlist contains `theme`, `tokens`
(`src/refdes/configcheck.py:71`), validated at `configcheck.py:375-385`
(`validate_token_overrides`). Tests: `tests/test_theme.py`,
`tests/test_themes_page.py`.

**Verdict: DONE**, "in the three steps this section ordered", as the entry
says.

## 5. backlog.md ~2008 — finding 35: cross-item calc references

**Decided:** `V_in = DEC-PWR-001.V_in` stored as a `DISPLAY-ID@key`
composite; any named value referenceable (no `exports:`); loud error at
the referring site; resolved value enters the referring item's content
hash with a coordinated `HASH_FORMAT` bump.

**Evidence.** The four cited commits all exist on `main`: `cabd9e1`,
`3078c45`, `89c6383`, `1dbfd77` (`git log -1` each). Composite reference
form documented at `src/refdes/calc.py:1108-1111`;
`build.HASH_FORMAT` is 5, as the entry says it was bumped from 4
(`src/refdes/lifecycle.py:335`). Tests: `tests/test_calc_cross_refs.py`,
`tests/test_calc_cross_ref_hash.py`, `tests/test_calc_cross_ref_diff.py`.
Fragments `changelog.d/calc-cross-item-refs.added.md` and
`…-refs-hash.changed.md`.

**Verdict: DONE.**

## 6. backlog.md ~2264 — finding 36: `<img src>` filename search + freeze

**Decided:** bare leaf filenames resolve against `site.assets:`
directories (no new key); ambiguity = error naming every match, no
tie-breaker; writable load freezes a unique hit to a project-root-anchored
path; `--no-write` and non-unique cases keep source spelling.

**Evidence.** `e8b4d34` on `main`. `_search_image_src`
(`src/refdes/build.py:3108`), pure-search half separated
(`build.py:3093`), error names `project.asset_dirs` searched
(`build.py:3145`), relative-wins rule at `build.py:3181`. Freeze:
`src/refdes/image_freeze.py` exists. Tests: `tests/test_image_search.py`.
Fragment `changelog.d/image-search-path.added.md` (§4 freeze half is the
"pending release" part).

**Verdict: DONE** (shipped; release pending, which is process state).

## 7. backlog.md ~2565 and ~2582 — finding 37: site tree view

**Decided:** containment-spine tree (workspace → board → group → item),
expand-once + reference-elsewhere, `Project-wide` bucket with a mechanical
totality test, scoped `tree-<board>.html`/`tree-<workspace>.html`,
`{{tree}}` with `board`/`workspace`/`depth`, no JavaScript.

**Evidence.** Both cited chunks on `main`: `b33da1b`, `91ea881`.
`src/refdes/tree.py`, `tree.html.j2`; `_render_tree`
(`src/refdes/blocks.py:500`) whose docstring records
`via` as *deliberately absent* — matching the status line's "one v1-scope
item was deliberately not shipped"; `REPORT_LABELS` carries
`"tree": "Tree"` (`src/refdes/nav.py:53`) and scoped names append
(`nav.py:104`). Tests: `tests/test_tree.py`, `tests/test_tree_scoped.py`.
Fragments `changelog.d/tree-view.added.md`, `tree-scoped.added.md`.

**Verdict: DONE** (both Status lines; release pending).

## 8. backlog.md ~2919 — finding 38: generated vocabulary reference + diagram

**Decided:** `doc:` key beside each declaration; hand-rolled layout, no
graph library; both surfaces from one generator; generated SVG replaces
Mermaid in `refdes schema --graph`; per-type diagrams after the whole-graph
diagram was rejected.

**Evidence.** Cited commits all on `main`: `9c48e99`, `7d1a2c6`,
`2565387`, `09baee8`, `4c1cd32`. `doc` in the type/field/link-type/sets
key sets (`src/refdes/configcheck.py:99,111,120`) plus validation
(`:558`). `src/refdes/vocabulary.py`, `src/refdes/diagram.py`;
`schema_json.py:380-382` renders `render_spine_svg` + per-term SVGs, and
`refdes schema --help` (run) describes `--graph` as "one connection
diagram per type, each a standalone SVG document … drawn here rather than
handed to Mermaid or graphviz". `docs/vocabulary.md` exists, generated by
`docs-site/gen_examples.py` (its header, lines 7-9). Gates:
`tests/test_standard_docs_complete.py`, `tests/test_vocabulary_page.py`.
Fragments `vocabulary-page.added.md`, `vocabulary-diagram.added.md`,
`schema-doc-key.added.md`.

**Verdict: DONE** (release pending).

## 9. backlog.md ~2976 — living notes, history and task lists (phases)

**Decided:** ratified plan `living-notes-plan.md` (questions ratified
2026-09-19 in `cb9180d`) landing phases H1–H9 with threads 4a/4b. Status
line itself: "landing in phases … not done".

**Evidence — landed:** H1 `d84e123`, H2 `47a5300`, H3 `506842c`, H4
`1981f9e` (`git log -1` each); H5 history-backed sealing = #157
(`3edb68b`, found via `git log --grep="H5"`); H6 `tasks:` on the merged
`log` (`src/refdes/standards/hardware/v3/base.yaml:302`, `type: tasks`,
hash-excluded); H7 `refdes thread`/`refdes work` (in `refdes --help`,
run) + index `threads` projection; H8 gate rules (`project.release_gate`
read at `src/refdes/lifecycle.py:925-930`). Threads 4a = `d71c143`
("Threads phase 4a: merge decision into log (#176)").

**Evidence — not landed:** H9: `living-notes-plan.md` header reads
"Implemented (H1–H8; optional H9 not landed)"; §H9 (plan:536) adds
`baseline` event kinds + item-page history disclosure. Code:
`src/refdes/history.py` `EVENT_KINDS` (lines 83-95) contains
`followed, followed-corrected, captured, revision, release, redaction,
legacy-seal, migrated-current` — **no `baseline` kind** (the `revision`/
`release` kinds are H4-era capture events, not the §H9 baseline snapshots
"written beside the compact baseline" by `lifecycle.stamp()`). Threads 4b:
`docs/design/threads.md` header (read) says "Phase 4a implemented. H6, H7
and H8 have since landed; H9 and the Phase 4b thread panel remain later
work"; the shipped pane is read-only W5a (`7c72311`;
`src/refdes/templates/taskpane/taskpane.js` header: "It fetches nothing
and writes nothing").

**Verdict: PARTIAL.** H1–H8 + 4a done; H9 not landed; Phase 4b (the
writing panel) not started and separately blocked (item 13).

**Size.** H9: M — `lifecycle.stamp()` writer, one new event kind,
`item.html.j2` disclosure panel + render plumbing, tests.

**Local model: yes** for H9's event half — the plan §H9 names the files
(the plan cites `lifecycle.py:642`/`render.py:756`; those functions are
now at `lifecycle.py:972`/`render.py:1091` — the plan's line cites are
drifted, its named symbols are not), the invariant
("a baseline created before it says rich content is unavailable rather
than inventing text from current files"), and the exclusions (no baseline
schema change, no `diff_against` change, no backfill). The panel's
presence/absence pattern is precedented by the thread panel. Layout taste
is the only judgment.

**First test:** stamp `refdes revision` after enabling history → the
store contains an event of kind `baseline` whose snapshot answers
"what did this item say at rev-B?"; a pre-H9 baseline resolves to the
"rich content unavailable" disclosure, not invented text.

## 10. docs/design/form-ingestion.md

**Header (read):** "Status: **proposed**; **no slices scoped, no code
written**. Nothing in this document is decided."

**Evidence.** No code: `grep -rni ingest src/ --include=*.py` → no
matches. The doc's §4 verified-while-writing claims check out today:
`GET /api/create/schema` (`src/refdes/serve/api.py:52,608`) advertises
fields/prefix/append_only/amends but no link verbs, and
`POST /api/items/create` (`api.py:690+`) accepts
`{type, fields, id, destination, amends, links}` — no `body:` — so the
two "load-bearing" gaps §4 names are real, unchanged.

**Verdict: BLOCKED ON A DECISION.** Not queueable. The named questions,
§6 (read): which schema route generates the form (widen
`/api/create/schema` vs. `refdes schema --json`); plus the two problems
carried from §1 (schema-sync over time; duplicate submissions), with the
§5 "accepted limitation" that a distributed form goes stale.

## 11. docs/design/item-search-hover.md

**Header (read):** "Status: **proposed**; **no slices scoped, no code
written**."

**Evidence.** No code: `editors/vscode/extension.js` registers only
`refdes.build/check/allocateIds/openPreview/refreshIndex/attachServer/
openInEditor/showServerLog` (lines 945-956, read); the shipped hover is
the id/status hover (Slice V0), not a project search; no `?`-trigger
search anywhere in the extension. §3.1's "There is no search in this
repository. None." header is the doc's own verified state.

**Verdict: BLOCKED ON A DECISION.** Not queueable. §6 (read): Q1 —
search backend + `?` trigger: which lands first; Q2 — does search index
bodies (recommendation yes, `ls`/`q` unchanged); the doc lists ten such
recommendations "the default if Jared lets it stand".

## 12. docs/design/inline-calc-later.md

**Header (read):** "**Not under review; direction notes only.** … None
is implemented or required to ship the first slice."

**Evidence.** First slice shipped (`src/refdes/inline_calc.py`,
`name := rhs [| unit] = result`); the deferred items are not:
`refdes inline-calc fill` — `refdes inline-calc --help` (run) exits
"invalid choice: 'inline-calc'"; one-unknown solving — no solve/root
machinery in `src/refdes/calc.py` (grep: `…` appears only as the
tolerance-interval *display* at `calc.py:988`, not as parseable range
syntax); live editor updates, multi-output calculators, `::1` pins,
`.refdes/equations.yaml` lockfile, form panel — no matches for any in
`src/`. The one recorded decision in the file is the range symbol
(`…` / ASCII `..`, owner 2026-10-17) for a solve span that has no
implementation to land it on.

**Verdict: NOT STARTED, by design** — this is a direction-notes document
and the task's premise ("decided" items) does not hold for it; the single
decided fragment (range symbol) is parked pending a solve design that is
"not under review". **Size if ever started: L** (cross-cutting:
evaluator, command, editor, lockfile). **Local model: no** — the file
itself states each piece "needs a separate review"; there is no written
contract to work from.

## 13. docs/design/thread-workbench-w5b-plan.md

**Header (read):** "Status: Proposed, and **blocked on the owner**. Ten
questions in §Open questions for Jared are open."

**Evidence.** The base it builds on is landed: W5a read-only pane
`7c72311` (#197) — `task_pane.py`, the `item.html.j2` pane block,
`taskpane.js`, all present (read; pane header: "computes nothing … fetches
nothing and writes nothing"). W5b itself is not: phases W5b.1–W5b.5
(plan §4) gate on Q1–Q10 (§6, read): Q1 where the tick draft lives, Q2
what save writes and through what door (incl. the `followed`-event
sub-question), Q3 tip-moved-mid-draft, Q4–Q10 (tickable states, draft
lifetimes, site-pane scope, CLI parity). No `POST
/api/item/<ref>/continue` in `src/refdes/serve/` (grep of api.py routes
shows only the existing edit/create routes).

**Verdict: BLOCKED ON A DECISION.** The plan itself is the queue: the
ten Q1–Q10 answers are the gate, and §8 of the plan tabulates which
phase each answer gates. Not code work.

## 14. docs/design/candidate-parts.md

**Status line (read):** "shipped (2026-09-25) — all five phases in §12
have landed".

**Evidence.** (A) `{{compare}}`: `src/refdes/blocks.py:550`
(`_render_compare` section), `tests/test_compare_block.py`, fragment
`compare-block.added.md`. (B) status-mapping `check_severity`:
`schema._parse_check_severity` (`src/refdes/schema.py:694`, cites
candidate-parts §4.3), in-use at
`hardware/v3/base.yaml:250` (`{candidate: info, selected: error, …}`).
(C) `rejected` status: `base.yaml:255` component enum
`[candidate, selected, rejected, obsolete]` with the "never satisfies"
doc line. (D) `refdes new --list` confirmed by running
`refdes new --help`; the dead-`defaults:` warning is
`parse._warn_dead_defaults_status` (`src/refdes/parse.py:1653`, called at
`:1842,:1944`). Phase 5 docs rows = PR #319 = `f002e53`
(`git log --grep="#319"`).

**Verdict: DONE.**

## 15. docs/design/named-calc-blocks.md

**Status line (read):** "Architecture decided (2026-09-24) … All five
phases (§13) have landed" (named fences, `[[ID#calc:name]]` fragments,
`{{calcblock}}`, hash pins, docs).

**Evidence.** (A) fence attributes: `calc.parse_fence_attrs`
(`src/refdes/calc.py:1018`) + `CalcFenceSyntaxError` (`:997`). (B)
qualified refs rejected: `calc.py:1119` ("Rejected, never resolved
(named-calc-blocks.md §4.2, §7)"). (C) fragments: `CALC_FRAGMENT_PREFIX =
"calc:"` (`src/refdes/build.py:75`), checked against the target's blocks
(`build.py:2843`); `{{calcblock}}` (`blocks.py:809`). (D) hash pins:
`build.calc_hash_for` (`build.py:2295`) hashes block contents, fence name
lives above them (`calc.py:1082` "stays lenient … so hashing"). Tests:
`tests/test_calc_block_names.py`, `test_calc_block_refs.py`,
`test_calc_block_hash.py`; fragments `named-calc-blocks.added.md`,
`calc-block-fragments.added.md`, `calcblock-page-render.added.md`,
`named-calc-blocks-docs*.added.md`; docs pages
`docs/blocks.md`/`docs/math.md` carry the `calc:` vocabulary (grep).

**Verdict: DONE.**

## 16. docs/design/stale-arithmetic-signal.md

**Status line (read):** "**Implemented** (`b537edd`, 2026-08-28) —
`lifecycle._stale_arithmetic` and the `stale_arithmetic` field on
`lifecycle.DiffResult`".

**Evidence.** `b537edd` exists on `main` (`git log -1 b537edd`:
"lifecycle: implement the stale-arithmetic signal"). Code:
`stale_arithmetic: list[str]` on the diff result
(`src/refdes/lifecycle.py:1092`), `def _stale_arithmetic`
(`lifecycle.py:1142`).

**Verdict: DONE.** (The header's "unreleased at the time of writing" note
is release-process state; 0.5.0 shipped before the commit per its own
text, so the signal ships with the next release — process, not work.)

## Method notes

- Status-line line numbers in `backlog.md` shifted since the task was
  written; sections were located by heading (mapping printed in §0).
  Two in-entry file/line cites have drifted (`model.py:174` → `:272`
  for `includes:`); the features themselves verified present.
- "Pending release" items (6, 7, 8) carry their `changelog.d/` fragments
  in the tree (`ls changelog.d/`), i.e. the release-process definition of
  shipped-not-released is met; no code work implied.
- The backlog's own verification date (2026-09-27, at `bda7ab5`) is ~1
  month and 285 commits (`git rev-list --count bda7ab5..899ab91`) behind
  this tree; this audit re-ran the checks at `899ab91`.
