# Changelog fragment verification — breaking + changed (2026-10)

Verified all 39 fragments in `changelog.d/` (16 `*.breaking.md`, 23
`*.changed.md`) against current main. Method: read each fragment, check every
nameable claim against the source (`grep`/`sed` in `src/refdes/`, `docs/`,
`tests/`, `pyproject.toml`) and, for CLI-visible claims, against live runs of
`python -m refdes.cli` (refdes 0.5.0) in throwaway projects under
`.scratch/fragments/` (init project pinned hardware@3, plus a v2-pinned
project for `standard upgrade`). Scratch wrapper: `.scratch/fragments/rf`.

## Verdict summary

35 of 39 accurate as written. 4 minimally fixed (listed under each entry).
0 need owner decision.

## Breaking fragments (16)

| fragment | verdict |
|---|---|
| calc-colon-units-retired | accurate (calc.py:1407–1416 sealed→warning; `calc-rewrite` exists; rewrite messages live-verified) |
| check-refresh-unreachable | accurate (citations.py:3122 `--allow-unreachable`, :3229/:3244 messages, HTTP/redirect semantics :3143–3155) |
| citation-page-checked | accurate (sources.py:683 "is not in this document -- it has X page(s)", citations.py:733–734 `page_count` keys, "not checked" :1926; live: page-grammar error, dynamic out-of-range after refetch) |
| citation-path | accurate (live: `url:`→`path:` rename error names the rewrite; `fetch --path`; `keep_copy: true` refused for local; `../` escapes refused) |
| citation-vendor-keep-copy | accurate (citations.py:73–74/135 `.refdes/copies` vs legacy vendor dir + lockfile key; schema.py:304 `missing_vendored_copies` release-gate rule errors naming `missing_kept_copies`; live: `vendor:` errors with `keep_copy:`) |
| config-duplicate-key | accurate (live: exit 2, `configuration error: refdes-project.yaml: duplicate key 'site' in one mapping (lines 1 and 13) -- YAML keeps the last, so the value on line 1 is lost.`; nested repeats; `add-preset` rejects; mapping-file rename guard) |
| config-split-two-files | **fixed**: overlay key list said `field_sets:` (main is `sets:`, standards.py:194–201/schema.py:377) and the settings list said `history:` (renamed to `on_change:` — the retire-guard's own message names `on_change:`); corrected to `sets:` ×2 and `on_change:` |
| duplicate-mapping-key | accurate (all quoted messages live: item file, defaults block, rename-mapping file, nested mapping, markdown front matter; byte-identical text withheld; `id` exit 1; `keys adopt`/`calc-rewrite` exit 1) |
| hardware-v3-drop-in | accurate (live on v3: "the link verb 'component.equivalent' is now 'component.drop_in' ... Its targets are used as 'drop_in' in this build", exit 1) |
| history-config-on-change | accurate (live: project `history:` → "was renamed to on_change:" config error exit 2; item-level → "item-level history: was renamed to on_change:" + read as on_change) |
| scalar-field-typo-error | accurate (quoted message exact; 0.6 cutoff parse.py:1384–1385; live) |
| scalar-for-list-field | **fixed**: field set is `model.NON_SCALAR_FIELD_TYPES = {list, checks, citations, options, tasks}` (model.py:199) — fragment omitted `tasks`; added. Rest live-verified (quoted message exact; link verb stays lenient) |
| sets-rename | accurate (v3 uses `sets:`: base.yaml; schema.py:377–379 hard-errors on `field_sets:` naming the rename; bundle loader reads both keys) |
| threads-4a-decision-merge | accurate (v3 schema json: no decision type; log__entry has satisfies/constrained_by/selects/supersedes/blocked_by/summary/status/rationale; base.yaml:283 `legacy_prefixes: [DEC]`; v3 preset list empty — live: "preset 'design-debate' does not exist for hardware@3 (available: [])" exit 2; migration.yaml decision→log, records→follows; history.py:743 "now follows it"; build.py:3816 edited-after-captured not a failure) |
| verb-named-reserved-key | accurate (parse.py:62/66 RESERVED+OVERRIDABLE as listed; schema.py:43/203 reads both; live: declaring a `board:` verb errors exit 2 naming key; inverse verb checked) |
| vocab-p9-log-to-timeline | accurate (live: item `on_change: log` → "renamed to 'timeline'... read as 'timeline' in this build"; `on_change.default: log` config error exit 2; schema enum invalidate/timeline/ignore; cli.py:1726 audit text) |

Every breaking fragment states the upgrade action a reader must take (all
"what you must do" / "run standard upgrade" / rename-in-place instructions
verified against the live guard messages, which name the new spelling).

## Changed fragments (23)

| fragment | verdict |
|---|---|
| calc-cross-item-refs-hash | accurate; **fixed format** (no leading `- `; added) — hash_format 4 + format-3 carry-forward build.py:2170–2180; audit line lifecycle.py:999; math.md covers cross-item refs |
| calc-fence-label-not-semantic | accurate (history.py `_strip_calc_fence_labels` + legacy semantic payload, PR #323 R9-F2) |
| calc-sources-hash | accurate (build.py:2177–2182 "(canonical path, key, locked decimal text)", same format 4, no fifth format; `calc_refs` payload :2249) |
| editor-save-single-build | structure accurate (serve/edit.py:20–21/342–352 single deferred build on gate); wall-clock timings not re-measured |
| entry-summary-typography | accurate (style.css:479 `.tl-summary` 17.5px/semibold/1.3 vs body `--text-xl` 15px, `.tl-body` 14px, h2 18px, `--text-sm` 12.5px, no colour rule) |
| extends-overlay-link-null | accurate (tests/test_extends.py:120,139–141) |
| follows-freeze-to-anchor | accurate (links.py:602/684/821 `FollowsAnchorPlan`/`plan_follows_anchor`/`anchor_follows`; adopt.py:218 "could not anchor N local follows reference(s)"; cli.py:2427/:2441 "would anchor"/"anchored N follows reference(s)"; chains.py:184 `anchored_only`; marker `.refdes/keys-adopted.yaml` keys.py:32 carries only `adopted:`) |
| hardware3-sets-factoring | accurate (v3 base.yaml sets: grouped/claims/invalidate_body/statement_title:124/named_title:131 = five; test_extends.py:582 base-resolves-unchanged; vocabulary.py:885 "Included by") |
| image-bytes-hash | accurate (build.py:2193 HASH_FORMAT=5 + §15.6 comment; seal.py:469 "modified since it was sealed"; URL `<img>` contributes nothing build.py:2523; docs/change-tracking.md:105/127 + docs/markdown.md:119 document it) |
| index-help-names-its-payload | accurate (cli-reference first line describes the payload; "print items.json to stdout" gone from docs). Note: `index --help` also lists the content hash, which the fragment's parenthetical doesn't enumerate — subset, not false; left as is |
| libyaml-parsing | accurate (parse.py:168 `getattr(yaml, "CSafeLoader", yaml.SafeLoader)`) |
| ls-free-text-matches-ids | **fixed**: `ls --help` and cli-reference.md:432 say the query matches id, title, `tags:` **and `former_ids:`** (cli.py:820/899/3091) — fragment claimed "id, title and tags"; corrected. Live: partial/lowercased id matches; editor filter (serve/filters.py) still title+tags only, as fragment says |
| markdown-parser-cache | structure accurate (build.py:2494–2528 thread-local `MarkdownIt`); timings not re-measured |
| on-change-fields-undeclared-name | accurate (parse.py:1124–1135 error + `del fields[fname]`; live message matches; :1158 posture comment) |
| pdf-source-reader | accurate (pyproject.toml:57 `pypdf>=6.19` with floor rationale :51; sources.py:1032 names the `[pdf]` extra; PdfReader extract:839–866 requires a quoted-line anchor, so a plain `source()` line hits the specific pdf reader, not the registry) |
| prefix-mismatch-warning | accurate (live: "WARNING ... id 'C-001' does not match this item's prefix 'CMP'", build continues) |
| readonly-notice-one-sentence | accurate (model.py:791 READ_ONLY_REFUSAL, :809 DESTINATION_REFUSAL "cannot write {path} (read-only tree?)", :863 "--no-write to silence this" suffix; cli.py:144/161/522; docs/cli-reference.md:71 section exists) |
| rename-replaces-revise | accurate (cli.py:2784 stderr alias line "will be removed in the next minor release"; stdout clean; `revise` absent from `--help`; `src/refdes/revise.py` module kept; docs/cli-reference.md has no revise) |
| revise-keys-cleanup | accurate (cli.py:2596 "exact match (surrogate key)", similarity kept for keyless baselines; revise.py has no ledger/seal-record rewriting, `_bare_reference_blockers` refuses with file:line :1444; dry-run simulates key pipeline + rename + display-half refresh on a copy, revise.py:1304–1336/1579–1582) |
| serve-watches-images | accurate (serve/state.py:9/(mtime,size) signature :114–119, asset_files/project_inputs walk :40–75) |
| standard-upgrade-no-write-dry-run | accurate (live on v2 project: `--no-write`/`--dry-run` print the plan, exit 0; `--no-write` refuses fetch/init/history-capture) |
| theming-token-layer | accurate (style.css `:root` token layer; tests/test_style_tokens.py exists) |
| thread-derived-grouping | accurate (threads.py:115 "Derived (auto clears when fixed)", group headings + kind order, sorts :670/:752; cli.py:1120–1126 "(none)") |

## Missing-fragment findings (for owner decision, not fixed here)

From `git log v0.5.0..main -- src/` (344 commits; renames/removals filtered;
command set diffed against the v0.5.0 tree — only the `revise` alias was
added, no command removed):

1. **hardware@3 ships, and `refdes init` now pins it.** v0.5.0 bundled only
   hardware@1/v2 (verified via `git ls-tree v0.5.0 src/refdes/standards/hardware/`);
   commit 50cf460 ("standard: ship hardware@3") bundled v3, so the
   `<latest>` pin `refdes init` stamps moved from 2 to 3 for every new
   project. No fragment announces the shipping/pin; the v3 added/changed
   fragments describe contents only, and several even say "the bundled
   hardware@3 is itself unreleased".
2. **v2→v3 field fold `text:`→`body:` (requirements/bounds) and
   `method:`→`body:` (tests)** with a hard refusal for items that already
   have body content (v3 migration.yaml). User-visible for anyone running
   `standard upgrade --to 3`; 50cf460 shipped no fragment and none of the 39
   covers it (threads-4a covers only the decision `title:`→`summary:` fold).

## Log

Applied 4 minimal edits: config-split-two-files (2 key names), scalar-for-list-field
(+`tasks`), ls-free-text-matches-ids (+`former_ids:`), calc-cross-item-refs-hash
(bullet prefix). All other fragments untouched. Verification runs left in
`.scratch/fragments/` (proj, p1–p22, v2).
