# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/Squishiba/refdes/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Squishiba/refdes/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Squishiba/refdes/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Squishiba/refdes/releases/tag/v0.1.0
