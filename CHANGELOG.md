# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Project lifecycle: `refdes revision <name>` cuts an internal checkpoint
  unconditionally (past the always-on error floor); `refdes release <name>`
  runs the full readiness gate and stamps only if it passes -- on failure it
  writes nothing and prints exactly what's blocking, since running it when
  you're not ready *is* the check (neither command takes flags). Both write
  `.refdes/baselines/<name>.yaml`, a content-hash snapshot of every local
  item -- re-stamping the same name with identical content is a no-op,
  with different content it's an error, since a name is a permanent label
  once written. The seven `release_gate:` rules (already parsed from
  `refdes-project.yaml`) are wired up: `draft_items`, `unpinned_citations`,
  `missing_vendored_copies`, `uncovered_requirements`,
  `unverified_requirements` (off by default for `release` -- boards go to
  fab to get tested), `info_check_failures`, and `unaccepted_board_moves`.
  `stamped_by` defaults to the OS username with zero git involvement;
  `baseline_identity: git_identity` opts into `git config user.name`,
  warning and falling back rather than erroring if it can't be resolved.
  `refdes audit` reports what's changed since the last revision (either
  kind) and since the last release (specifically) -- this is deliberately
  not the git-history layer: both are a directory scan and a hash
  comparison, no git object ever read. See
  [project lifecycle](docs/lifecycle.md).
- The standard schema library: a bundled `hardware@1` dictionary (six item
  types -- `requirement`, `constraint`, `decision`, `test`, `component`,
  `log` -- their fields, status lifecycles, and thirteen-verb link
  vocabulary) resolved live, by reference, into any project declaring
  `standard: {base: hardware, version: 1, presets: []}` in `refdes.yaml`.
  `refdes.yaml` never contains a copy of the standard's `types:`/
  `link_types:`/`field_sets:` -- only the pointer -- and the project's own
  overlay merges on top (add a field, remove one, redeclare an enum, add or
  remove a whole type, with a load-time error if the removal breaks
  something still relied on). `standard: none`, or omitting `standard:`
  entirely, is the explicit escape hatch: today's fully self-declared
  behaviour, unchanged. See [the standard library](docs/standard-library.md).
- `field_sets:`/`include:`: named, reusable groups of field definitions
  pulled into a type instead of retyped on each -- the mechanism the
  standard is itself authored with (`provenance`, `stewardship`), also
  available to a project's own custom types.
- An optional `design-debate` preset (`debate`/`option`/`claim`/`position`),
  bundled but not enabled by default, opted into with
  `standard.presets: [design-debate]`. Presets are peers: purely additive
  against the base and each other, with a name collision a hard load-time
  error naming both sides.
- `coverable:`, `coverable_statuses:`, and `verifying_statuses:` on any
  `types:` entry (standard or bespoke) -- engine-level coverage flags, not
  standard-specific plumbing. They replace three previously hardcoded
  behaviours in `compute_coverage()` (a fixed requirement/constraint type
  gate, a hardcoded `status == "retired"` exclusion, and detecting `test`
  items by type name). A type that declares no `coverable:` falls back to
  the old name-based convention with a one-time warning, preserving
  pre-existing behaviour exactly.
- `required_when:` on any field: conditionally required based on a sibling
  enum field's current value, or on a link being present
  (`required_when: {links: alternate}`), cross-validated against the fully
  merged schema at load time. Wired to `decision.rationale` via the
  already-parsed `require_rejection_rationale` setting in
  `refdes-project.yaml`.
- This repository's own sample project now declares
  `standard: {base: hardware, version: 1}` instead of hand-declaring its six
  types.
- `refdes-project.yaml`: an optional, committed, project-level settings file
  sitting next to `refdes.yaml` for presentation/behaviour preferences that
  aren't schema -- `sigfigs`, `item_layout`, `baseline_identity`,
  `require_rejection_rationale`, `publish_datasheets`, and `release_gate:`.
  Absent entirely, a project behaves exactly as before this change (see
  Breaking, below, for the one exception). `item_layout`,
  `baseline_identity`, `require_rejection_rationale`, and `release_gate:` are
  parsed and validated now for features landing in later steps
  (workspace-layer item layout, `refdes revision`/`refdes release`, and the
  `required_when` standard-library mechanism); they have no effect yet.
- `sigfigs` (default 4, range 1-15) replaces the hardcoded significant-figure
  count in calc results and check messages, resolved once at project load.
  Formatting also now prefers positional notation over `%g`'s scientific
  flip when only a couple of trailing zeros need inventing (606.0606 at 2
  sigfigs now renders "610", not "6.1e+02"); a number far enough past the
  requested precision (1234567 at 4 sigfigs) still renders in scientific
  notation.
- `publish_datasheets: true` copies `vendor: true` citation PDFs into
  `_site/assets/datasheets/<sha256><ext>` (flattened, not mirrored under
  `.refdes/vendor/`, since dot-prefixed directories are skipped by several
  static hosts including GitHub Pages via Jekyll).

### Breaking

- The "satisfied but not verified" coverage warning now only fires for an
  item whose coverage stage is actually `satisfied`, not merely "not yet
  verified" (which also matched `addressed`). Latent since `constraint` was
  always coverable but never eligible for this warning; migrating a
  project's `constraint` type onto `coverable: true` (as the standard does)
  can surface it for the first time on an addressed-only constraint.
- Vendored citation PDFs are no longer copied into the built site by
  default. Manufacturer datasheets are generally copyrighted, so publishing
  them is now opt-in via `publish_datasheets: true` in
  `refdes-project.yaml`. With it left unset (or the file absent), the
  rendered citation links upstream only, same as an unvendored citation.

## [0.3.0] - 2026-08-11

### Added

- Asset pipeline: local `<img src>` references resolve, are copied into the
  rendered site under `assets/`, and support Quarto-style
  `{width=... caption="..."}` suffixes rendered as `<figure>`/`<figcaption>`.
  An opt-in `site.assets:` list in `refdes.yaml` copies directories verbatim.
- Datasheet citations: a new `citations` field type with hash-pinning and
  opt-in vendoring. Provenance (sha256, fetched timestamp, vendored flag)
  lives in a committed lockfile, `.refdes/citations.yaml`, and is never
  folded into an item's own content hash.
- `refdes fetch [--item ID] [--url URL] [--update]` — the only command that
  touches the network — to fetch and pin (and optionally vendor) datasheet
  citations.
- `refdes check --refresh` to scan for citation drift against upstream
  without touching the local cache; `refdes build --require-citations` to
  make a missing or unvendored citation a hard build error for CI.
- `references.html` (and a per-board `references-<board>.html`) listing
  citations by URL, and a Citations section in `refdes audit`.
- `item.citations` in `items.json`, exporting resolved citation provenance
  (state, sha256, vendored, pinned) per field.

### Breaking

- A local image `src` that doesn't resolve to a file on disk is now a build
  **ERROR**, not a warning. In 0.2.x this only produced a warning and the
  build succeeded; any existing project with a dangling image reference will
  now fail the build with a non-zero exit code. Fix or remove dangling image
  references before upgrading.

## [0.2.1] - 2026-08-11

> **Provenance note:** this release was published to PyPI by hand — the
> version was bumped directly in a locally-edited `pyproject.toml`, built,
> and uploaded with `twine`, bypassing `release.py`'s clean-tree check. The
> edit was never committed, tagged, or pushed at the time, so **no commit
> exactly reproduces the uploaded artifact**. The `v0.2.1` tag was added
> retroactively at `d12afb7`, the last commit on `main` before the upload
> (PyPI recorded the upload at 2026-08-11T21:46:06Z / 17:46:06 -04:00, ~30
> minutes after `d12afb7` and ~45 minutes before the next commit,
> `15e727c`). Treat this tag as a best approximation of what was published,
> not a guarantee of an exact match — the dirty working tree at upload time
> was never captured, so it may differ from the tagged tree in ways git
> cannot show.

### Added

- Rendered pages warn when a local `<img src>` doesn't resolve to a file on
  disk (this becomes a hard build error in 0.3.0).
- Multi-item markdown files: a single `.md` file can hold several
  `---`-fenced items behind a leading `defaults:` block, mirroring list
  files. Existing single-item files parse unchanged.
- `prefix:` is now a reserved key usable on an individual item, not just in
  `defaults:`.
- Opt-in board scoping: items are grouped into boards by their path under
  `items/`, declared via a `boards:` registry in `refdes.yaml`. Adds
  per-board document/coverage/log/summary pages, `.refdes/boards.yaml`,
  `refdes build --accept-board-move`, and board listings in `refdes audit`.
  Entirely inert with no `boards:` registry.

### Fixed

- ID allocation into flow-style YAML list entries (`- {text: ...}`) rewrites
  the mapping in place instead of corrupting the file.
- Coverage distinguishes "claimed" (an unsettled item says it satisfies a
  requirement) from "satisfied" (a settled one does), via an opt-in
  `satisfying_statuses:` type option.
- A misspelled link key (e.g. `sattisfies:` for `satisfies:`) now fails the
  build instead of silently dropping the traceability edge.
- The site build prunes stale output pages left behind by deleted or renamed
  items, via a build manifest, without touching files it didn't write.

## [0.2.0] - 2026-08-11

### Added

- Project summary view with check margins.
- `release.py`, a release script for the CLI and the VS Code extension that
  enforces version ordering, a clean working tree, and a PyPI-unpublished
  check before building.
- VS Code extension Marketplace metadata (icon, repository, homepage, bugs,
  keywords, gallery banner) and a registered publisher ID.

## [0.1.0] - 2026-08-10

### Added

- Initial release: typed items, units-aware math, and traceability for
  hardware design decisions.
- `.gitattributes` normalizing line endings so content hashes are
  line-ending independent.
- Author, licence, and project URL metadata.

[Unreleased]: https://github.com/Squishiba/refdes/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Squishiba/refdes/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Squishiba/refdes/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Squishiba/refdes/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Squishiba/refdes/releases/tag/v0.1.0
