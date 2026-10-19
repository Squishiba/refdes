# Release-readiness audit — 2026-10-19

**Read-only audit of `main` for a release this week.** Nothing was fixed,
bumped, folded, or committed in `main`'s state; the only file written is this
report. Method follows `in-prog-logs/release-readiness-audit.md` (2026-09-27,
stale — used for method only). Every claim names the command run or file read;
where something could not be verified, it says so.

- Audited tree: `docs-release-audit-202610` branch, HEAD = `0efe209`
  (`main` tip at audit time, 2026-10-19 01:21 -0400), working tree clean at
  start (`git status --short` empty).
- Environment note: this checkout's venv (`~/work/venv-refdes`) had a stale
  editable install pointing at the deleted worktree
  `~/.paseo/worktrees/16msma8v/user-sim-run12-2`, so the `refdes` console
  script died with `ModuleNotFoundError`. Repaired with
  `pip install -e . --no-deps` (venv change only, not a repo change);
  `refdes --version` then reported `refdes 0.5.0`.

---

## 1. Version facts

- `pyproject.toml:3` — `version = "0.5.0"`.
- Latest git tag: `v0.5.0` (tag date 2026-08-21, `git log -1 --format=%ci v0.5.0`).
  Tag list: `v0.5.0, v0.4.0, v0.3.0, v0.2.1, v0.2.0`.
- `git log --oneline v0.5.0..main | wc -l` → **593 commits** on main since the
  released tag. pyproject is not ahead of or behind the tag (both 0.5.0).
- `changelog.d/` — **351 files: 350 pending fragments + `README.md`**.
  Every fragment is named `<slug>.<category>.md` with a category from the
  documented set (verified by extracting the category suffix of all 350).
  No removed/deprecated/security fragments.

| Category  | Count |
|-----------|-------|
| added     | 97    |
| changed   | 23    |
| fixed     | 214   |
| breaking  | 16    |
| removed   | 0     |
| deprecated| 0     |
| security  | 0     |

- The 16 `.breaking.md` fragments (name — one-line summary, from fragment text):
  1. `calc-colon-units-retired` — the `name : unit = expression` calc spelling
     is retired; old-spelling lines are build errors, `refdes calc-rewrite` converts.
  2. `check-refresh-unreachable` — `refdes check --refresh` now fails (was:
     warn + exit 0) when a pinned citation cannot be re-fetched.
  3. `citation-page-checked` — a citation's `page:` is now validated (bounds,
     two ways) instead of being free text.
  4. `citation-path` — citation `url:` is renamed `path:`, one field dispatched
     on scheme (`http(s)` = remote/fetched).
  5. `citation-vendor-keep-copy` — citation `vendor:` is renamed `keep_copy:`.
  6. `config-duplicate-key` — a key written twice in a config file is now a
     configuration error (both config files).
  7. `config-split-two-files` — `refdes.yaml` is retired; project config is now
     `refdes-project.yaml` + `refdes-schema.yaml`.
  8. `duplicate-mapping-key` — a key written twice in one mapping of an item
     file is now a build error.
  9. `hardware-v3-drop-in` — component `equivalent` link verb renamed `drop_in`.
  10. `history-config-on-change` — project setting `history:` and the item
      front-matter override are renamed `on_change:`.
  11. `scalar-field-typo-error` — a field name that is a confident misspelling
      of a declared field is now a build error.
  12. `scalar-for-list-field` — a scalar written for a list-shaped field is
      now a build error.
  13. `sets-rename` — `field_sets:` is renamed `sets:` (with composition widening).
  14. `threads-4a-decision-merge` — the `decision` type is retired; the
      history-backed `log` absorbs it.
  15. `verb-named-reserved-key` — a link verb named like a reserved
      front-matter key (`id`, `type`, `body`, `former_ids`, `key`, `prefix`, …)
      is now an error.
  16. `vocab-p9-log-to-timeline` — the `on_change` mode `log` is renamed
      `timeline`.

  Read together: a release from this tree is a **major vocabulary/config
  break from v0.5.0** (v3-standard renames, config split, strict duplicate-key
  and scalar-shape errors). If the release is meant to be semver-honest, 0.6.0
  is only defensible for a 0.x line; that is a maintainer call, recorded here
  as a fact (16 breaking fragments), not a tool failure.

## 2. `release.py`

`python release.py --help` (run): usage `release.py [-h] [--dry-run]
[--allow-dirty] {cli,extension} version`.

`python release.py cli 0.6.0 --dry-run` was run **with `--dry-run` only**, to
completion, **exit 0**. Full sequence (from `release.py:432-463`,
`release.py:314-329` — verified by reading the source and by the run's output):

1. `require_clean_tree()` — passed (tree clean; `--allow-dirty` not used).
2. `require_newer(0.5.0, 0.6.0)` — passed: "== Releasing CLI 0.5.0 -> 0.6.0".
3. `require_unpublished_pypi("0.6.0")` — passed: "PyPI: 0.6.0 is unpublished,
   good".
4. `python -m pytest -q` (full suite) — passed: "tests passed". (Local suite
   runtime ~10 min, consistent with CI's 8–12 min Tests job.)
5. Dry-run report: names all **350 fragments** that "would be folded into
   CHANGELOG.md and deleted", then "dry run: stopping before any file is
   modified". It does **not** build, bump, or touch `dist/` on a dry run
   (`release.py:370-376` build/twine steps are post-`if dry_run: return`).

`git status --short` **before** (empty, verbatim — no output):

```
(empty)
```

`git status --short` **after** (empty, verbatim — no output):

```
(empty)
```

Nothing was created in `dist/` (no `dist/` exists; verified `ls dist` →
0 entries). One operational note: an earlier detached attempt died
silently (0-byte log, killed by the environment, not by release.py); the
audited run above is the complete one. `release.py extension` was **not**
run, per task constraints.

## 3. Build and metadata

- `python -m build` (build 1.6.1, available): built
  `refdes-0.5.0.tar.gz` and `refdes-0.5.0-py3-none-any.whl` into
  `./.scratch/dist-check/` (never into `dist/`); exit 0.
- `twine check` (twine 7.0.0): **PASSED** on both artifacts.
- Wheel contents (read from the built wheel): 106 entries, including 16
  `templates/` files, the `standards/hardware/v3/` YAMLs, and 2
  `assets/` files — the `[tool.setuptools]` package-data directive
  (pyproject.toml comment: templates/standards "are code here") works;
  a fresh install ships a runnable `refdes build`.
- Wheel METADATA: `Name: refdes`, `Version: 0.5.0`, `License-Expression: MIT`
  + `License-File: LICENSE`, `Requires-Python: >=3.11`, four `Project-URL`
  entries (Homepage/Documentation/Source/Issues →
  github.com/Squishiba/refdes, squishiba.github.io/refdes).
- pyproject metadata fields (`pyproject.toml:1-64`): real description, real
  author, 8 keywords, classifiers incl. `Development Status :: 3 - Alpha` and
  Python 3.11/3.12/3.13; optional extras `pdf`, `xlsx`, `dev`; console script
  `refdes = refdes.cli:main`. `grep -rn CHANGEME pyproject.toml` (and the
  docs words scan in §4): **no placeholders** (no CHANGEME/TODO/FIXME
  anywhere in pyproject.toml, docs/, docs-site/, README.md).
- Could **not** verify: PyPI *name* availability for `refdes`
  (`require_unpublished_pypi` checks only the version on the registered
  project; a name-squat on a never-published project name is outside what
  any command run here checks).

## 4. Docs

- `refdes build` in `docs-site/` (the CI `docs.yml:42` step): **exit 0,
  "0 items, 0 errors, 4 warnings"**; site written to `../_docs` (gitignored —
  tree stayed clean). Warnings:
  - `refdes-project.yaml — site.assets entry 'images' is not a directory`
    (`docs-site/refdes-project.yaml` names an assets dir that does not exist).
  - `docs/vocabulary.md — reference to citation '', which does not exist` ×3.
- `python docs-site/gen_examples.py --check` (the CI docs job): **exit 0**,
  all generated pages "up to date" (incl. `docs/schema-reference.md`,
  `docs/vocabulary.md`).
- **CLI reference coverage**: all **22** subcommands from `refdes --help`
  (`serve build check revision release index ls thread work id fetch audit
  init new schema standard keys rename calc-rewrite stub-tests former-ids
  history`) have sections in `docs/cli-reference.md`. **No command is
  missing** (per-command grep; 27 `##` headings in the reference).
- **Nav**: `docs/` holds 25 `*.md`; `docs/index.md` references all 24
  non-index pages. **No orphan pages.**
- Word scan (docs/, docs-site/, README.md):
  - `hardware@2`: 21 hits across 9 top-level pages. **All real hits are
    historical/version-context** (v1/v2 → v3 rename explanations, released
    presets, old error messages in troubleshooting.md). No stale claim that
    the current standard is v2. (`docs/links.md:81` even states v3 is
    unreleased, matching AGENTS.md.)
  - `refdes.yaml`: in top-level docs only in `docs/troubleshooting.md:13,21`,
    where it quotes the *retirement error* (intentional). Also in
    `docs/design/standard-library.md` and `docs/design/editor-vscode-adapter.md`
    as pre-split historical context inside design records.
  - `TODO` / `FIXME` / `CHANGEME`: **zero hits** in docs/, docs-site/, README.md.

## 5. Features since v0.5.0 with no docs (97 `.added.md` fragments)

Method: for each of the 97 `.added.md` fragments, extracted the feature terms
from the fragment body and grepped `docs/*.md` + `docs/design/*.md`; then
hand-verified every fragment with no/weak match. Coverage map (fragment →
covering page) — representative of the ~91 covered, all matched by grep:

- calc suite (`calc-rewrite`, `calc-project-equations`, `calc-pipe-units`,
  `named-calc-blocks*`, `calc-sources`, `calc-cross-item-refs`,
  `calcblock-page-render`, `inline-calc-spans`) → `docs/math.md`,
  `docs/blocks.md`, `docs/markdown.md` (inline calc: `docs/math.md` has the
  `:=`/inline-calc section); design records
  `docs/design/named-calc-blocks.md`, `docs/design/calc-sources.md`.
- keys/history/threads (`keys-adopt`, `key-corruption-lint`,
  `key-label-refresh`, `key-baseline-lint`, `import-keys`, `history-commands`,
  `history-backed-sealing`, `threads-*`, `former-id-lookup`,
  `baseline-relabelled-diff`, `ls-thread-keys`) → `docs/ids.md`,
  `docs/design/keys.md` (the record per AGENTS.md), `docs/cli-reference.md`,
  `docs/troubleshooting.md`, `docs/output.md`, `docs/design/living-notes*.md`.
- editor/serve (`serve`, `serve-port-token-file`,
  `editor-image-upload*`, `browser-editor-*`, `serve-editor-read`,
  `create-item-links`, `vscode-adapter-contract-tests`) →
  `docs/markdown.md` ("Uploading an image from the browser editor", :205),
  `docs/cli-reference.md` (serve section), `docs/getting-started.md`,
  design: `docs/design/browser-editor.md`, `editor-image-upload.md`,
  `editor-vscode-adapter.md`.
- theming (`theming-two-palettes`, `theming-site-theme-tokens`) →
  `docs/themes.md`, `docs/output.md`.
- vocabulary/standard (`vocabulary-page`, `vocabulary-differs-from`,
  `hardware-v3-group-type`, `hardware-v3-rejected-status`,
  `standard-definitions`, `standard-upgrade-dry-run`,
  `check-severity-status-mapping`, `sets-carry-links-body`, `schema-doc-key`,
  `compliance-verb-and-naming-docs`) → `docs/vocabulary.md`,
  `docs/standard-library.md`, `docs/schema-reference.md`, `docs/checks.md`,
  `docs/cli-reference.md`.
- CLI conveniences (`version-flag` → cli-reference + getting-started;
  `ls-workspace-*` → cli-reference + workspaces; `tree-view`,
  `candidate-list-layout`, `citation-ids`/`citation-section`,
  `fetch-size-warning`, `uncaptured-log-edit-warning`, `work-command`,
  `thread-command`, `follows-capture`, `edited-after-captured`,
  `open-tasks-captured-edits-gate-rules`, `changelog-fragments`) → each has a
  matching page/section found by grep (cli-reference, ids, links, design-log,
  multi-board, checks, lifecycle).

**Fragments with no user-facing docs page/section:**

1. `source-picker-panel`, `source-picker-accept`, `pdf-source-picker`,
   `pdf-picker-panel`, `pdf-picker-accept`, `editor-image-picker` — the
   editor's CSV/PDF **source-value picker** is documented only in
   `docs/design/editor-source-picker.md` (status proposed, slices landed) and
   `docs/design/editor-pdf-picker.md` (status **implemented**, slices P-A/B/C
   landed). Top-level docs: `docs/cli-reference.md` mentions "picker" once;
   there is no user page for the editor at all (it lives as a CLI reference
   section + a markdown.md subsection). **Gap: a shipped, user-visible
   editor feature with design-docs-only documentation.**
2. `ci-py313-job` — CI-only (Python 3.13 test job); lives in
   `.github/workflows/tests.yml`; no user docs needed — not a gap.

## 6. CI on main

`gh run list --branch main --limit 5`: the five most recent runs (latest
2026-10-19T05:21:38Z, ~90 min before audit) are **all `completed / success`**
— `Tests` (8m22s–12m25s) and `Deploy docs` (35s) for the three latest pushes
(PR #342, #341, #241 merge commits). No failures in the window.

## 7. Open holds

**Open PRs** (`gh pr list --state open`): exactly one — **#269** "feat(tools):
Paseo permission hook for Sol workers' external-directory prompts" (branch
`fix/worker-permission-policy-20261015`, opened 2026-10-15). Tooling-only
(Sol worker permission hook), no user-facing behavior; not a release hold.

**Design docs in `docs/design/` with a Status line saying proposed/blocked/held**
(first sentence quoted verbatim; ⚑ = touches shipped behavior):

1. `editor-image-upload.md`: "Status: **proposed** (drafted 2026-09-25) — a
   design spec, not a decision; **all of §17 has landed**" ⚑ — feature shipped
   (4 `editor-image-upload*.added.md` fragments; user docs in
   `docs/markdown.md`); the leading "proposed" is stale.
2. `editor-source-picker.md`: "Status: **proposed**; **Slices A, B, and C
   landed** (§11)." ⚑ — shipped slices, proposed headline.
3. `editor-vscode-adapter.md`: "Status: **proposed** (drafted 2026-09-27) — a
   design spec, not a decision; **Slices V−1 and V0 of §8 have landed**" ⚑ —
   shipped slices (adapter-contract-tests, live-snapshot-hover fragments).
4. `form-ingestion.md`: "Status: **proposed**; **no slices scoped, no code
   written**." — pure design; nothing shipped it contradicts.
5. `inline-calc.md`: "Status: **Proposed, design only; open questions
   decided.**" ⚑ — contradicted by shipped `inline-calc-spans.added.md`
   (inline calcs evaluate in check/build, user docs exist in
   `docs/math.md`); status line is stale.
6. `item-search-hover.md`: "Status: **proposed**; **no slices scoped, no code
   written**." ⚑ (verify) — `vscode-live-snapshot-hover.added.md` shipped a
   hover feature over item ids; the design doc claims nothing built. The two
   may be different hovers (live-snapshot hover came from
   `editor-vscode-adapter.md`), so flagged for a human to confirm, not
   asserted as stale.
7. `living-notes-plan.md`: "Status: Proposed — implementation plan for living
   notes; the decisions it implements are in `docs/design/living-notes.md`
   and are not reopened here." ⚑ — the plan's features (history capture,
   thread/work commands, uncaptured-edit warnings) shipped widely; status
   line stale.
8. `seal-marker-identity.md`: "Status: proposed (drafted 2026-09-27) — a
   design note, not a decision. Nothing here is landed" — consistent with
   tree (no `history.py` changes claimed as shipped).
9. `thread-workbench-w5b-plan.md`: "Status: Proposed, and **blocked on the
   owner**. Ten questions in §Open questions for Jared are open as this is
   written" ⚑ — blocked on the owner, yet `thread-workbench-values`,
   `-preview-pin`, `-task-pane`, `-squiggles` fragments shipped (per
   `docs/design/browser-editor.md`: "v1 scope has since shipped"). The
   **w5b** slice proper is open; earlier slices shipped.

No design doc carries a "held" status. `docs/design/browser-editor.md`
("architecture decided … v1 scope has since shipped") and
`editor-pdf-picker.md` ("implemented") are the honest counterparts of the
stale lines above.

---

## Verdict

| Class | Item | Evidence |
|---|---|---|
| **BLOCKER** | *(none found)* | CI green on main (`gh run list`, §6); `release.py cli 0.6.0 --dry-run` exit 0 incl. full pytest (§2); `python -m build` + `twine check` PASSED into `.scratch/dist-check` (§3); CI docs steps pass locally (`refdes build` exit 0, `gen_examples.py --check` exit 0, §4); no placeholders in package metadata (§3); CLI reference complete, nav complete (§4) |
| SHOULD FIX | 16 breaking fragments → the 0.6.0 bump is a large vocabulary/config break; release notes must lead with the rename table | §1 fragment list; `release.py` dry-run folds all 350 |
| SHOULD FIX | Stale design-doc Status lines for **shipped** features: `editor-image-upload.md`, `editor-source-picker.md`, `editor-vscode-adapter.md`, `inline-calc.md`, `living-notes-plan.md` (+ verify `item-search-hover.md`) | §7, quoted Status lines vs shipped fragments |
| SHOULD FIX | `docs-site` build warnings: `site.assets entry 'images' is not a directory`; `docs/vocabulary.md` ×3 `reference to citation ''` | `refdes build` in `docs-site/` (§4) — CI-green but warning-noisy on a release build |
| NICE TO HAVE | User-facing docs section for the editor CSV/PDF source picker (design-docs-only today) | §5 item 1 |
| NICE TO HAVE | PyPI name-availability check for `refdes` (first publish) — not checkable by any command run here | §3, stated as unverifiable |
| NICE TO HAVE | `thread-workbench-w5b-plan.md` blocked on 10 owner questions — w5b slice itself, not shipped behavior | §7 item 9 |

**Blockers: 0.** The tree is release-ready for a 0.6.0 CLI release this week,
with the caveat that the changelog folding all 16 breaking fragments demands a
prominent migration section in the release notes.
