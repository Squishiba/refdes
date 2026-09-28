# Release-readiness survey — what is actually outstanding

**Read-only audit. Nothing was fixed, resolved, folded, or bumped.** No
`CHANGELOG.md` edit, no version bump, no `release.py` run, no `changelog.d/`
fragment added, edited, or deleted. This file is the only thing written.

- Audited tree: `docs/release-readiness-audit` at `197bc7c`, 2026-09-27.
- Current version: `0.5.0` (`pyproject.toml:3`).
- `main` is 314 commits past the `0.5.0` date (2026-08-21); HEAD is
  2026-09-27.

---

## 0. Method, and what I could *not* verify

Per `AGENTS.md`, I ran the self-describing tool where I could and read code
where I could not.

- **Could not run `refdes schema` or the test suite.** This checkout has no
  installed dependencies (`ModuleNotFoundError: No module named 'pint'`) and
  no `refdes` on `PATH`. Installing was out of scope for a read-only pass, so
  **every schema claim below is from reading the YAML and Python source
  directly**, cited by file and line. I am flagging this rather than implying
  I executed the tool.
- **Did consult the live repository** via `gh` (read-only API calls) for CI
  status, Pages status, and branch existence.
- **CI is the substitute for a local test run**: `tests.yml` on `main` at
  `197bc7c` is green — 3 jobs, `conclusion: success` (run `36355019569`).

---

## 1. Category breakdown of the 127 pending fragments

`changelog.d/` holds 128 files; 127 are fragments, plus `README.md`
(which is documentation and is never folded, per `changelog.d/README.md:29`).
No fragment has a malformed name; every one matches
`<slug>.<category>.md` with a category from the documented set.

| Category | Count |
|---|---|
| `added` | 64 |
| `fixed` | 45 |
| `changed` | 12 |
| `breaking` | **6** |
| `removed` | **0** |
| **Total** | **127** |

Zero `removed` fragments. Nothing in the pending set announces a dropped
capability.

---

## 2. Every pending fragment, one line each

### Breaking (6)

| Fragment | Says |
|---|---|
| `config-split-two-files.breaking.md` | `refdes.yaml` is retired; config becomes `refdes-project.yaml` (all settings) + optional `refdes-schema.yaml` (overlay only). A leftover `refdes.yaml` fails to load. |
| `citation-path.breaking.md` | Citation `url:` becomes `path:`, scheme-dispatched (http(s) remote vs project-relative file); `refdes fetch --url` becomes `--path`; absolute paths, drive letters, `..`, symlink escapes, and `keep_copy:` on a local path are all refused. |
| `citation-vendor-keep-copy.breaking.md` | Citation `vendor:` becomes `keep_copy:`; lockfile `vendored:` → `kept_copy:`; `.refdes/vendor/` → `.refdes/copies/`; release-gate rule `missing_vendored_copies` → `missing_kept_copies`. |
| `hardware-v3-drop-in.breaking.md` | `component`'s `equivalent` verb becomes `drop_in` (self-inverse, component-only); `standard upgrade --to 3` rewrites it; a v3 project still writing `equivalent:` is a build error. |
| `sets-rename.breaking.md` | `field_sets:` renamed to `sets:`; released v1/v2 bundles keep their frozen bytes and the loader reads either key from a bundle file. |
| `calc-colon-units-retired.breaking.md` | The `name : unit = expression` calc spelling is retired and is now a build error naming the rewrite; `refdes calc-rewrite` converts a project in one transactional pass. A retired line inside a *sealed* entry is a warning, not an error. |

### Changed (12)

| Fragment | Says |
|---|---|
| `calc-cross-item-refs-hash.changed.md` | A cross-item calc reference's resolved value enters the referring item's content hash (`hash_format` 4). |
| `calc-sources-hash.changed.md` | An item with a `source()` line hashes the locked `(path, key, value)` it used (part of `hash_format` 4). |
| `extends-overlay-link-null.changed.md` | An overlay's `links: {verb: null}` on an `extends:`ing type suppresses an inherited link, instead of being popped as a no-op and then made a load error. |
| `hardware3-sets-factoring.changed.md` | hardware@3's `base.yaml` factors duplicated declarations into `grouped`/`claims`/`invalidate_body`/`statement_title`/`named_title` sets; resolved schema byte-identical. |
| `image-bytes-hash.changed.md` | `HASH_FORMAT` is 5: a referenced local image's path and content digest enter the item's content hash. |
| `libyaml-parsing.changed.md` | YAML parsing moved to libyaml for performance, with parse results and error diagnostics preserved. |
| `pdf-source-reader.changed.md` | A cited `.pdf` has a reader (behind `refdes[pdf]`), so `source()` on a PDF fails specifically rather than as "no reader for this file type"; the extra now requires `pypdf>=6.19`. |
| `prefix-mismatch-warning.changed.md` | An item id whose prefix disagrees with its declared/type prefix drops from a build-blocking error to a visible warning. |
| `revise-keys-cleanup.changed.md` | Prefix renames no longer rewrite bare references or touch the id ledger; the key pipeline runs inside the rename's transaction and refuses if a reference is still bare. |
| `serve-watches-images.changed.md` | `refdes serve` treats every file under a `site.assets:` directory as a build input for watch/rebuild purposes. |
| `theming-token-layer.changed.md` | The stylesheet gained a design-token layer (`--sans`, `--text-*`, `--space-N`, `--radius-*`, …), shipped as a provable no-op. |

`theming-two-palettes` is filed as `added.md` and is counted above under
`added`; it is called out in §2.4 because its slug and its content pull in
different directions.

### Added (64)

| Fragment | Says |
|---|---|
| `baseline-relabelled-diff.added.md` | Baseline diffs report a display-id rename as `relabelled` when baseline and current item share a surrogate key. |
| `board-conforms-to.added.md` | ① A board declares `conforms_to: [GRP-…]` for per-(item, board) coverage; ② `conforms_to:` must be a list of group ids (a bare string was iterated per character), and the warning only points at a `coverage-<board>.html` that will actually be rendered. |
| `board-includes.added.md` | A board declares `includes: [GRP-…]`; members are displayed/listed on that board's pages, never counted. |
| `browser-editor-create.added.md` | Browser-editor item creation: `plan_new_id`/`reserve_id` split, `create_item` under the write lock, three destination shapes, sealed-log "amend" as pure creation, `/api/create/*` + `/api/items/create`, a New Item form. |
| `browser-editor-links.added.md` | Structured link editing: `AddLink`/`RemoveLink` across all three list spellings, `add_link`/`remove_link` ops, a per-verb picker in the UI. |
| `calc-block-fragments.added.md` | `[[ID#calc:name]]` links to a named calc block's table; the `calc:` prefix is required; a miss warns and names what the target does have. |
| `calcblock-page-render.added.md` | `{{calcblock item=… block=…}}` renders one named block's rows on a page, never evaluates, local items only. |
| `calc-cross-item-refs.added.md` | `V_in = DEC-PWR-001.V_in` — cross-item calc references, dependency-ordered, composite-stored, cycle errors, imported items refused. |
| `calc-pipe-units.added.md` | Calcpad-style `P_mW = V_out * I_load \| mW` unit spelling, in calc blocks and in `{{P_diss \| mW}}` prose references. |
| `calc-project-equations.added.md` | Project-defined `equations:` in `refdes-project.yaml`, callable from any calc block; cycles, shadowed builtins, and arity are all errors. |
| `calc-rewrite.added.md` | `refdes calc-rewrite` transactionally rewrites retired colon-unit lines, carrying content and calc hashes forward. |
| `calc-sources.added.md` | `source("file.csv", "key")` reads a named number from a repo-local CSV, lockfile-pinned at fetch time; drift warns loudly. |
| `candidate-list-layout.added.md` | ① A dead `status:` in a file's `defaults:` warns; ② `refdes new <type> --list` prints a list-file skeleton. |
| `changelog-fragments.added.md` | The fragment workflow itself: one file per change, folded by `release.py` at release time. |
| `check-severity-status-mapping.added.md` | `check_severity:` may be a status→severity mapping with a `default:` fallback; scalar form unchanged. |
| `ci-py313-job.added.md` | The suite now also runs on Python 3.13 (ubuntu-only); the 3.11 job is unchanged on both OSes. |
| `citation-ids.added.md` | ① A citation entry may declare an `id:`, addressable as `[[cite:<id>]]`; ② `revise` reports a stale `[[ID#field]]` after a field rename. |
| `citation-section.added.md` | A citation may declare `section:`; `refdes fetch` resolves it against the PDF outline into the lockfile, sha256-guarded. |
| `compare-block.added.md` | `{{compare}}` renders a candidate-comparison table of recorded check outcomes, display-only. |
| `docs-update.added.md` | User-facing doc updates for `relabelled`, composites, `--no-write`, `keys adopt`, keys/corruption diagnostics, hash versioning, board manifest, log ordering, schema.json staleness. **See §4.3 — its hash-format number is wrong.** |
| `edited-after-captured.added.md` | `check`/`build` warn when an item captured into `.refdes/history/` has since been edited; a warning, never an error. |
| `editor-edit-ui.added.md` | The browser editor can edit an existing item: an `edit` block on the read route, `POST /api/item/<ref>/edit`, draft/unsaved/conflict UI. |
| `editor-image-picker.added.md` | Phase 0: an image picker listing `site.assets:` images with thumbnails, inserting a relative src into the draft. |
| `editor-image-upload.added.md` | Phase 1: `POST /api/assets` byte uploads, type sniffed from bytes, `.svg` refused, 8 MiB cap, `_atomic_create`. |
| `editor-image-upload-conflicts.added.md` | Phase 2: `expected_hash` replace path, refusal on search-path ambiguity and on silently re-pointing a bare-name reference, `referenced_by` blast-radius disclosure. |
| `editor-image-upload-seals.added.md` | Phase 3: an upload *for* a sealed entry, or a create/replace of a file a sealed entry references, is refused (422, not 409). |
| `field-fragment-refs.added.md` | `[[ID#field]]` / `[[ID#field\|label]]` links to a field's row; never inlines the value. |
| `follows-capture.added.md` | A writable load that freezes a `follows:` edge also captures the predecessor's snapshot as a `followed` event. |
| `history-commands.added.md` | `refdes history capture` / `redact` / `migrate-seals`, all refusing under `--no-write`. |
| `import-keys.added.md` | Imported `items.json` artifacts carry surrogate keys, so cross-project links freeze to composites. |
| `key-baseline-lint.added.md` | `refdes check` rejects a key changed or removed from an item still carrying the display id of the latest baseline. |
| `key-corruption-lint.added.md` | `refdes check` rejects malformed keys, duplicate keys, and composite links whose well-formed key no item declares. |
| `key-label-refresh.added.md` | Stale display labels in composites refresh after a rename; ambiguous rewrites are refused. |
| `keys-adopt.added.md` | `refdes keys adopt [--dry-run]` mints keys, expands composites, re-keys baselines and seals, transactionally, with a committed `.refdes/keys-adopted.yaml` marker. |
| `named-calc-blocks.added.md` | Named calc blocks (```` ```calc id="losses" ````), an anchor, a caption, uniqueness as an error, and a now-validated fence info string. |
| `named-calc-blocks-docs.added.md` | Docs for the `id="…"` fence attribute, the validated info string, and the fence errors. |
| `named-calc-blocks-links-blocks-docs.added.md` | Docs for `[[ID#calc:name]]` in `links.md` and `{{calcblock}}` in `blocks.md`. |
| `pdf-source-picker.added.md` | The editor's source picker browses a cited PDF page: positioned text runs, rows, and every number as an unselected candidate; bounded reads; read-only (no picking yet). |
| `schema-doc-key.added.md` | `doc:` is a recognised definition key on types, fields, field-set entries and link types, exported as JSON Schema `description`. |
| `serve.added.md` | `refdes serve` — loopback-only preview server from a temp dir, per-launch token, no writes on load; the editor app lands later. |
| `serve-editor-read.added.md` | The editor's read side: `GET /api/items` (fully combinable, counted, URL-held filters) and `GET /api/item/<ref>`; the `/edit/` shell. |
| `sets-carry-links-body.added.md` | `include:` composes a whole slice of a type — `fields:`, `links:` and `body:` — merging in include-list order, the type's own declaration last. |
| `source-picker-accept.added.md` | Accepting a picked source value writes the item and `.refdes/citations.yaml` in one `set_body` + `pin` request under the write lock; re-validated; lockfile written atomically; rollback on any failure. |
| `source-picker-reads.added.md` | The picker read side: `sources.list_entries()` plus three GET endpoints, authorized by `citations.authorize_source_path()`, bounded, read-only. |
| `standard-definitions.added.md` | Every `hardware@3` term defines itself via `doc:` (71 definitions), with `tests/test_standard_docs_complete.py` as the completeness lint. **See §5.3 — the count is worth a glance.** |
| `status-link-disagreement.added.md` | A build warns when `supersedes`/`selects` and the paired `status` disagree; a warning, never a rewrite. |
| `theming-site-theme-tokens.added.md` | `site: theme:` and `site: tokens:`; unknown token names are build errors with a did-you-mean; overrides merged *over* the default; generated `assets/theme.css`; un-themed builds byte-identical. |
| `theming-two-palettes.added.md` | ① Three built-in themes (`high-contrast`, `paper`, `slate`) plus a generated gallery; ② `light:`/`dark:`-scoped `site: tokens:`; ③ verdict colours overridable with a load-time contrast check; ④ a light override no longer bleeds into dark mode. |
| `thread-workbench-preview-pin.added.md` | W1: preview pages carry a response-only reload probe and an "Open preview" link. |
| `thread-workbench-squiggles.added.md` | W2: response-only preview decorations — a diagnostics panel (D3) and image provenance markers (D2). |
| `thread-workbench-values.added.md` | W3: response-only inline calc-value attribution with a values toggle; nothing re-evaluated. |
| `threads-chain-diagnostics.added.md` | `follows:` chains are walked: current tip, per-field fold, fork `info`, cycle error. |
| `threads-coverage.added.md` | Thread-aware coverage and `{{index}}` use a silent entry's current thread status; id-less entries resolve via keys. |
| `threads-follows-freeze.added.md` | Bare `follows:` references freeze to the current tip on writable loads, labels refreshed after renames. |
| `threads-identity-phase1.added.md` | An item with no `id:` but a non-empty `follows:` is a full project member from the moment it parses. |
| `threads-rendering.added.md` | An item continuing another renders a Thread section: a "currently concludes" panel plus the whole timeline. |
| `tree-group-subtype.added.md` | A type that `extends: group` behaves as a group in the tree. |
| `tree-scoped.added.md` | ① `{{tree}}` gains `board=`/`workspace=`/`depth=` (`via=` deliberately refused as cascade's job); ② `tree-<board>.html` / `tree-<workspace>.html` join the scoped report set; ③ a board node's count tallies only what it owns ("1 own, 2 shared"). |
| `tree-view.added.md` | A generated `tree.html` — workspace → board → group → item, expand-once, a `Project-wide` bucket, `<details>` collapse, no JS. |
| `vocabulary-diagram.added.md` | One small inline-SVG diagram per item type beside its heading, plus a coverage spine; `refdes schema --graph` now emits these. Hand-rolled layout, no library, no Mermaid. |
| `vocabulary-page.added.md` | Every built site gets `vocabulary.html` generated from the *resolved* schema, with the `doc:` definition per term. |

### Fixed (45)

| Fragment | Says |
|---|---|
| `agents-field-sets-word.fixed.md` | `AGENTS.md`'s overlay sentence now says `sets:` and names `field_sets:` as the retired spelling. **See §7.1 — the same sentence is still wrong in two other files.** |
| `audit-uncomparable.fixed.md` | `refdes audit` reports un-migratable older-format entries on an `uncomparable N` line instead of folding them into `changed`. |
| `board-manifest-keys.fixed.md` | Board/workspace membership drift is keyed by immutable surrogate after `keys adopt`; legacy manifests stay compatible. |
| `calc-domain-errors.fixed.md` | A calc line leaving the reals (`sqrt(-1)`, `ln(0)`, `exp()` overflow, fractional power of a negative) is a diagnostic on its line, not an unhandled `TypeError` that killed the build. |
| `calc-rewrite-tolerance.fixed.md` | `calc-rewrite` no longer refuses the very line its own build error points it at (`P : W ± 10% = V * I`). |
| `cli-load-errors.fixed.md` | `index`/`ls`/`id`/`audit`/`former-ids propose` all print load errors; `ls`/`id`/`audit` exit 1 (`index` deliberately still exits 0 for the VS Code extension). |
| `cli-reference-audit.fixed.md` | Six CLI-reference corrections, incl. the top-level usage line, `build -v`, and two behaviours documented as broken (a quoted `id:` hint; `check`/`id --dry-run` writing). |
| `cli-reference-audit-2.fixed.md` | Seven more CLI-reference corrections (audit sections, `new --list`, `schema --graph`, `standard`/`init` exit codes). |
| `cli-reference-audit-3a.fixed.md` | Six more, incl. `revise` cannot do a type/required-field rename on a hand-rolled schema in either order, and `calc-rewrite` cannot rewrite a tolerance line (documented as a hand edit). |
| `cli-reference-audit-3b.fixed.md` | Six more, incl. the surrogate-key `former-ids propose` line and three `history` subcommand behaviours. |
| `config-unknown-keys.fixed.md` | Every nested block of both config files is validated with a did-you-mean. **A project with a previously-ignored typo will now fail to load — stated plainly in the fragment.** |
| `date-format-log-sort.fixed.md` | `date_format:` project setting; design-log dates validated and sorted chronologically instead of as raw strings. |
| `deleted-key-report.fixed.md` | A hand-deleted `key:` is reported as `key deleted` (load warning + build error) rather than silently re-minted as `key changed`; evidence preserved. |
| `design-doc-statuses.fixed.md` | Design-doc status lines corrected: `candidate-parts.md` all five phases, `named-calc-blocks.md` all five, `thread-workbench.md` W1/W2 landed + W3 in progress, `browser-editor.md` no longer claims there is no test CI. |
| `docs-audit-batch1.fixed.md` | Eleven docs corrections (a `text`→`body` example, `math.md`'s display-units table, two dead `[below](#…)` anchors, a "six standard types" claim, a `follows:` claim, and more). |
| `docs-audit-core.fixed.md` | Ten more docs corrections, incl. eleven `text:` examples across two pages and the display-title precedence order. |
| `docs-audit-lifecycle-batch.fixed.md` | Ten more, incl. the baseline-file example and the `extends:` example that cannot load under hardware@3. **Its last bullet is now false — §4.4.** |
| `dry-run-load-writes.fixed.md` | `id --dry-run` and `stub-tests --dry-run` no longer write on the way in; a dry run is `--no-write` for the whole run. |
| `editor-focus-rerender.fixed.md` | The editor carries field controls, caret and selection across a rebuild that lands mid-edit. |
| `esc-single-quote.fixed.md` | Generated HTML escapes `'` as well. |
| `figure-attr-typo.fixed.md` | An unknown image attribute name warns instead of doing nothing in silence. |
| `fetch-load-errors.fixed.md` | `refdes fetch` prints load errors, exits 1, and says citations in unparsed files were not processed. |
| `follows-docs-honesty.fixed.md` | The docs stop presenting `follows:` as a verb an author can write today (no bundled standard declares it). |
| `id-hint-write-back.fixed.md` | ① `refdes id` replaces a numeric `id:` hint in place, wherever it sits; ② it no longer converts a CRLF file to LF. |
| `inline-image-attrs.fixed.md` | An image attribute suffix on an image that is not alone in its paragraph applies `width=` and warns that `caption=`/`id=` are dropped. |
| `links-part-of-row.fixed.md` | `docs/links.md`'s verb table now lists `part_of`. |
| `load-time-write-flow-guard.fixed.md` | A flow-style one-line Markdown front matter is no longer destroyed by key minting; a backstop restores any file a load-time write broke. |
| `log-figure-refs.fixed.md` | Figure references resolve inside log entry bodies. |
| `micro-sign-display.fixed.md` | A micro value's rendered unit is U+00B5 on every interpreter, not whatever pint happens to spell. |
| `no-write-complete.fixed.md` | `--no-write` now suppresses *every* write across load/check/build; explicit write commands either dry-run or refuse with exit 2. |
| `no-write-help-calc-rewrite.fixed.md` | The global `--no-write` help text now lists `calc-rewrite`, with a test pinning the set. |
| `overlay-markdown.fixed.md` | `parse_markdown_file` reads through `read_source`, so a candidate `.md` edit is validated against the overlaid bytes. |
| `patcher-crlf-body-final-break.fixed.md` | Editing a body in a CRLF file no longer writes a stray CR; the patcher refuses any plan introducing a CR outside a line break. |
| `patcher-crlf-insert.fixed.md` | Inserting a field in a CRLF file no longer splits a line break. |
| `propose-old-title.fixed.md` | `former-ids propose` no longer prints an empty old title for surrogate-key pairings. |
| `revise-flow-style-values.fixed.md` | `revise` now rewrites `type:`/`section:`/`prefix:`/`id:` written in flow style, and refuses rather than half-rewriting. |
| `revise-link-target-verb.fixed.md` | A link rename onto a verb the project does not have is refused up front instead of silently un-inking every edge. |
| `revise-missing-mapping.fixed.md` | `revise` on a missing/unparseable mapping file is a one-line error and exit 2, not a traceback. |
| `seal-skips-error-entries.fixed.md` | A new append-only entry with an ERROR attributed to it is not sealed, and is reported once. |
| `source-line-endings.fixed.md` | Six line-ending fixes: no write-back normalizes a mixed file, `former-ids confirm` keeps CRLF, `standard upgrade`/`add-preset` don't restyle the config, editor-created items and `stub-tests` don't inject CRLF, and the tool's own state files are platform-independent. |
| `standard-library-type-count.fixed.md` | `standard-library.md` said six types; hardware@3 ships seven (`group` added). |
| `tree-block-nested-anchors.fixed.md` | `{{tree}}` no longer emits an anchor inside an anchor (`_linkify` now skips `<a>` regions). |
| `tree-board-home.fixed.md` | The tree files a boarded item under its own board, not its first group. |
| `vscode-activation-project-marker.fixed.md` | The VS Code extension activates on `refdes-project.yaml` again instead of the retired `refdes.yaml`. |

---

## 3. Version-number convention (measured, not guessed)

This project is pre-1.0, and **every released version that carried breaking
changes was a minor bump in the `0.x` line.** Measured from `CHANGELOG.md`'s
own history:

| Version | Date | Has a `### Breaking` section? |
|---|---|---|
| `[0.5.0]` | 2026-08-21 | yes — `CHANGELOG.md:552` |
| `[0.4.0]` | 2026-08-18 | yes — `CHANGELOG.md:810` |
| `[0.3.0]` | 2026-08-11 | yes — `CHANGELOG.md:887` |
| `[0.2.1]` | 2026-08-11 | no |
| `[0.2.0]` | 2026-08-11 | no |
| `[0.1.0]` | 2026-08-10 | no |

**So the convention is not abstract semver — it is observed three times: in
`0.x`, breaking ships as a minor bump. The one patch release (0.2.1) carries
no breaking section, which is the patch lane.** With **6 pending breaking
fragments**, this release is on the `0.x` breaking lane, and by this project's
own history that is a **`0.5.0` → `0.6.0`** shape, not a patch.

Whether the scope should be narrowed to fit a different number is Jared's
call; this section only records the measured convention.

---

## 4. Cross-check: pending fragments against the already-folded `[Unreleased]`

The folded `[Unreleased]` (`CHANGELOG.md:8-337`) is *not* the same story as
the pending set. Five things need a human before a fold.

### 4.1 Three disagreeing accounts of "what changed in hardware@3"

This is the most consequential finding in this report.

| Source | Says hardware@3 changes are |
|---|---|
| `CHANGELOG.md:27` (already folded) | **"Five changes"** — ① `governed_by` ② `satisfies` widening + `component.constrained_by`/`checks` ③ `text`/`method` → `body` ④ `citations` field set + `datasheets:` → `citations:` ⑤ `decision.recorded_by: [log]` |
| `src/refdes/standards/hardware/v3/base.yaml:11` | **"in four parts"** — then enumerates **five** (`base.yaml:12-99`): ① `governed_by` ② `satisfies` widening ③ `text`/`method` → `body` ④ **`group` type** ⑤ **`equivalent` → `drop_in`** |
| the pending `changelog.d/` fragments | at least **seven more**: `group` type (`hardware-v3-group-type.added.md`), `drop_in` (`hardware-v3-drop-in.breaking.md`), `component.status: rejected` + status-keyed `check_severity` (`hardware-v3-rejected-status.added.md`), sets factoring (`hardware3-sets-factoring.changed.md`), `field_sets:` → `sets:` (`sets-rename.breaking.md`), `url:` → `path:` (`citation-path.breaking.md`), `vendor:` → `keep_copy:` (`citation-vendor-keep-copy.breaking.md`) |

`base.yaml:11` is internally inconsistent with its own body: it says **four**
parts and then lists **five** numbered items. That is a one-word defect in the
file that ships as part of hardware@3.

The folded changelog enumeration and `base.yaml`'s overlap on three items and
diverge on the other two in each direction: the changelog names
`citations`-as-a-field-set and `recorded_by`, which `base.yaml`'s header never
mentions; `base.yaml` names the `group` type and the `drop_in` rename, which
the changelog's list never mentions. **All three lists are incomplete or wrong
relative to each other.** A reader of the release notes would not learn that
`group`, `drop_in`, `rejected`, `url:`→`path:`, `vendor:`→`keep_copy:` or
`field_sets:`→`sets:` are part of the same standard bump.

The v3 `base.yaml` itself does contain the newer material (read directly):
`drop_in` is declared at `base.yaml:181`, `component.status` choices are
`[candidate, selected, rejected, obsolete]` with the status-keyed
`check_severity` at `base.yaml:259`, and the `sets:` key is at
`base.yaml:110`. So the *code* is ahead of all three *prose* lists.

### 4.2 The folded entry names a key that is now a hard error

`CHANGELOG.md:61` describes the citations change as moving into "an
includable **`field_sets:`** entry". `sets-rename.breaking.md` renames that
key, and `src/refdes/schema.py:255-257` now hard-errors `field_sets:` in a
project file with a message naming `sets:`. Folding the fragments as-is would
publish, in the same release, a changelog entry instructing a reader to write
a key that same release forbids.

### 4.3 A pending fragment states a hash format two behind

`docs-update.added.md:8` says "Content hash versioning (`hash_format`,
**currently 3**)". The code is at **`HASH_FORMAT = 5`**
(`src/refdes/build.py:1468`), and two *other* pending fragments describe the
intermediate steps — `checks-against-keys.fixed.md` (→ 3),
`calc-sources-hash.changed.md` and `calc-cross-item-refs-hash.changed.md`
(both → 4), `image-bytes-hash.changed.md` (→ 5). Folding all of them produces
a changelog reading 2 → 3 → 4 → 5 as a correct progression, *except* for one
entry asserting "currently 3" as a present-tense fact. Note the folded
`CHANGELOG.md:144` still says `HASH_FORMAT = 2`.

### 4.4 A pending fragment's last bullet documents a bug that no longer exists

`docs-audit-lifecycle-batch.fixed.md` ends with:

> "Docs: `docs/output.md` carries the same unloadable `site.tokens` example …
> **Not fixed here — that page is outside this audit's scope.**"

`docs/output.md:33-38` has since been corrected to a legal bare-pair-only
form, matching what `schema-reference.md:64-70` now shows. Folding this
fragment would publish a claim that `docs/output.md` is broken when it is not.
The fragment's other bullets are fine.

### 4.5 Two folded entries forward-reference the fragments about to be folded

`release.py` deletes the fragment files as it folds them
(`changelog.d/README.md:3-6`), so these two pointers will dangle:

- `CHANGELOG.md:184` — the surrogate-keys layer-2 entry says the four
  still-design-only items "have since shipped — see the `changelog.d/`
  fragments (`key-corruption-lint.added.md`, `keys-adopt.added.md`,
  `key-label-refresh.added.md`, `revise-keys-cleanup.changed.md`)". All four
  are pending and will be folded into the same section.
- `CHANGELOG.md:104` — the `extends` phase-3-4 entry says an overlay null
  "suppresses it (see the changelog fragment `extends-overlay-link-null`)".
  That fragment is pending too.

Both are harmless if the fragments land adjacent, and slightly wrong if they
don't. Either way it is a hand-edit decision, not a `release.py` one.

### 4.6 Checked and cleared

- The `extends` phase-1 entry says "Nothing in hardware@3 uses it yet" while
  the phase-3-4 entry above it says `bound` now `extends: requirement`. The
  phase-1 sentence was true when written and the later entry supersedes it; it
  reads as a progression, not a conflict. Minor.
- No pending fragment duplicates a *feature* already described in the folded
  `[Unreleased]`. The overlaps are the two forward-pointers in §4.5 and the
  hash-format chain in §4.3.

---

## 5. hardware@3: is it internally complete?

### 5.1 No dangling TODO / FIXME / "not yet implemented" in the standard

`grep -rniE "todo|fixme|not yet|not implemented|open question|undecided|XXX|HACK"`
over `src/refdes/standards/hardware/v3/` returns **exactly one hit**, and it
is a false positive: `v3/presets/design-debate.yaml:16` uses the phrase "an
open question" as part of a `doc:` definition of the `question` type ("An open
question the design is arguing about…"). **The v3 standard carries no
unfinished-work marker of any kind.** On that narrow question it is clean.

### 5.2 The `doc:` completeness gate exists and is wired

`standard-definitions.added.md` claims every v3 term defines itself and that
`tests/test_standard_docs_complete.py` fails when one does not. That test file
**exists**. Every declaration sampled in `base.yaml` carries a `doc:`
(`component`'s type, its fields, its links and its `include` list; the whole
`group` type following it). Prose and code agree here.

### 5.3 One count worth a glance

`standard-definitions.added.md` says "**71 definitions** in total" across
`base.yaml` and the `design-debate` preset. Counting raw `doc:` occurrences
gives **56 in `base.yaml` + 18 in the preset = 74**. The two are probably
reconcilable — `base.yaml:113-115` states that a set's own `doc:` "is never
resolved onto a type", so some of the 74 are set-level and not counted as term
definitions — but the fragment does not say so, and a reader counting will land
on 74. Low stakes; a one-word clarification would settle it.

### 5.4 Loose edges around the standard

- `base.yaml:11` says "four parts" and lists five (§4.1). This is the one
  internal inconsistency in the file that ships.
- `migration.yaml:8-12` describes "v3's other changes" as the `governed_by`
  verb, the `satisfies` widening, and `component`'s `constrained_by`/`checks`.
  It omits the `group` type (also additive) and the `sets:` factoring, so the
  migration file's own account of its sibling's delta is incomplete.
- `refdes standard upgrade --to 3` is the migration path for **four** renames
  (spelled across three fragments: `datasheets:`→`citations:`,
  `equivalent:`→`drop_in:`, `url:`→`path:`, `vendor:`→`keep_copy:`). I read
  `migration.yaml` and all four are present (`links:`, `fields:`,
  `citation_keys:` at the file's end). The `vendor:`→`keep_copy:` rename is
  the one that shipped under **a released** version (hardware@2, v0.3.0–v0.5.0
  per its own fragment), so it is the one most likely to have a real migrating
  project in front of it.

---

## 6. Stale `Status:` lines in `docs/design/backlog.md`

The file's own header says it was "Verified against the actual codebase as of
commit `e73ffea` (2026-09-15, `main`)" (`backlog.md:12`). Two problems with
that header before any individual entry: **`e73ffea` is dated 2026-09-14, not
the 15th**, and **HEAD is 210 commits past it.** Ten Status lines are stale
against the current tree. Each was verified by reading the code, not the prose.

| Finding | Line | What the Status line claims | What I verified |
|---|---|---|---|
| **15** | `backlog.md:334` | "**No implementation exists.**" (the browser editor) | **Shipped, substantially.** `src/refdes/serve/` is a 10-module package (`api.py`, `edit.py`, `filters.py`, `preview.py`, `security.py`, `server.py`, `sources.py`, `state.py`, `upload.py`, `static/`). `serve` is registered at `src/refdes/cli.py:1368`. The read side, the edit UI, link editing, and item creation are all pending fragments describing shipped code. |
| **16** | `backlog.md:360-361` | "`docs/design/threads.md` (**design only, not implemented** — see its own status header)" | **Stale.** `docs/design/threads.md:17` now reads "**Status: Phase 3a implemented.**" Five threads fragments are pending. `src/refdes/chains.py` is a 31 KB module whose docstring is "`follows:` chain walk: tips, the per-field fold, fork and cycle diagnostics". |
| **17** | `backlog.md:396-397` | "`threads.md` is itself **design only** — nothing in it is implemented" | **Stale, same evidence as #16.** The paragraph's conclusion ("if this work happens, it happens as `threads.md`") is still right; the premise is not. |
| **26** | `backlog.md:844` | "**Status: outstanding — design drafted, awaiting review.** No `xlsx`/`csv`/`openpyxl` reference exists anywhere in the package" | **Shipped.** `src/refdes/sources.py` exists (a CSV reader: `extensions = (".csv",)` at line 215, `csv.reader` at line 450). `calc.py:643` and `calc.py:1601` carry the `source("cited/file.csv", "key")` grammar. `calc-sources.added.md` and `calc-sources-hash.changed.md` are pending. The *design* status has also moved on independently: `docs/design/calc-sources.md:1-3` reads "**Status: Reviewed** — Jared's decisions recorded 2026-09-19; question 2 … decided 2026-09-21 … All section 11 questions are now answered." |
| **33** | `backlog.md:1402-1403` | "Nothing here is implemented yet; `includes:` still appears nowhere in the package." | **Shipped.** `src/refdes/boards.py:118-153` is a dedicated `includes:` resolver (`spec.includes`, `validate_includes()`, and an explicit comment that it must never be used "where a number is produced"); `src/refdes/model.py:174` carries `includes: list[str]` on the board spec. `board-includes.added.md` is pending. |
| **34** | `backlog.md:1426-1428` | "the editor does not exist yet (`cli.py:1182-1520` registers build/check/revision/release/index/ls/id/fetch/audit/init/new/schema/standard/keys/revise/stub-tests/former-ids — **there is no `serve`**)" | **Stale twice over.** `serve` is registered at `src/refdes/cli.py:1368`, alongside `keys` (1675), `calc-rewrite` (1716), and `history` (1788) — all three of which the line also omits. |
| **34** | `backlog.md:1652-1653` | "Implementation not started." (theming) | **Shipped in three steps.** `src/refdes/theme.py` and `src/refdes/contrast.py` exist. Three pending fragments: `theming-token-layer.changed.md` (the token layer), `theming-site-theme-tokens.added.md` (step 2a), `theming-two-palettes.added.md` (step 2b). `docs-site/gen_themes.py` and `tests/test_style_tokens.py` both exist. |
| **37** | `backlog.md:2478` | "The tree page already exists (`src/refdes/tree.py`)." | **Accurate**, and the entry is further along than "already exists" suggests — `tree.py` exists and `{{tree}}` is registered at `src/refdes/blocks.py:880` beside `calcblock`/`compare`/`index`/`cascade`, with four pending tree fragments. The "decided" framing understates it but claims nothing false. Low priority. |
| **38** | `backlog.md:2589-2591` | "The embedded diagram **is still stale** — `grep -n part_of docs/links.md` matches the table row and the `hardware@3` note under it, never the diagram" | **Stale.** `grep -n "mermaid\|graph TD\|flowchart" docs/links.md` returns **nothing**. The checked-in Mermaid block is gone, replaced by a pointer to the generated vocabulary page (`docs/links.md:93-103`), and `vocabulary-diagram.added.md` is pending. The paragraph's *argument* — generation is not what keeps a document honest, nothing regenerates a checked-in diagram — is intact and was proved twice; only the "still" is wrong. |
| **1** | `backlog.md:101-113` | "**Status: shipped, not yet deploying.** … every run since it was added (56 runs, first 2026-08-22) fails at `actions/configure-pages` … the repository has Pages disabled (`has_pages: false`)" | **Stale, verified live.** `gh api repos/Squishiba/refdes` returns **`has_pages: true`**. The last five `docs.yml` runs are all `conclusion: success`, most recently run `36355019569` at 2026-09-27T22:21:45Z on `main`. The fix is no longer outstanding. |

### 6.1 The same staleness class outside the backlog

- **`AGENTS.md`'s surrogate-keys paragraph is now wrong the same way.**
  `AGENTS.md:24-25` says the corruption lint, `refdes keys adopt`, the
  display-half refresh-on-rename, and any `revise.py`/`former_ids.py` change
  are "still design only". All four are shipped: the corruption lint is
  `malformed_key_message()` at `src/refdes/keys.py:117-145`; `keys adopt` is
  `cmd_keys_adopt` at `src/refdes/cli.py:1012` over `src/refdes/adopt.py`;
  the refresh is `links.py:462-469` ("Expand bare link targets and refresh
  stale composite display halves"); and `revise.py` no longer contains
  `_rewrite_reference_ids`, `_rewrite_block_sequence`, `_rewrite_id_tokens`,
  `_relabel_id`, `_relabel_ledger`, `_restore_ledger`, or the burned-prefix
  check (grep returns nothing), with `_rename_prefix` surviving as the
  id/prefix-line helper. The folded `CHANGELOG.md:184` already says so
  explicitly — so `AGENTS.md` and the changelog currently disagree.
- **`docs/design/extends.md:507` and `:515` are *not* stale** — checked, and
  they are inside a fenced block quoting the *history* of a Status-line
  rewrite, not live status. Worth stating so nobody "fixes" them.
- **`docs/design/calc-sources.md:14`** writes its headline example in the
  **retired** calc spelling: `eff : 1 = source("analysis/power-budget.csv", …)`.
  `calc-colon-units-retired.breaking.md` makes that a build error, and
  `docs/math.md` documents the pipe form. The design doc's own example would
  now fail its own build.

---

## 7. Fragments describing something that isn't actually in the tree

### 7.1 No fragment references a PR, branch, commit, or issue

Checked mechanically: `grep` for 7-hex commit hashes, `#<number>` issue/PR
references, and `owner/branch`-shaped tokens across all 127 fragments returns
**zero** hits of any kind. Every `owner/name` token that matched is a real
file path (`.refdes/citations.yaml`, `refdes/schema.json`, …). Every
`docs/…md` path referenced by a fragment exists (22/22). So there is **no
fragment written for reverted, abandoned, or never-merged work** detectable by
reference — that class of problem is absent.

### 7.2 But the `field_sets:` → `sets:` rename was applied to one of three files

`agents-field-sets-word.fixed.md` fixes the retired-key sentence in
`AGENTS.md`. The **same sentence, saying the same wrong thing**, survives in
two other files:

- `refdes-project.yaml:8` — "the project's own schema overlay (types:,
  link_types:, **field_sets:**)"
- `refdes-schema.yaml:4` — "it holds `types:`, `link_types:` and
  **`field_sets:`** and nothing else"

`refdes-schema.yaml` is the repo's own canonical example of the optional
overlay file, and its header is what a reader copies. `AGENTS.md:14-17` now
correctly says `sets:`. `src/refdes/schema.py:255-257` confirms `field_sets:`
is a hard error in a project file. Not a load failure (both occurrences are
comments), but the fix applied to `AGENTS.md` was applied to one of three
places.

`src/refdes/standards/hardware/v1/base.yaml:11` and `v2/base.yaml:56` also
carry `field_sets:`, and that one is **correct** — `standards.py:135-142`
documents that released bundles predate the rename and the loader reads either
key from a bundle file.

Two design docs still use `field_sets:` throughout
(`docs/design/standard-library.md`, `docs/design/composition.md`), and
`base.yaml:6` points readers at `standard-library.md` as "the full design
discussion behind every choice here". Design docs are historical records, so
this may be deliberate — but `standard-library.md:59,77,207,218,714,721`
presents `field_sets:` in the present tense as the way to author a set.

### 7.3 Everything else I sampled exists

Every module, test file, docs-site script and static asset named by a
fragment is present: `tests/test_standard_docs_complete.py`,
`tests/test_style_tokens.py`, `tests/test_image_search.py`,
`tests/test_citation_ids.py`, `tests/test_text_node_escaping.py`,
`docs-site/gen_themes.py`, `docs-site/gen_examples.py`,
`serve/static/{preview,app,controls}.js`, `serve/{sources,upload,edit}.py`.
The block registry at `src/refdes/blocks.py:856-880` carries all five blocks
the fragments describe (`calcblock`, `compare`, `index`, `cascade`, `tree`).

---

## 8. CI signal

`tests.yml` on `main` at `197bc7c`: **green**, 3/3 jobs (run `36355019569`).
The last Windows-leg failure was run `36352381579` at 2026-09-27T21:37:05Z,
commit `58e0183`:

```
FAILED tests/test_serve_edit_http.py::test_edit_requires_a_matching_origin[http://evil.example]
  ConnectionAbortedError: [WinError 10053]
1 failed, 2500 passed, 1 skipped in 186.56s
```

**This is a flake, not a regression**: the identical content was green on its
PR run (`36352062042`, sha `2f50ed0`), and the two pushes after it were green.
The signature is a test that sends a request with a bad `Origin` and expects a
refusal response, losing the connection on Windows before the response
arrives. It is the first thing to look at if a release gate needs a clean
matrix, and it sits in the same area the pending `serve-editor-read` and
`editor-*` fragments are working in.

Per `AGENTS.md`, `ruff check .` is **not** a valid gate today (~99 pre-existing
findings). `tests.yml` correctly scopes ruff to `--select E9,F src tests`, and
that step passed.

---

## 9. Open questions that need a human before a release could safely happen

None of these are recommendations about *when* to release. Each is a
discrepancy whose resolution is not mine to choose.

1. **Which enumeration of the hardware@3 delta is authoritative** — the
   changelog's five, `base.yaml`'s "four" (listing five), or the fragments'
   seven-plus? And is `base.yaml:11`'s "four parts" a typo for "five", or is
   one of the five items in that header wrong? *(§4.1)*
2. **Whether `CHANGELOG.md:61` gets hand-edited** from `field_sets:` to
   `sets:` before folding, since the same release makes the old key a hard
   error. *(§4.2)*
3. **Whether `docs-update.added.md:8`'s "currently 3" is corrected to 5**, or
   left as a historical statement with the intermediate fragments supplying the
   chain. *(§4.3)*
4. **Whether `docs-audit-lifecycle-batch.fixed.md`'s final bullet is dropped**
   as obsolete, since the `docs/output.md` defect it reports has been fixed.
   *(§4.4)*
5. **What happens to the two folded forward-pointers** at `CHANGELOG.md:104`
   and `CHANGELOG.md:184` once `release.py` deletes the files they name. *(§4.5)*
6. **Whether the stale Status lines in §6 and §6.1 are corrected as part of
   this release or left**, given that `AGENTS.md` and the folded
   `CHANGELOG.md:184` currently contradict each other on whether the keys
   layers shipped.
7. **Whether all six breaking fragments belong in one release**, given the
   measured `0.x` convention puts breaking on the minor lane (§3) and two of
   the six (`url:`→`path:`, `vendor:`→`keep_copy:`) affect projects that are on
   **already-released** hardware@2 and therefore have real content to migrate.
8. **Whether the Windows `serve` HTTP flake is fixed before a gate runs** (§8).

---

## 10. Explicitly not done

Per the brief and `AGENTS.md`: no fix, no resolution, no cleanup.
`CHANGELOG.md` untouched, `pyproject.toml` version untouched, `release.py` not
run, no `changelog.d/` fragment created, edited, or deleted, no backlog Status
line corrected, no code changed. This file is the entire deliverable.
