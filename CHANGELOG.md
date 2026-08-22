# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

### Fixed

- The generated `.refdes/schema.json` had no branch for `section:` marker
  entries, so a YAML list file using them -- valid, and accepted by `refdes
  check` -- failed to validate against its own schema in any editor
  (`missing property "text"`, `matches multiple schemas`). Added a
  `section_marker` branch to the list file's `items:` `oneOf`, mirroring
  `_only_key()`'s own rule that a marker's one real key is `section`.
  Scoped to list files: a markdown section marker is a bare fenced block,
  not front matter, so there was never a bare-item schema to fix.

## [0.5.0] - 2026-08-21

### Added

- `hardware@2`, the first version bump since the standard library shipped.
  Three vocabulary changes, arriving as one version because they came out of
  one development cycle and none of them was ever published on its own:
    1. `constraint.title` is now `constraint.text`, matching
       `requirement.text`'s role as the type's one required content field --
       `title` was a short-label field with nowhere for a constraint's
       actual normative sentence to go but the optional, overflow-only
       `body:`. `preview` follows it, becoming `[status, text, limit]`.
    2. `constraint` is now `bound`, prefix `CON` -> `BND`, and `bound`
       additively gains `refines: [bound]` alongside its existing
       `derives_from: [requirement, bound]`. `requirement` and `constraint`
       read as near-synonyms in plain English -- a constraint colloquially
       *is* a requirement -- which is what produced the authoring mix-up
       this comes from; `bound` doesn't have that problem, and it names the
       `limit:` field that makes the type mechanically distinct. Before
       this only `requirement` could `refines:`, so a constraint narrowing
       another constraint had nowhere to say so; `derives_from:` stays,
       since the two answer different questions and only `derives_from:`
       may cross into `requirement`.
    3. `component.equivalent` and `component.alternate` are restricted to
       `[component]`, where v1 wrote both as `[]`. An empty target list
       means *unrestricted* -- which is what it deliberately means on
       `decision.blocked_by:` -- so v1's dictionary accepted `equivalent:
       [REQ-PWR-001]` on a component with no diagnostic at all, while the
       spec and every version of the docs said component -> component.

  `hardware@1` is untouched and still resolves exactly as it always has:
  this ships as a new pinned version rather than an in-place edit, since
  `standard.version: N` is byte-identical forever once released.

  `refdes standard upgrade --to 2` applies parts 1 and 2 to an existing
  project's item files and their ids. Part 3 renames nothing -- it only
  starts checking what is already written -- so there is nothing for the
  migration to rewrite, but the step still re-validates and will refuse,
  rolling back, if an existing equivalence no longer satisfies it, naming
  the offending link. Moving the pin by hand instead gets a diagnostic
  naming the type rename rather than a bare "unknown type 'constraint'."
  with no did-you-mean (the two names are too dissimilar for difflib to
  suggest anything).
- `refdes schema --graph`: Mermaid flowchart source for the project's
  actual type/link graph -- the same resolved schema `--json` emits, walked
  with a different renderer, so a preset or project overlay changing a verb
  can't leave a hand-drawn diagram silently stale. The worked example in
  [links](docs/links.md#starter-link-types) is generated from it.
- A generated site sidebar, replacing the top nav bar: narrative pages and
  project-wide reports first, then one collapsible group per board or
  workspace holding that scope's own pages and reports, boards nesting
  inside the workspace their items resolve into. A group renders
  pre-expanded when the page being read lives inside it, the current page's
  link carries `aria-current="page"`, and below a narrow viewport the whole
  tree collapses behind one "Navigation" line -- a CSS-only toggle, so it
  still works with JavaScript disabled. A page's own in-document contents
  list additionally highlights the section in view as you scroll, where
  JavaScript is available.
- A quoted bare-numeric `id:` (`id: "042"`) is expanded against the item's
  prefix by `refdes id` and frozen at exactly the number the author typed,
  rather than being handed the next free one. A number at or below the
  current high-water mark for that prefix -- already live, or burned by a
  since-deleted item -- is refused with an error naming the number to beat,
  never silently renumbered. An *unquoted* one is refused outright: YAML
  resolves a leading zero as octal (`id: 042` parses to 34, not 42), so by
  the time the value arrives it may already be the wrong number with nothing
  left to recover the intent from.
- An already-id'd item whose id doesn't match the prefix its own `type:` or
  `prefix:` would derive is now a build error rather than passing silently.
  Checked as "starts with", so a free-form category segment typed straight
  into the id (`CON-IO-004` against a bare `prefix: CON`) is correct, not a
  mismatch. Never auto-corrected: the id is the one string every link,
  backlink, and ledger entry is keyed on.
- `refdes revise <mapping-file>`: rewrites project-local vocabulary (type
  names, field names scoped per type, link verb names, id prefixes) across
  every item file in one operation, from a hand-written old->new mapping.
  `refdes standard upgrade --to N` does the same thing for a bundled
  standard's own version history, needing no hand-written mapping -- each
  standard version ships its own `migration.yaml` describing its delta from
  the version before it (`hardware@2`'s ships the renames described above),
  and a multi-version jump chains every intervening version's own delta in
  order rather than merging them into one combined rename. Both carry each affected item's content hash forward
  in every stamped baseline *and* seal file, id by id, so a purely cosmetic
  rename never looks like a content change or, for a sealed append-only log
  entry, a build-breaking seal violation. Refuses, rolling back cleanly,
  rather than guessing at an ambiguous mapping, an already-used target
  name, or a rename the current schema doesn't yet support. Baselines now
  also record which standard version they were stamped under
  (`Baseline.standard`), so a multi-version upgrade knows where an existing
  baseline started -- one stamped before this field existed is left alone
  (reported, not guessed at) during a chained upgrade rather than silently
  matched against whichever version happens to be current.
- `section: <type>` markers (finding 6, replacing the type-keyed `items:`
  mapping the finding originally proposed): a `- section: <type>` list entry,
  or a `section: <type>` fenced block in Markdown, asserts the type for every
  item after it until the next section or end of file, so a file mixing
  several types no longer has to restate `type:` on each one. Unlike
  `defaults: {type: ...}`, a section *asserts* rather than defaults -- an
  item inside one that names a conflicting type is an error, not a silent
  override, and a file-level `defaults:` naming a different type than an
  active section is likewise an error rather than a silent pick-a-winner.
  No `enforce_grouping:` setting was added: a section makes interleaved
  types within it structurally impossible rather than something to lint for.

### Fixed

- `refdes revise` and `refdes standard upgrade` refused to run on any
  project with a failing `checks:` result. A decision currently violating a
  bound is the tool working, not failing, and a state a real board sits in
  for weeks -- this repository's own sample project ships one deliberately,
  as the teaching example on the front page of the docs, and so could not be
  migrated at all. The refusal now covers what it was actually for: a
  document that doesn't validate (an item that doesn't parse, a missing
  required field, a link pointing at nothing, a schema the data no longer
  satisfies), where a hash change caused by the rename really could hide
  behind an already-broken build. A rename moves the arithmetic and the
  limit together and cannot change a check's verdict.
- A registered board with no items was given a full set of six report pages
  describing nothing, three of which the nav then declined to link -- so
  they were unreachable as well as empty. The mirror image of the
  boardless-items fix in 0.4.0: there, items with no page; here, pages with
  no items. A *populated* board with no log entries had the same problem one
  report down, getting a `log-<board>.html` nothing pointed at. Which
  reports exist for a scope now comes from one function that both the nav
  and the renderer read, so the sidebar and the output directory cannot
  disagree in either direction. Workspaces get the same treatment.
- This repository's own sample project reported six "no board" warnings on
  every build, one per design-log entry: the `log` type declares its own
  `board` field, so the reserved `board:` override the other Board A folders
  use cannot reach it, and the file sat in `items/log/`, which is not a
  registered board. Moved to `items/board-a/log.yaml`, where the path itself
  matches the registry. Content hashes are unchanged, so all six seals
  migrated into the board's own seal file untouched.
- A check against a limit in an offset temperature unit (`<= 85 degC`, one
  of the six forms the limits table documents, and about the most obvious
  constraint a board has) aborted the whole command with an unhandled
  `pint.OffsetUnitCalculusError` traceback -- from `check`, `build`, and
  `index` alike. The crash was in the margin calculation, which divides a
  temperature *difference* by a temperature *reading*; there is no honest
  fraction to report either way, since 45 degC of slack under an 85 degC
  limit is 53% on the Celsius scale and 13% in kelvin, so this joins the
  two cases a margin was already undefined for. The check itself was never
  in question and is unchanged, as are absolute scales (`<= 350 K`) and
  ranges (`0 degC .. 60 degC`), which still get real margins.
- `refdes id` reported "allocated REQ-002" and "allocated 1 id(s)" directly
  below the error saying that id could not be written into the source, and
  recorded it in the ledger's `allocated:` list and burned its number -- so
  the next run gave the item a different id and the burned one stood for
  nothing. A refused write-back touches nothing, so it is no longer counted
  as an allocation anywhere, and the item stays pending for a later run.
  Per item, not per file: a neighbouring entry that can be written still is.
- The `refdes release` readiness-gate table picked a stream per row (FAIL to
  stderr, everything else to stdout), so under redirection -- CI, where it
  matters most -- the table arrived split across two files with its ordering
  lost. It is one block of output and now goes to one place.
- `refdes check --help` and the CLI reference both claimed `check` writes
  nothing to disk. It refreshes `.refdes/schema.json`, like every other
  command that loads the project. Reworded to the guarantee that actually
  holds: nothing of the project's own is written.
- A `---`-fenced block partway down a multi-item Markdown file whose YAML
  didn't parse -- or parsed to something that isn't a mapping -- was skipped
  with no diagnostic at all. The item vanished from the project, its body
  text folded into the previous item's, and the build exited 0 with zero
  errors. The file's own head block always reported both conditions; every
  later block now reports them identically, at the real failing line.
- Deleting a sealed append-only entry was undetected. Editing one was
  already a build error, but removing it outright produced a clean build, a
  clean `audit`, and an orphaned hash left in the seal file forever --
  the louder half of the same tamper-evidence question. Now reported the
  same way, with the same (optionally board-scoped) `--reseal` escape hatch,
  which drops the orphaned seal. An id still live under a different board,
  or claimed by another item's `former_ids:`, is present rather than
  deleted and is not reported.
- `refdes revise`/`refdes standard upgrade` never rewrote a block-style
  link target list (a bare `key:` with `- TARGET` entries under it) -- only
  flow style had ever run through the engine. That didn't leave those
  references merely untouched: the rewritten project then had a dangling
  link target, so the whole operation refused and rolled back for any
  project writing its links the idiomatic way, reporting the symptom and
  nothing about the cause.
- Both also reported success while leaving prose mentions of a renamed id
  pointing at nothing. Prose is still deliberately never rewritten --
  editing a sentence, including a sealed one, is not a rename's business --
  but every mention that no longer resolves (to a live item, or through some
  item's `former_ids:`) is now listed with its file and line, across items
  and narrative pages alike.
- An explicit `null` on an enum field no longer bypasses its schema default
  and the enum check that skips any `None` value -- it's coalesced into
  absent, same as an omitted key, and reported when it happens.
- `refdes id` no longer inserts a second `id:` key when run on an
  already-scaffolded bare `id:` placeholder -- it fills the existing key in
  place, in both the YAML-list and Markdown front-matter write-back paths.
- The generated JSON Schema no longer hard-rejects a field `refdes check`
  only warns about -- `additionalProperties` on a type's merged schema node
  is permissive, matching the CLI's actual leniency.
- Every generated `.vscode/settings.json` used to point at the same relative
  `yaml.schemas` path, so two refdes projects open in the same VS Code
  session could validate one project's files against the other's schema.
  `refdes init` now writes an absolute, project-specific path.
- A malformed YAML file always reported `line 1`, regardless of where the
  problem actually was -- not a fallback, wrong for every parse failure past
  the first couple of lines. Both catch sites now read the real location off
  the exception. A bare `>`/`>=` value (read by YAML as a folded-block-scalar
  indicator, not a comparison, on any field) now also gets a targeted hint
  telling you to quote it. `limit:`'s generated JSON Schema fragment carries
  `examples` showing the quoted forms, verified against the real
  `yaml-language-server` to actually surface as editor completions.
- A multi-item Markdown file only ever reads its very first block as
  `defaults:`. A `defaults:`-shaped block anywhere else used to be silently
  misparsed as a malformed item -- an "unknown field 'defaults'" warning, and
  every item after it silently kept whatever type came from the *original*
  leading defaults, wrong or not. Now an error naming the mistake, pointing
  at `section: <type>` as the fix.

### Breaking

- **The bundled standard moves to `hardware@2`, and `constraint` is now
  `bound`.** The id prefix moves with it, `CON` -> `BND`, so this touches
  every id, every link target, and every `checks:` entry pointing at one.
  `constraint.title` is also now `bound.text`, and
  `component.equivalent`/`alternate` no longer accept a non-component
  target. `refdes init` pins `version: 2` from now on.

  **A project pinned at `version: 1` is completely unaffected** and stays
  that way until it chooses otherwise -- that is what pinning is for. To
  move: `refdes standard upgrade --to 2`, which rewrites the item files and
  their ids, carries content hashes forward in every stamped baseline and
  seal so the rename doesn't read as a content change, and refuses (rolling
  back) rather than leaving a half-migrated project. Prose mentions of a
  renamed id are deliberately not rewritten but are reported by file and
  line; recording the old id once in the replacement's `former_ids:` makes
  every one of them resolve again.

- **Three things that used to build clean are now errors.** Each was a
  silent failure rather than a lenience worth keeping:
  - deleting a sealed append-only log entry (editing one was already an
    error; removing it outright was not detected at all);
  - a `---`-fenced block partway down a multi-item Markdown file whose YAML
    doesn't parse (the item used to vanish from the project, its body text
    folding into the previous item's, with the build still exiting 0);
  - at `hardware@2` only, an `equivalent`/`alternate` pointing at something
    that is not a component.

- **The generated site's top nav bar is replaced by a sidebar.** Anything
  styling, scraping, or linking into the old markup will need updating. The
  tree is collapsible, marks the current page with `aria-current`, and
  collapses behind one line below a narrow viewport, still without
  JavaScript.

- **A scoped report page is only written when it has something to show.** A
  registered board with no items gets no report pages at all, and a board
  with no log entries gets no `log-<board>.html`; previously both were
  written and then left unlinked. A hand-written link to one of those URLs
  will now 404. Everything the sidebar links exists, and everything that
  exists is linked.

- **`checks[].margin` is `null` for a limit in an offset temperature unit**
  (`<= 85 degC`), where the command previously crashed outright with an
  unhandled traceback. Consumers already had to handle `null` for an `==`
  limit and a limit of zero; this is a third case, not a new shape.

- **`refdes id` no longer counts a refused write-back as an allocation.** An
  id it could not write into the source is no longer reported as allocated,
  no longer recorded in `.refdes/ids.yaml`, and no longer burns its number.
  Anything parsing the `allocated N id(s)` line will see a different count
  in that failure case -- and the id stays available for the next run.

## [0.4.0] - 2026-08-18

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
- Workspaces: a `workspaces:` registry (an ownership boundary one level above
  boards), `item_layout: workspace` as the second of the two fixed layouts
  `refdes-project.yaml` already validated, an item-level `workspace:`
  override, a cross-workspace reference lint (`cross_workspace_severity`,
  default warning) that flags an authored link crossing into a workspace not
  marked `shared: true`, per-workspace pages, nav grouping (boards nest under
  their workspace), `--workspace` scoping on `refdes check`, workspace drift
  tracked in `.refdes/boards.yaml` and reported by `refdes audit`, and an
  eighth release-gate rule, `unaccepted_workspace_moves`. Entirely inert with
  no `workspaces:` registry declared. See [workspaces](docs/workspaces.md).
- Board-grouped site navigation: once `boards:` is registered, the top bar
  groups a project's pages and generated reports under each board's label
  instead of one flat list; a narrative page joins a board's group by tagging
  `board:` in its front matter. A project with no `boards:` registry renders
  the same flat nav as before.
- Append-only seals are now split per board: each registered board gets its
  own `.refdes/log-seal-<board>.yaml`, and `--reseal` optionally takes a
  board name to accept edits only to that board's own entries (bare
  `--reseal` still accepts everywhere). A project with no `boards:` registry
  is unaffected (single `.refdes/log-seal.yaml`, as before).
- `refdes check --board NAME` narrows which diagnostics print, and the item
  count in the summary line, to one board's own items -- the whole project
  still parses and every link still resolves regardless; a project-level
  diagnostic with no attributable item is never hidden by `--board`.
- Generated blocks, `{{index}}` and `{{cascade}}`: `{{index by="<field>"
  type="<type>"}}` groups a type's items into ID/Title tables by a field's
  current value (enum fields in declared-`choices:` order, dates
  chronologically, everything else lexicographically, with an `(unset)`
  bucket last); `{{cascade from="<id>" direction="down|up|both"}}` renders a
  bounded, rooted walk of the traceability graph, a revisited node rendering
  once more as a terminal leaf rather than erroring. Both are extracted and
  validated before markdown rendering, sharing the standard hover-preview
  linking; an unrecognized block name passes through as literal text, and a
  block shown as an example inside a fenced code block is left untouched
  rather than executed. `link_types:` entries gain a `trace:` flag (default
  `true`) controlling which verbs a cascade walks by default -- the bundled
  standard sets it `false` on `amends`/`records`/`supersedes`/`addresses`.
  See [blocks](docs/blocks.md).
- Figures: an explicit `id="..."` on a figure registers it in a project-wide
  registry and enables numbering; each rendered document numbers its own
  figures fresh in its own reading order; `[[fig:id]]` resolves to a linked
  "Figure N" (or a custom label) wherever both the figure and the reference
  are rendered together. `refdes check` now catches a dangling `[[fig:...]]`
  immediately, the same as a dangling `[[ITEM-ID]]`, instead of only
  discovering it on the next `refdes build`.
- `blocked_by:` link and its cascade report: a decision (or any type) can
  declare `blocked_by: [...]`; the report resolves each direct edge to its
  structural root, detects cycles as a hard build error, and flags a blocker
  that reached a settled status while the edge is still declared. Surfaced
  in `refdes audit` ("Blocked chains"), a panel on the blocked item's own
  page, and folded into `coverage.html`'s "claimed but not verified"
  warnings.
- Parts indexing (`parts.html`, plus per-board/per-workspace variants,
  broken out separately in `refdes audit`'s "Parts:" section) and part
  equivalence: `parts.html` indexes any type's `part_number` field and any
  citation's own nested `part_number` by exact string, so a part cited but
  never made into a component still shows up. `equivalent`/`alternate`
  links on `component` (already in the bundled standard) now render
  correctly for the self-inverse case (`equivalent`'s inverse is itself),
  merging outgoing and incoming declarations instead of showing the same
  claim twice.
- `refdes init`, `refdes new <type>`, `refdes schema --json`, and
  `refdes standard add-preset`/`remove-preset`: `init` writes a minimal
  `refdes.yaml` pointing at the standard (no copied `types:`/`link_types:`)
  plus a `.vscode/settings.json` wiring up `yaml.schemas`; `new` scaffolds an
  item's front matter for any type in the merged schema; `schema --json`
  emits a JSON Schema over the project's actual merged schema, written to
  `.refdes/schema.json` (gitignored) as a side effect of every
  project-loading command, with staleness detected by `refdes check`;
  `standard add-preset`/`remove-preset` edit `standard.presets:` in place as
  a minimal text patch, `remove-preset` reporting exactly what breaks before
  writing the change.
- VS Code extension: declares `redhat.vscode-yaml` as a dependency, so
  `items/**/*.yaml` gets full YAML-schema completion/validation from the
  association `refdes init` now writes; adds a third completion trigger for
  `.md` front matter, which that mechanism can't reach -- field and link key
  names, once the current item's type is known from context.
- `refdes stub-tests`: writes one multi-item markdown file per (workspace,
  board), one starter test item per still-uncovered coverable item in that
  scope (`verifies:` already pointing at it, the type's own default
  `status:`, an empty `method:` if the type declares one). Deduplicates by
  declared links, not text, so re-running never doubles up and deleting a
  stub makes its target eligible again.
- `former_ids:`, a reserved list field recording the id(s) an item replaces
  after a renumbering: `[[old_id]]` and a bare `old_id` (when it fits the
  ordinary `PREFIX-NNN` bare-reference shape) resolve to the declaring item
  with a visible "(formerly old_id)" marker; a former id colliding with a
  live id, or claimed by two items, is a build error; every former id is
  folded into the ID ledger so the allocator can never reissue it; `refdes
  audit` lists the full mapping.
- `refdes former-ids propose`: infers old-to-new id candidates by comparing
  the most recent baseline snapshot to the live project and scoring title
  similarity; shows every candidate with its confidence and writes nothing
  until specific old ids are named via `--confirm`.

### Fixed

- `refdes check`/`refdes build` now warn when an item resolves to no board
  (a `boards:` registry is declared but a path segment isn't in it), and
  treat a recorded board going away as drift -- both were previously
  silent, so a restructured `items/` tree could hollow out a board's pages
  with no diagnostic at all.
- A limit's parse-failure diagnostic now appends a hint when the
  unparseable text looks like several bounds run together in one sentence
  (two or more numbers plus a list-like conjunction), suggesting a split
  into separate constraint items.
- A `[[ITEM-ID]]` reference inside prose no longer produces nested
  duplicate `<a>` tags (the bare-reference pass was re-scanning the
  explicit-reference pass's own already-substituted HTML).
- A `{{index ...}}`/`{{cascade ...}}` directive shown as a literal example
  inside a fenced code block was being executed as a real block instead of
  left as text.
- Packaging: `standards/**/*.yaml` (the bundled standard library) is now
  included in the built wheel -- previously an installed, non-editable
  `refdes` would fail to resolve `standard:` at all, since the files it
  needs simply weren't shipped.
- Finding 9: a tolerance written on the wrong side of a calc declaration
  (`name : unit ± tol = expr` instead of `name : unit = expr ± tol`) now
  gets a diagnostic naming the fix (`a tolerance belongs on the right-hand
  side — ...`) instead of `unknown unit 'W ± 10%' in declaration`.

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
- `refdes check`/`refdes build`'s failing-`checks:` message now leads with
  the worst-case bound instead of the nominal value it previously (and
  incorrectly) reported -- e.g. `P_dens = 0.2366 W/in² violates CON-THM-001
  (<= 0.15 W/in^2)` is now `P_dens violates CON-THM-001: worst case 0.2366
  W/in² vs <= 0.15 W/in^2`, with `(nominal X)` appended only when a
  tolerance widens the check. Anything scripted against the old message
  text will need updating.
- Coverage diagnostics now aggregate: "nothing addresses, satisfies, or
  verifies this yet" and "satisfied but not verified" each collapse into
  one project-level summary line (pointing at `coverage.html`) instead of
  one warning per item; "satisfied but not verified" is additionally
  suppressed entirely when the project declares no verifier (`test`-like)
  items at all. A new `info` diagnostic severity was added, hidden by
  default and shown with the new `-v`/`--verbose` flag on `check`/`build`.
- An unpinned citation (no fetched record yet) is now reported at `info`
  severity, not `warning` -- it's the routine state before `refdes fetch`
  has run. Still promoted to error with `--require-citations`.
- Local image (`<img src>`) destinations in the rendered site are now
  content-hashed leaf filenames (`figures/curve.<hash>.png`) instead of
  mirroring the source path exactly. Ordinary `![alt](src)` markdown images
  are unaffected -- the rendered `<img src>` is rewritten to match
  automatically -- but a hand-typed link into `_site/assets/...` hard-coding
  the old, unhashed destination path will now 404.
- A project that adopts the bundled `hardware@1` standard (`standard:
  {base: hardware, version: 1}`) gets `coverable_statuses: [active]` on
  `requirement`/`constraint` and `verifying_statuses: [passing]` on `test`:
  a `draft`-status requirement or constraint now leaves coverage tracking
  entirely (no `coverage.html` row, doesn't count toward "N item(s) with no
  coverage"), and a `test` whose own status isn't `passing` -- including
  `planned`, both the standard's own default and what `refdes stub-tests`
  generates -- no longer counts as verifying anything it links to. A
  project not using the standard, or a custom type that doesn't declare
  these flags, is unaffected.
- This repository's own sample project migrated onto the standard:
  `decision.constrains` is now `constrained_by`, `requirement`/`constraint`
  status choices renamed `accepted` -> `active` (the standard's
  `draft`/`active`/`retired` enum has no `accepted`), and `REQ-PWR-003`'s
  self-referencing `derives_from` is now `refines`. Anyone using this
  repository's `refdes.yaml`/items as a starting template should expect the
  same renames on adopting the standard.

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

[Unreleased]: https://github.com/Squishiba/refdes/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Squishiba/refdes/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Squishiba/refdes/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Squishiba/refdes/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Squishiba/refdes/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Squishiba/refdes/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Squishiba/refdes/releases/tag/v0.1.0
