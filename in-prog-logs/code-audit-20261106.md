# Code optimization and simplification audit (PERF-3)

Audited: `src/refdes`, `tools/`, `src/refdes/serve/static` at main `b9eba32d`
(the PR-size-gate era). **Audit only — no code in `src/`, `tools/` or
`serve/static` was modified.** Every claim below names the command that
produced it; measured numbers are from this machine (Linux, Python 3.13.5,
venv `/home/jorb/work/venv-refdes`, ruff 0.16.9).

All audit scripts live in `.scratch/` (gitignored) and are re-runnable:

| script | what it does |
| --- | --- |
| `.scratch/deadnames.py` | AST: top-level defs in src+tools, classified by reference site (src / tests / docs / data) |
| `.scratch/argparse_flags.py` | AST: every `add_argument` dest, checked for `args.<dest>` reads in src |
| `.scratch/dupfuncs.py` | AST-normalized exact-duplicate + SequenceMatcher near-duplicate functions |
| `.scratch/profile_run.py` | counting wrappers (open/re.compile/subprocess/yaml/`Project.__init__`) + cProfile around a CLI run |
| `.scratch/serve_profile.py` | in-process `refdes serve` with Project/jinja/open counters driven by real HTTP requests |
| `.scratch/gen_project.py` | synthetic project generator (N requirements with links) for scaling sweeps |

Verdict legend — **do**: benefit measured, risk bounded; **maybe**: benefit
real, risk/design tradeoff to weigh; **skip**: leave alone (documented
divergence, deliberate design, measured cost too small).

---

## Section 1 — Dead code

First-pass tooling evidence:

```
$ ruff check src tools --select F401,F811,F841
All checks passed!
```

ruff's own dead-import/redefinition/unused-local rules are **already clean**;
everything below comes from the AST reference scan (top-level defs; nested
functions and methods excluded), cross-checked by hand with a whole-repo
word-boundary grep (`.scratch/verify_names.txt`). CLI flags and serve routes
were swept separately: **0 dead flags** (all 66 `add_argument` dests are read
somewhere: `argparse_flags.py` printed zero `NEVER-READ` rows), **0 dead
`/api/` routes** (all 13 Python-side literals are referenced by
`serve/static` JS), **0 dead template files** (all 17 under
`src/refdes/templates/` referenced), **0 dead standards files**.

### 1.1 Unused constants (3) — **do** (all)

| location | evidence | benefit | risk |
| --- | --- | --- | --- |
| `src/refdes/seal.py:45` `SEAL_FILE = ".refdes/log-seal.yaml"` | only repo-wide hit is the def line itself; the path is built from the literal at `seal.py:61` (`f"log-seal-{board}.yaml" if board else "log-seal.yaml"`) | −1 line; removes a constant that invites a future edit to change one copy of the path only | none — no code reads it |
| `src/refdes/serve/state.py:34` `CONFIG_NAMES = (PROJECT_CONFIG_NAME, SCHEMA_CONFIG_NAME)` | def line is the only reference; the two members *are* used (`state.py:85,88`) | −1 line | none |
| `src/refdes/navis_ops.py:24` `KINDS = frozenset(...)` (14 lines) | referenced only by a docstring (`navis_ops.py:44`); no code reads it | −14 lines | low — it is documentation of an output shape; if it should *enforce* the shape, wire it (that's a feature, not cleanup) |

Tests covering: none needed (nothing reads them).

### 1.2 Unused function (1) — **do**

`tools/docs_context/llm.py:213` `_get_json_body` (10 lines). Zero references
in code; the only text mention is `in-prog-logs/docs-context-ask.md:122`
which records "`_get_json`/`_get_json_body` **collapsed**" — the pair was
collapsed into one helper and the def was left behind. **do**, −10 lines.
Risk: none.

### 1.3 Test-only helpers living in `src/` (7) — **do** (move to tests, delete from src)

These are `src/refdes` top-level functions whose only callers are
`tests/` (verified: zero hits in `src/` outside def+prose, zero in `tools/`,
`docs-site/`, `editors/`):

| location | lines | callers | note |
| --- | --- | --- | --- |
| `src/refdes/patcher.py:294` `revert_plan` | 27 | `tests/test_patcher.py` (×10), `tests/test_patcher_links.py` (×4) | inverse-of-plan helper; pure test support |
| `src/refdes/chains.py:708` `fold_at_tip` | 30 | `tests/test_threads_projection.py` ×1 | docstring calls it a thin wrapper over `resolve_current_with_source` kept "so the equivalence test still [holds]"; design docs mention it in prose only |
| `src/refdes/navis.py:1171` `scan_body` | 13 | `tests/test_navis.py` (×46 grep hits, all tests) | thin wrapper: `analyze_navis(body)` and split — production reads `analyze_navis` directly |
| `src/refdes/standards.py:97` `resolve_schema` | 9 | `tests/test_standards.py` ×2, `tests/test_revise_migrations.py` ×1 | production path is `resolve_namespaces` (`schema.py:811`); `resolve_schema` is the "two-value form" convenience wrapper nobody in src calls |
| `src/refdes/build.py:3423` `legacy_hash_for` | 5 | `tests/test_keys_links.py` ×3, `tests/test_keys.py` ×1 | test-support for legacy-hash fixtures |
| `src/refdes/patcher.py:323` `patch_item` | 6 | `tests/test_patcher.py` ×2 | see 2.2 — the serve editor path uses `plan_patch`/`apply_patch` directly, not this |
| `src/refdes/editor_journal.py:698` `refuse_if_pending` | 5 | `tests/test_editor_journal.py` ×6 | **flag for Jared**: `serve/edit.py` uses `begin`/`complete` (lines 2196–2228) and relies on `begin` raising `JournalPending`; `refuse_if_pending` (the pre-flight guard in the design notes, `in-prog-logs/editor-journal-1-designer.md:21`) has no production caller. Either the guard is obsolete-by-design (delete) or the editor is missing its call (bug) — human call needed, audit can't tell |

**Verdict**: delete + move each into its test module (net −102 lines from
`src/`). Risk: mechanical; each is covered by exactly the tests listed (those
tests are the verification). The `refuse_if_pending` row is **do (with the
design question answered first)**.

### 1.4 Test-only *and* duplicated (1) — **do**, highest value of §1

`src/refdes/history.py:244` `legacy_object_payload` (9 lines) is
**byte-identical in body** to `object_payload` at `history.py:306` except it
wraps `legacy_semantic_payload` (see diff in §2.4). Delete it; the single
test caller (`tests/test_history_edited.py:612`) can call
`object_payload(legacy_semantic_payload(item))`-style composition inline.
−9 lines, kills the in-file clone. Risk: one test edits.

### 1.5 Keep-list (false positives the scanner raised) — **skip**

`vocabulary.render_markdown` (used by `docs-site/gen_examples.py:158`),
`theme.check_builtin_themes` (used by `docs-site/gen_themes.py:75`),
`theme.SEMANTIC_BAND_TOKENS` (test-parametrized; keep as API),
`tools/docs_context/refs.py:490 clear_caches` (intentional cache-reset API
for a long-lived MCP process, used by `tests/test_docs_context_refs.py`),
`tools/pr_size.py:66 count_src_additions` — *test-only as a function*, see
§2.8 where the fix is the opposite direction (make `main()` use it).

`refuse_if_pending`-style "docs-only" hits are prose in
`docs/design/*` / `in-prog-logs/*`, never code.

**§1 ranking:** 1.4 → 1.1/1.2 (trivially safe) → 1.3 (bulk −102 lines) → 1.5.

---

## Section 2 — Duplicated logic

Method: `.scratch/dupfuncs.py` (strip docstrings, alpha-rename locals, hash
AST) over all 1,133 functions ≥8 lines in `src/`+`tools/`: **9 exact-duplicate
pairs; zero near-duplicates ≥0.90** (SequenceMatcher, full pairwise within
length buckets). Diffs from `difflib.unified_diff` on the source segments.

### 2.1 Byte-identical pair in ONE file (the reviewers' finding) — **do**

`src/refdes/history.py:244 legacy_object_payload` ⇄ `src/refdes/history.py:306 object_payload`
(identical modulo `legacy_semantic_payload` vs `semantic_payload`):

```diff
-def legacy_object_payload(item):
-    payload = dict(legacy_semantic_payload(item))
+def object_payload(item):
+    payload = dict(semantic_payload(item))
     payload["key"] = item.key
     payload["id"] = item.id
     payload["source"] = {...}
```

−9 lines by deleting the test-only one (§1.4). Risk: `tests/test_history_edited.py`
only.

### 2.2 `_esc` byte-identical across modules — **do**

`src/refdes/blocks.py:75` ⇄ `src/refdes/build.py:3488` — **9/9 lines, byte
identical**. Both private; `build.py` already imports `blocks`? check import
direction at fix time; pick one home. −9 lines. Risk: rendering-escape
correctness — covered by build/render goldens; run `pytest tests/test_build.py
tests/test_blocks*.py`-area tests.

### 2.3 `_check_state` ⇄ `check_state` — **do**

`src/refdes/render.py:270` ⇄ `src/refdes/serve/filters.py:94`, byte-identical
bodies (8/9 lines; `filters.py`'s docstring literally says "The same rollup
`render._check_state`/`items.json` report"). Serve already imports from
`refdes` (`serve/edit.py:103`), so import direction is fine. −8 lines. Risk:
low; covered by serve page tests + render tests.

### 2.4 `_write_taskpane_assets` ⇄ `_write_navis_assets` (same file) — **do**

`src/refdes/render.py:1178` vs `render.py:1204` (16/12 lines): identical
shape, parameterized by `(ASSET_NAMES, ASSET_DIR)`:

```diff
-    for name in TASKPANE_ASSET_NAMES:
-        shutil.copyfile(os.path.join(TASKPANE_DIR, name), os.path.join(asset_out, name))
+    for name in NAVIS_ASSET_NAMES:
+        shutil.copyfile(os.path.join(NAVIS_DIR, name), os.path.join(asset_out, name))
```

One `_write_assets(out_dir, written, enabled, names, src_dir)` helper;
−10 lines. Risk: byte-identical site output is exactly what the asset tests
assert — they are the safety net.

### 2.5 `_create_temp` in 4 copies — **skip (risk)**

`textio.py:279`, `editor_journal.py:321`, `history.py:1196` byte-identical
AST; `seal.py`'s twin is named in the docstrings ("identical to seal's
`_create_temp`"). Bodies identical modulo docstrings; docstrings carry
substance (umask rationale, PERM-OWNER-001/002). This is **write-path code**;
per the audit's standing instruction, listed as a finding, not a
recommendation — a shared helper touches every atomic write. If Jared wants
it, it goes through `tests/test_preset_write_atomicity.py` and the perm tests.

### 2.6 `_item_tags` ⇄ `item_tags` — **skip (deliberate)**

`blocks.py:91` ⇄ `serve/filters.py:77`. Divergence is **documented in the
docstrings** (run-7 F13/F16 made the CLI read string-only; the serve page read
keeps lenient `str()`; `in-prog-logs/run7-small-nits.txt`). Merging them
changes what a broken project's page displays.

### 2.7 `_item_spans` ⇄ `_item_spans` (28 lines) — **skip (deliberate)**

`links.py:56` ⇄ `revise.py:610`; code identical modulo
`parse_mod.FENCE_RE`/`parse.FENCE_RE`. `links.py`'s docstring: "reimplemented
here rather than imported: this module has no dependency on revise.py, by
design (…revise.py's own retirement…)". Leave; revisit when revise retires.

### 2.8 `pr_size.py`: `main()` duplicates `count_src_additions` — **do**

`tools/pr_size.py:66` defines `count_src_additions(numstat_text)` (3 lines,
tested ×13 in `tests/test_pr_size.py`), but `main()` computes
`total = sum(added for added, _, path in rows if path.startswith(SRC_PREFIX))`
**inline** and never calls it. Benefit: the gate's own helper becomes the
tested path (real coverage of what ships), −1 duplicated expression, and
`count_src_additions` stops being test-only (§1.5). Risk: trivial, CI gate
itself is covered by `test_pr_size.py`.

**§2 ranking:** 2.1 → 2.8 (correctness-of-gate) → 2.3 → 2.4 → 2.2; 2.5–2.7
skip.

---

## Section 3 — Hot paths: measured

Method: `.scratch/profile_run.py` runs the real CLI in-process with counting
wrappers on `open`/`re.compile`/`subprocess`/`yaml.load`/`Project.__init__`,
plus cProfile. Baselines: repo's own project (20 items), `docs-site`, and
synthetic projects from `.scratch/gen_project.py` (`.scratch/syn{200,800,1600}`;
the `satisfies` warnings are schema-shape noise in the generator, the parse
work is identical).

**Structural findings first (the good news, measured):**

- **Project built exactly once per command**: `refdes check` and `refdes
  build` report `Project.__init__ = 1`; `serve` builds 1 project at startup,
  requests reuse it (`/api/items` ×3, `/api/item/REQ-PWR-001` ×2,
  `/api/revision` ×2: `proj=1` throughout).
- **0 subprocess spawns** in check/build.
- **`check` scales linearly**: N=200 → 151 ms, 800 → 436 ms, 1600 → 914 ms
  (in-process, excludes import).
- Serve request handling is in-memory (`/api/items` 9.4/11.7/13.4 ms; file
  opens stayed flat at 117 across all requests).

### 3.1 `render._unique_calc_anchors` re-scans every page — **do** (biggest item in the audit)

cProfile of `refdes build` on the 800-item synthetic project:

```
1226670 function calls in 6.118 seconds
  809    3.338    3.338    {method 'findall' of 're.Pattern' objects}
  809    0.004    3.382    render.py:61(_unique_calc_anchors)   # of render_site's 5.016 s
```

Mechanism (`render.py:84`): `taken = set(_ID_ATTR_RE.findall(html))` scans
the whole page with a lookbehind regex, and `_CALC_TABLE_ID_RE.sub` scans it
again, for every page — pure waste when the page has no calc tables. Measured
on 400 real rendered pages (mean 181 KB):

```
pages with calc tables: 0/400
findall pass: 2189.9 ms total (5.47 ms/page)
substring precheck ('class="calc"' in html): 35.3 ms (0.088 ms/page, 62× cheaper)
plain id=" findall 0.29 ms/page vs lookbehind 5.86 ms/page   # the lookbehind is ~20×
```

A/B experiment (same machine, same inputs, monkeypatched guard
`if 'class="calc"' not in html: return html`):

```
baseline build: 7353 ms
guarded  build: 1746 ms   saved 5607 ms (76%)
outputs byte-identical: True
```

On this repo's own 20-item site: 40 pages, 3 carry calc tables → the guard
skips 37 of 40 (~20 ms of the 581 ms build, ~3–4%; share grows with site
size).

Fix shape: keep the function, add the substring guard (one line). Risk: a
page whose calc-table markup changes its literal `class="calc"` string → the
guard must be updated with `_CALC_TABLE_ID_RE` (keep both literals adjacent);
site goldens (`test_render`/build output tests) cover byte-identity.

**Follow-on micro (same lines of code, for calc-bearing pages):**
replace the lookbehind scan (`(?<![-\w])id="`) with a plain `id="` finditer +
Python-side check of the preceding character (measured 20× cheaper per page,
§3.1 data above). Same output; the char-check preserves the exact rule the
docstring records (`data-id=`, `hiddenid=` exclusion). **do**, second commit.

### 3.2 Every CLI start imports pint: ~273 ms of 445 ms — **do**

```
$ time: refdes --version 445 ms; refdes ls 528 ms; bare python 15 ms
$ python -X importtime -c "import refdes.cli" | sort by cumulative
  487655 µs  refdes.cli
  273325 µs    refdes.calc      (self 180 ms + pint 93 ms)
  172 ms wall  import pint ; 308 ms import refdes.calc ; 313 ms import refdes.ids
```

`calc.py:22` runs `UREG = pint.UnitRegistry()` at import, and
`model.py` → `calc` is in the import chain of *every* command (`cli →
adopt → boards → keys → ids → model → calc`). Commands that never touch units
(`ls`, `schema`, `keys`, `id`, `init`, `new`, `revision`, `history`, `navis`,
`index`, …) pay ~60% of their runtime for a unit registry.

Fix shape: lazy `_registry()` accessor in `calc.py` (build on first use),
`UREG`/`Q` module attributes behind it; callers in `calc.py`/`inline_calc.py`
switch to the accessor. Risk: module-level `UREG`/`Q` uses must all migrate
(mechanical, greppable); the registry is global-persistent (pint caches
definitions in the registry object, so first calc pays ~136 ms once per
process — calc commands' net change ≈ 0). Benefit: ~270 ms (−60%) on every
unit-free command. Tests: whole suite touches calc; the win is directly
measurable with the same timing script.

### 3.3 Jinja compiles all 12 templates on every process / every serve rebuild — **do**

- `render.py:1267`: one `Environment(...)` per `render_site` call; 20-item
  build: `get_template` 51 calls, **12 compiles = 393 ms of the 581 ms
  build**; 800-item build profile: `environment.compile` 0.350 s of 6.1 s.
- In-process `serve`: 12 compiles at startup, and **+12 more per preview
  rebuild** (instrumented: `render_site` 1→4, compiles 12→24→36→48; each
  rebuild ~180–200 ms, of which ~150 ms is compile).

Fix shape: `Environment(..., bytecode_cache=FileSystemBytecodeCache(dir))`
keyed to a cache dir (tempdir under the user cache), `auto_reload` keeps
template edits fresh. Benefit: serve rebuilds −~150 ms (≈75% of rebuild
latency the editor feels after the ~2 s poll), repeat builds −~350 ms.
Risk: cache staleness (mitigated by mtime check), cache-dir lifecycle
(tempdir), and template compiles must remain deterministic (goldens verify).

### 3.4 Page/nav output is O(n²) in site size — **maybe (design)**

Measured: synthetic site mean item page 46 KB at N=200 → **174 KB at
N=800**; total site 10.4 MB → **146.3 MB** (×14 for 4× items). `base.html.j2`
root executes 228,836 times in the 800-item build (~286 nav rows per page).
Every page embeds the full nav, so total bytes and render cost grow with
n². Any fix (shared nav include fetched once, or JS-injected nav) is a
site-structure change, not a code tweak — flag for Jared, **maybe**.

### 3.5 Small repeated work — **skip** (measured, not worth the diff)

- check (20 items): 34 file opens, 23 distinct; reopened: seal files ×2–3
  (read by load + by check verification, semantically distinct passes),
  history events ×2, `style.css` ×2, one PNG ×2–3. All ≤ a few ms.
- `difflib.get_close_matches` ×2400 (251 ms at N=800, 4.8% of the profiled
  build) — only runs on the warning path (unknown-field "did you mean"); a
  clean project pays ~0. Fine.
- argparse builds 40 subparsers per run (~19 ms cum cProfile, gettext ×120
  13 ms): a lazy-subparser `main()` split saves ~20 ms/command — small vs
  the import fix (3.2); **skip** unless 3.2 lands and the CLI is
  startup-critical.

**§3 ranking:** 3.1 → 3.2 → 3.3 → 3.4 (design call) → 3.5.

---

## Section 4 — Oversized functions/modules

`ast`-measured (whole `src/refdes` + `tools`, 1,710 functions): 16 functions
≥200 lines. Top 10:

| # | lines | location | split? |
| --- | --- | --- | --- |
| 1 | 891 | `cli.py:3224 main` | **would help**: 39 `add_parser` blocks inline; extracting the parser construction (`_build_parser()`) separates argparse plumbing from dispatch; every §3.2/§3.5 change lands in this file, so the split pays interest |
| 2 | 513 | `render.py:1256 render_site` | **would help**: per-page renderers are already template-per-section; the body is a long sequence of "render X if needed" blocks — extract per-page emitters (the 3.1/3.3 work touches it) |
| 3 | 444 | `citations.py:2677 fetch_all` | **skip**: network-fetch orchestration; length is sequential fetch/report stages, splitting adds indirection, no measured hot spot (0 measured cost — citation fetch is `--refresh` only) |
| 4 | 393 | `schema.py:746 load_project` | **maybe**: load+validate+register stages; correctness-critical, split only alongside a real change |
| 5 | 382 | `revise.py:1479 apply` | **skip**: revise is slated for retirement (links.py docstring, §2.7) |
| 6 | 373 | `cli.py:1773 cmd_audit` | **skip**: one report printer; sections are already loops |
| 7 | 360 | `calc.py:1340 evaluate_block` | **skip**: expression evaluation is naturally a long dispatch; unit-critical (correctness-critical path) |
| 8 | 351 | `build.py:434 validate_items` | **maybe**: diagnostic-rule loops; extract rule groups if rules keep growing |
| 9 | 255 | `parse.py:1180 _build_item` | **skip (risk)**: markdown/parse path — standing audit rule says don't churn it for style |
| 10 | 247 | `build.py:3513 _linkify` | **skip (risk)**: link rendering on the write-path-adjacent side; correctness-critical |

Modules (lines): `build.py` 4700, `cli.py` 4118, `citations.py` 3273,
`serve/edit.py` 2347, `revise.py` 2320 (retiring), `parse.py` 2046,
`patcher.py` 1897, `calc.py` 1793. **Verdict: split `cli.py`'s
`main`/parser (helps §3.2/§3.5, mechanical, test-covered) and `render_site`
(aligns with §3.1/§3.3 work). Everything else: skip — size alone is not a
defect when the code is a rule table (audit/validate) and tests already
address it.**

---

## Section 5 — JS in `src/refdes/serve/static`

Inventory: 20 files, 4,945 lines; the page loads exactly one module
(`index.html`: `/edit/static/app.js`); everything else arrives through the
`import` graph. Reachability scan: 18/20 files reachable from `app.js`;
`preview.js` is served to the preview surface (`serve/preview.py` references
it); `navis-preview.js` is loaded by `templates/base.html.j2` (checked —
**not dead**).

### 5.1 Dead exports (6) — **do**

Zero importers anywhere in `static/`, zero uses in own file beyond the export
line itself (per-file `export`-usage scan):

```
app.js:85      export function currentRevision() { return openRevision; }
app.js:86      export function setOpenRevision(rev) { openRevision = rev; }
drafts.js:216  export function corruptDraft(handle) {...}
filters.js:45  export function itemsHref(filters) {...}
formatbar.js:36 export const FIGURE_SKELETON = ...
formatbar.js:37 export const VALUE_SKELETON = ...
```

Drop the functions/consts (or the `export` keyword where the value is
self-used: `NAVI_SKELETON`, `SPAN_SKELETON`, `OPS`, `SHORTCUTS`, `REFDES_OPS`,
`FILTER_PARAMS`, `FACETS`, `PICKER_LIMIT`, `withFacet`, `hasAnyDraft`,
`discardCorruptDraft`, `isStale`, `poll`×2, `wireValueToggles` are
export-keyword-only bloat, refs>1 in-file, 0 importers — listed, low value,
leave to a follow-up). Benefit: −6 functions (~14 lines), API surface honesty
(the two `app.js` revision accessors are exactly the ED-1 surface an editor
author would expect to be wired — if the revision handshake is meant to use
them, that's the bug-shaped case, same class as §1.3 `refuse_if_pending`).
Risk: none (no importers; JS has no dynamic import of these names — verified
by name grep across `static/` and `index.html`).

### 5.2 `el()` duplicated in 12 files — **do**

Identical 6-line DOM helper (`function el(tag, cls, text) {…}`) in
`create.js:14, editor.js:23, filters.js:58, fontsetting.js:28,
formatbar.js:44, images.js:30, item.js:15, links.js:18, list.js:7,
live-calc.js:32, navis-panel.js:32, sourcepicker.js:6` (AST-normalized
hash-identical; pairwise ratio 1.000). Move to one small module (next to
`api.js`) + 12 imports. Benefit: −60 lines, single place for the pattern every
new panel copies. Risk: trivial (pure DOM builder, no state).

### 5.3 navis-preview.js ⇄ navis-panel.js twin panel — **maybe**

`act` 0.552, `clearStatus` 0.861, shared mint/status flow (the M2/M3 mint
buttons) across the preview panel (`navis-preview.js`, site-surface) and the
editor panel (`navis-panel.js`). Two near-identical fetch-status loops with
different surfaces. Sharing is a design call on the just-landed M2/M3 code —
list it, don't rush it.

### 5.4 Handlers never removed — **skip** (verified not-leaking)

`add=80` element-scoped listeners vs 6 window/document-level ones total
(`app.js:80/127/138` hashchange/rebuilt/stale-calc, `drafts.js:358`
beforeunload, `navis-panel.js:295/301` keydown/rebuilt), and
`mountNavisPanel` — the only one not at boot — is called exactly once
(`app.js:149`). All element-scoped listeners (images.js 12, sourcepicker.js
11, formatbar.js 9 …) attach to nodes inside regions the SPA replaces; they
die with the node. No leak demonstrated → no fix justified.

**§5 ranking:** 5.2 → 5.1 → 5.3 → 5.4.

---

## Summary

| section | items | do | maybe | skip |
| --- | --- | --- | --- | --- |
| 1 dead code | 12 (3 const + 1 func + 7 test-only + 1 dup-test-only) + clean sweeps (ruff/flags/routes/templates) | 12 | 0 | 5 keep-list |
| 2 duplication | 9 exact pairs (0 near) | 5 | 0 | 4 |
| 3 hot paths | 7 findings | 3 (+1 micro) | 1 (design) | 3 |
| 4 oversized | 10 functions + module ranking | 2 splits | 2 maybe | 8 |
| 5 JS | 4 | 2 | 1 | 1 |

### Five best `do` items by benefit/risk

1. **Guard `_unique_calc_anchors`** (`render.py:84`) — one line, measured
   **−76% build time** (7,353→1,746 ms @800 items), byte-identical output.
2. **Lazy-import pint/`UnitRegistry`** (`calc.py:22`) — measured **−273 ms
   (−60%) on every unit-free CLI command** (`--version` 445→~170 ms).
3. **Jinja `FileSystemBytecodeCache`** (`render.py:1267`) — measured 12
   template compiles (~150 ms) *per serve rebuild* and ~350 ms per repeat
   build removed.
4. **Delete the 12 dead/test-only src names** (§1.1–1.4) — **−128 lines**,
   incl. the in-file `history.py` clone and the two dead write-path constants;
   all mechanically safe.
5. **Dedupe `el()` across the 12 editor JS files** (§5.2) — −60 lines, zero
   risk; then §5.1's 6 dead exports.

(Plus §2.8 `pr_size.main()` → `count_src_additions`: the smallest diff here
and the only one that fixes a CI-gate correctness-of-coverage issue — worth
riding along.)

## Unverified hunches (NOT backed by command output — do not act without measuring)

1. `serve/edit.py` (2,347 lines, 13 `add` handlers) likely has more
   innerHTML-replacement churn than the audit sampled; per-handler leak audit
   in a real browser (the pptr388 recipe) was not run for this report.
2. The 117 opens observed per serve process may include per-request re-reads
   under a *dirty* project (poller rebuilds re-parse changed files); all
   request-phase measurements above were on a clean project.
3. `items.json` payload generation (`render` → 7 KB at 20 items) may carry a
   per-page nav duplicate that 3.4's fix would shrink; not isolated.
4. `inline_calc._scan_comment_line` (603 calls/20 items, 7 ms) is the next
   per-body hot spot if body sizes grow; not quadratic at measured scale.
5. Deleting the export-keyword-only JS exports (list in 5.1) was grepped by
   name only; a build-time bundler (none exists today) would change that.
