# changelog fragments — one file per change, assembled at release

Task: replace "everyone edits CHANGELOG.md's `[Unreleased]`" with one fragment
file per change in `changelog.d/`, assembled by a pure function in release.py
at release time. Finished.

## What was built

- `changelog.d/README.md` — the contributor convention: filename
  `<slug>.<category>.md`, categories `breaking|added|changed|fixed|removed`,
  content is the changelog bullet(s) written for a reader of the project
  (what changed, what they must do about it), fragments are consumed and
  deleted at release.
- `release.py`:
  - `assemble_fragments(changelog_text: str, fragments: dict[str, str]) -> str`
    — PURE (no file I/O; verified by reading release.py's `assemble_fragments`,
    lines 219-283: it only slices/joins strings and raises `Abort`). Groups
    fragments by the category in their filename, folds them under the matching
    `###` subheading inside `## [Unreleased]`, creates a subheading when the
    category has none, emits subheadings in `CHANGELOG_CATEGORIES` order
    (breaking, added, changed, fixed, removed — Breaking first, per the
    project's existing `CHANGELOG.md` layout), and never touches existing
    bullets (they are copied verbatim; new bullets are appended after a
    section's last existing bullet). Refuses (raises `Abort`) on a non-standard
    subheading, a duplicated subheading, or a missing `## [Unreleased]`.
  - `fragment_category(name)` — filename -> category, refusing anything that
    is not `<slug>.<category>.md` with a category in the set.
  - `read_fragments()` — reads `changelog.d/` (README.md excluded, sorted by
    filename for deterministic order, empty fragments refused).
  - `release_cli` wiring: the real path folds the pending fragments into
    `CHANGELOG.md` and deletes the consumed fragment files (after the version
    bump, before building). The `--dry-run` path now *reports* the pending
    fragments ("would be folded into CHANGELOG.md and deleted") and stops
    before any file is modified.
- `changelog.d/changelog-fragments.added.md` — this change's own fragment
  (the dogfood).

CHANGELOG.md was NOT modified (see verification below). No dependencies added;
standard library only. `.gitignore` unchanged (nothing needs ignoring —
fragments are committed, like any other source).

## Verification

### 1. Full test suite

`python -m pytest tests/ -q` -> `663 passed in 22.85s` (ran after all edits;
no package code changed).

### 2. Assembler demonstrated on the real CHANGELOG.md

Called `assemble_fragments` directly on the real CHANGELOG.md text (read-only;
the file itself was never written) with two sample fragments — one in a
category that already has a subheading (`added`, which must fold in without
disturbing the existing bullets) and one in a category that has NO subheading
today (`changed`, which must create `### Changed` between Added and Fixed).
Script: `C:\Users\Jared\AppData\Local\Temp\opencode\demo_fragments.py` (outside
the repo). Sample fragments:

```
demo-extra-added.added.md:
  - **A demo added entry.** Proves fragments fold into the existing
    `### Added` section, appended after the bullets already there,
    without rewriting them.
demo-new-changed.changed.md:
  - **A demo changed entry.** `### Changed` does not exist in
    `[Unreleased]` yet, so the assembler must create the subheading in
    the right place: after Added, before Fixed.
```

Resulting `[Unreleased]` section (verbatim from the assembler's output):

```
## [Unreleased]

### Breaking

- **A `calc` name assigned twice in one item is now a build error, not a
  silent overwrite.** Variables are shared across every `calc` block in an
  item (`docs/math.md`) through one item-wide `env` dict, so a name reused in
  a second block, or a second time in the same block, silently kept
  whichever definition ran last -- both `{{NAME}}` interpolation and any
  `checks:` entry against that name read whatever value happened to win,
  regardless of where in the document it appeared. That's a correctness bug
  (the wrong value picked up silently), not a cosmetic one, so it's an error
  rather than a warning: a project that happened to rely on the overwrite,
  even unintentionally, will now fail to build until the duplicate is
  renamed. The message names the variable and both source lines (built on
  the previous entry's line tracking): `'x' is assigned twice in this item
  -- first at line 12, again at line 21. ... rename one of them, e.g. 'x' ->
  'x_2'.` A name reused across *different* items is unaffected -- scope
  still resets per item, unchanged from before.
- **The bundled standard moves to `hardware@3`.** Five changes, arriving
  together because none was ever published on its own:
    1. A new link verb, `governed_by` (inverse `governs`), authored on
       `requirement`, targeting `[requirement, bound]` -- "this specific
       fact must comply with a general rule stated elsewhere," a gap
       `refines` (a narrower version of the *same* statement) and
       `constrained_by` (a machine-checkable numeric limit, the case where a
       `bound` and `checks:` are actually involved) both left open.
    2. `satisfies` widens to `[requirement, bound]` on `decision` and
       `component` (each was `[requirement]`) -- a `bound` could be
       `verified` or `addressed` but never *satisfied*, permanently
       uncoverable regardless of how much design work answered to it, since
       coverage reads only the `addressed_by`/`satisfied_by`/`verified_by`
       backlinks and `constrained_by` was never one of them (see
       [coverage.md](docs/coverage.md#which-links-feed-coverage)).
       `component` also gains `constrained_by: [bound]` (previously no path
       to a bound at all) and a `checks:` field, so a component can
       demonstrate compliance with a bound without a `decision` invented
       purely to host the check. Reviewed against real authoring before
       release (issue #7 findings 7 and 22) and folded into this version
       rather than shipped narrow and corrected later as a breaking `@4`.
    3. `requirement.text`/`bound.text` merge into `body:`, and `test.method`
       does too -- `title` and `body` become the only free-prose fields any
       type carries. `title` is now optional on `requirement`/`bound`,
       falling back exactly as `Item.title` already does for every type
       missing one. `body:` is `required: true` on both, the direct
       replacement for what `text: required: true` used to guarantee, but
       enforced as a **warning**, not a build-blocking error -- a
       requirement with no statement isn't one, but a stub still needs to
       exist while it's being drafted. `method:` was never required, so
       folding it into `body:` doesn't make `body:` required on `test`.
       `rationale`, `source`, `note`, and the log's `summary` all stay
       exactly as they were.
    4. `citations` moves out of `component`'s hand-rolled field list into
       an includable `field_sets:` entry under the one field name
       `citations:`, included by both `component` and `decision`.
       `component.datasheets` is renamed `component.citations` -- breaking
       -- and `decision` gains the same field, so a decision can cite the
       document its reasoning came from instead of only a component being
       able to name its datasheets. `refdes standard upgrade --to 3`
       carries the rename (`datasheets:` -> `citations:`), with the same
       hash-carrying, refuse-and-roll-back behaviour as the rest of the
       migration.
    5. `decision` gains `recorded_by: [log]` -- the inverse of a `log`'s
       existing `records:` verb, now declared on `decision`'s own `links:`
       block. A sealed log entry folds its links into its content hash and
       so can never be edited to point forward at a decision written after
       it; `recorded_by:` lets the decision itself point back at the entry
       that recorded it. Purely additive.

  `refdes init` pins `version: 3` from now on. `refdes new <type>` now hints
  at `body:` after the closing fence -- it's reserved, not a schema field,
  so it never showed up in the scaffold's per-field loop before this.

  **A project pinned at `version: 1` or `version: 2` is completely
  unaffected** and stays that way until it chooses otherwise. To move:
  `refdes standard upgrade --to 3`, which renames `text:`/`method:` to
  `body:` in every item file that still writes them and `datasheets:` to
  `citations:` on any component that still writes it, carries content
  hashes forward in every stamped baseline and seal, and refuses (rolling
  back) rather than silently overwriting or orphaning content on any item
  that already has body content of its own -- merge the two by hand first,
  then upgrade. Parts 1, 2, and 5 need no migration; all three are purely
  additive.

### Added

- **Surrogate keys, layer 2: hashing on the key, and link expansion**
  (`docs/design/keys.md`). Two changes, landed together because the second
  has to be provably neutral against the first:
    1. **Content hashing** (`build.compute_hashes`, `HASH_FORMAT = 2`): a
       link target now contributes its *resolved key* to the owning item's
       content hash, not the display-id text. Renaming an item's display id
       no longer churns the hash of anything that links to it -- verified
       empirically against this repo's own project (renaming `REQ-PWR-002`
       changed 0 of the 19 other items' hashes, including all 6 that link to
       it) rather than merely asserted. An existing stamped baseline or
       seal, recorded under the pre-keys hash definition, is carried
       forward automatically the first time it's next compared or verified:
       if the item's content demonstrably hasn't changed (its hash under
       the *old* definition still matches what's stored), the stored hash
       is silently upgraded in place; if it doesn't match, the entry is
       left untouched and reported as `uncomparable` rather than guessed
       at. Baselines record which format each entry is in (`hash_format:`);
       seals, having no per-entry field to spend on it, self-describe by
       construction once upgraded (see `seal._matches_sealed_hash`).
    2. **Link expansion** (`refdes/links.py`): a bare `satisfies: [REQ-001]`
       is expanded in place to `satisfies: [REQ-001@k7f3m2q9x4b]` the first
       time it resolves to a keyed item, the same automatic-side-effect
       posture key minting already has, gated by the same `--no-write`.
       Resolution now reads only the part after `@`; the display half is
       never consulted, not even as a fallback for an unresolvable key.
       Frozen once written -- this module never rewrites a composite it
       already produced, and never touches a flow-style list entry
       (`- {id: X, satisfies: [Y]}`), a disclosed, narrow gap left bare
       rather than half-handled.

  Fixing hashing surfaced five other places that resolved a link target by
  treating it as a bare display id and would otherwise have silently
  misbehaved the moment a target got composite-expanded: `blocked.py`'s
  chain/root resolution, `blocks.py`'s `{{cascade}}` walker, coverage's
  satisfied/verified/addressed accounting, the cross-workspace lint, and
  `stub-tests`'s already-covered check. All five now read a new
  `Item.resolved_links` field (`resolve_links`'s own resolved output)
  instead of raw `links`. `checks: [{value, against}]` is a separate
  mechanism, not a `links:` reference, and is not covered by expansion --
  `against:` stays a bare id and is not yet rename-safe.

  Still design-only: the corruption lint, `refdes keys adopt`, the
  display-half refresh-on-rename mechanism, and anything in `revise.py` or
  `former_ids.py`.
- **Surrogate keys, layer 1: format and minting** (`docs/design/keys.md`).
  Every local item now gets an opaque, immutable 11-character `key:` --
  10 random Crockford-base32 data characters plus a Damm check character,
  minted automatically by any command that loads the project (`refdes/keys.py`,
  wired into `cli._load()`) and written back next to `id:`, the same
  write-back path `refdes id`/`former_ids:` already use. `key` joins
  `parse.RESERVED` -- hard-reserved like `id`, not overridable like `prefix`,
  so a hand-rolled schema declaring its own `key` field can't shadow
  identity. A new global `--no-write` flag suppresses minting for a
  genuinely read-only pass (CI, inspecting someone else's project, a
  bisect); an item with no key yet still parses, validates, and builds --
  a key is a precondition for being durably referenced, not for existing.
  The design doc's own recommendation changed during implementation: the
  check character is Damm, not the originally-recommended Luhn mod 32 --
  see the doc's amended §1 for the measured numbers behind that call. This
  is the format-and-minting slice only; link resolution, hashing, the
  corruption lint, and `refdes keys adopt` are later layers and remain
  design-only.
- `refdes audit` reports `allocated` ledger entries with no live item and no
  `former_ids:` explaining them (issue #6, finding 10 part 2's narrower,
  informational half). Not a fix for hand-typed id reuse after deletion --
  investigated at length and found undetectable from project state alone,
  see `docs/ids.md`'s "Numbers are never reused" and
  `docs/design/keys.md`'s "Why this is the root fix" -- only for the window
  between a deletion and any later re-typing of the same id, and only when
  `refdes audit` happens to run during it.
- `refdes index`'s output now includes `next_ids`, the next free number per
  id prefix (one more than `ids.high_water()`'s own reported maximum,
  unioned across live items and the ledger's burned/allocated history). Lets
  an editor offer the next id as a completion while a new item's id is still
  being hand-typed -- the one population id completion never covered, since
  a brand-new item's id doesn't exist yet to be completed from.
- A GitHub Actions workflow (`.github/workflows/docs.yml`) that runs
  `refdes build` inside `docs-site/` on every push to `main` and publishes
  the result to GitHub Pages. Before this there was no point between a
  change landing on `main` and someone being able to browse the current
  reference docs as an actual rendered refdes site -- `docs-site/`'s output
  is gitignored on purpose (`_docs/`) and was never committed, so a human
  had to clone the repo and run the build by hand. Requires GitHub Pages to
  be switched on for this repo (Settings -> Pages -> Build and deployment ->
  Source: GitHub Actions) before the first run can deploy; not something
  this change can do on its own.
- Documented the difference between `source:`, `note:`, `rationale:`, and
  `body:` in `docs/authoring.md` -- previously only inferable by reading
  each field's `on_change:` mode in the schema itself (`note:` wasn't
  mentioned anywhere in the docs at all).
- `refdes build --dry-run`: renders the site for real (same output
  directory, real HTML) without sealing new log entries -- the one command
  with a permanent side effect on an ordinary run that had no way to preview
  first. Unlike `id`/`revise`/`stub-tests`'s own `--dry-run`, which print a
  preview and write nothing, this one still writes -- only the seal-recording
  side effect is skipped. Output is watermarked with a "Draft build" banner
  on every page so a preview render can't be mistaken for the sealed site.
- VS Code id completion (`editors/vscode/extension.js`) now also matches
  against an item's source file and board, not just its id and title --
  typing `power` narrows the dropdown to items declared in `power.yaml`, or
  on the `power` board, exactly as typing `REQ-IO` narrows by id prefix
  today. Both were already in the index payload `refdes index` sends the
  extension; this is a filter-text change only.
- `refdes ls`: a filterable, human-readable listing of existing items (id,
  type, board, title), for everyone not using the VS Code extension --
  `index`/`index --compact` is the same data but a whole-project JSON blob
  built for editor tooling, with no filtering and unreadable without piping
  it through something else. `--type`, `--board`, `--file`, `--tag`, and a
  free-text positional query that matches title *and* `tags:` -- tags: is
  `on_change: ignore`, so retagging never invalidates anything downstream,
  which is what makes it the right place to invest in findability, and what
  makes reaching it in search worth doing.
- `lint_own_tags: true` (`refdes-project.yaml`, default off): warns on an
  item whose `tags:` are entirely inherited from its file's `defaults:`, or
  absent entirely -- as hard to find later as having no tags, since a
  file-level tag set is identical across every item in the file and just
  re-encodes which file it's already in. A bare presence check would fire
  on almost nothing (`tags:` is nearly always set once in `defaults:`, so
  every item in the file inherits a non-empty list); `inherited_fields`
  (this release's `defaults:`-provenance tracking) is what makes the real
  signal checkable. Opt-in, following `boards.lint_tokens()`'s own
  precedent: `tags:` is optional by design, and plenty of projects won't
  want the noise. Sequenced after `refdes ls --tag`/free-text search, since
  the lint only points at something actionable once search can act on it.
- `{{index}}` gains a `tag="..."` parameter scoping the listing to items
  carrying that tag -- the same single named filter `board=` already is,
  validated against the tags some local item actually carries (with the
  usual did-you-mean on anything else, and deliberately not a query
  language). `tags:` is the one grouping field that follows neither board
  nor type lines, and `{{index}}` was the only surface unable to select
  on it.

- **A demo added entry.** Proves fragments fold into the existing `### Added` section, appended after the bullets already there, without rewriting them.

### Changed

- **A demo changed entry.** `### Changed` does not exist in `[Unreleased]` yet, so the assembler must create the subheading in the right place: after Added, before Fixed.

### Fixed

- `calc` build diagnostics (errors and warnings) always pointed at the
  item's front-matter line, never at the assignment that actually caused
  them -- unhelpful the moment an item had more than one `calc` block or
  more than one line in a block. `CalcLine`/`items.json` now carry each
  assignment's absolute source line (`Item.body_line`, computed from the
  closing front-matter fence for a markdown item; `None` for a list file's
  `body:` key, which has no cheap per-line position without deeper
  YAML-loader surgery, so its calc diagnostics still fall back to the
  item's own line). The VS Code extension's inline decorations had the same
  problem one level up: they matched a calc result to a line by name alone
  (`Array.find`), so two lines assigning the same name always decorated
  both with the *first* one's result. They now match by source line
  instead.
- The generated `.refdes/schema.json` had no branch for `section:` marker
  entries, so a YAML list file using them -- valid, and accepted by `refdes
  check` -- failed to validate against its own schema in any editor
  (`missing property "text"`, `matches multiple schemas`). Added a
  `section_marker` branch to the list file's `items:` `oneOf`, mirroring
  `_only_key()`'s own rule that a marker's one real key is `section`.
  Scoped to list files: a markdown section marker is a bare fenced block,
  not front matter, so there was never a bare-item schema to fix.
- A file's `defaults:` merged onto every item unconditionally, including one
  that overrode `type:` -- so a value only valid for the file's typical type
  (e.g. `status: active`, a `requirement`/`bound` vocabulary) could fail
  validation against a different type's own vocabulary on an item that never
  wrote that value itself, with the error reported identically to one the
  item actually typed. Items now carry which of their field values came from
  `defaults:` rather than their own keys; a failure on one of them now says
  so explicitly and points at the `defaults:` block's own line instead of
  the item's.
- The calc lexer rejected a prefixed non-ASCII unit: its unit pattern only
  admitted `Ω`, `µ`/`μ`, and `°` in the leading character class, so `kΩ`
  and `MΩ` -- with the prefix in front -- failed to parse while a bare `Ω`
  worked, and `%` was reachable only through the tolerance pre-parse, so a
  bare percent (`85 %`) failed as a raw syntax error with no hint. The
  non-ASCII unit characters are now legal anywhere in a unit segment, and
  `%` reads as its own percent-quantity alternative. A declaration that
  fails to parse now also names the expression that failed, not just the
  parser's message.
- A citation's recorded `page:` went nowhere: it was stored and printed in
  the table cell but never reached the link. A citation carrying a page
  number now appends `#page=N` (the standard PDF fragment) to both the
  remote citation's href and the vendored "local copy" href.
- Jinja autoescaping was silently disabled project-wide and is now actually
  on. It was enabled via `select_autoescape(["html"])`, which matches a
  template's name by suffix -- and every template here is named
  `*.html.j2`, ending in `.j2`, so the callback returned `False` for all
  of them and no output was ever escaped; author-controlled YAML reached
  HTML attributes raw. The templates already marked every intentional
  raw-markup site `| safe`, which is what enabling escaping gives back.
- The preview-data JSON embedded in each rendered page could be broken out
  of its `<script id="preview-data">` element: `json.dumps` doesn't escape
  `<` or `>`, so an item title containing `</script>` closed the element
  at parse time and turned the rest of the title into live markup. `<`
  and `>` are now escaped (`\u003c`/`\u003e`) at dump time -- valid JSON
  escapes that `JSON.parse` decodes back to the original characters, so
  the payload value is unchanged.
```

The assembler itself reported, over the same region compared against the
original file text:

```
Unreleased-region diff: 6 line(s) added, 0 line(s) removed
(0 removed  => no existing line was reordered or rewritten)
CHANGELOG.md on disk is byte-identical to what the demo read in (read-only).
```

The 6 added lines are exactly the two demo bullets plus the created `###
Changed` subheading plus the separating blank lines — one contiguous hunk at
the end of `### Added` / before `### Fixed`. Subheading order in the result:
Breaking, Added, Changed, Fixed. (This run also caught a real bug in my first
draft — a doubled blank line after every subheading — which the byte-level
diff exposed and the `body_start = match.end() + 1` fix resolved; the diff
shows 0 removed/0 rewritten lines only after that fix.)

`CHANGELOG.md` stayed untouched: `git status --short` shows only `M release.py`
and `?? changelog.d/`, never a CHANGELOG.md entry.

### 3. Dry run writes nothing and deletes nothing

Ran the real CLI dry-run path with the pending fragment present:

```
python release.py cli 198.0.0 --dry-run --allow-dirty
```

Output (captured from the run):

```
== Releasing CLI 0.5.0 -> 198.0.0
  PyPI: 198.0.0 is unpublished, good

== Running the test suite
  tests passed
  dry run: changelog-fragments.added.md would be folded into CHANGELOG.md and deleted
  dry run: stopping before any file is modified
```

How verified: sha256 of `CHANGELOG.md`, `changelog.d/changelog-fragments.added.md`
and `changelog.d/README.md` taken immediately before and after the run —
all three byte-identical, and the fragment file still exists. Structurally
the fold-and-delete step sits after the dry-run early return in
`release_cli` (release.py lines 324-334), so the dry run cannot reach the
write.

## Notes / risks

- The assembler refuses (Abort, no partial state) on: a fragment filename
  that is not `<slug>.<category>.md` with a known category, an empty
  fragment, a `[Unreleased]` section missing, a non-standard subheading
  inside `[Unreleased]`, or a duplicated subheading. Reasonable "refuse
  rather than guess" posture matching the rest of release.py.
- Subheadings in `[Unreleased]` are re-emitted in the canonical category
  order; today's Breaking/Added/Fixed order already matches, so the real
  file never moves.
- Dry-run now reads `changelog.d/` to report pending fragments — read-only,
  allowed by the "no write/delete" rule.
- `changelog.d/` is committed like any source (fragments are part of the
  change they describe); nothing added to `.gitignore`.