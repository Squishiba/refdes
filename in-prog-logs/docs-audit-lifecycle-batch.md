# Docs accuracy audit — lifecycle, change-tracking, parts, multi-board, workspaces, schema-reference, vocabulary, troubleshooting

Scope: eight docs pages, audited in that order, against the real CLI
(`python -c "import sys;from refdes.cli import main;sys.exit(main(sys.argv[1:]))"`)
and `refdes schema` JSON. Not owned by another worker and therefore not
touched: `docs/cli-reference.md`, `docs/standard-library.md`, `AGENTS.md`.

Scratch projects live under `.scratch/proj*` (gitignored), each a copy of
the repo's own `items/` + `refdes-project.yaml` + `refdes-schema.yaml`.
One bound was relaxed in the scratch copies only (`BND-THM-001`
`<= 0.15 W/in^2` -> `<= 0.35 W/in^2`) so the project builds clean enough to
exercise the release gate; the repository's own items are unmodified.

## docs/lifecycle.md

### Claims checked

- `release_gate:` defaults — all eight rules, both halves, exact booleans:
  verified against `src/refdes/model.py:57-68` `RELEASE_GATE_DEFAULTS`.
- Unknown `release_gate:` key is a load-time `SchemaError` naming the eight
  rules with a difflib suggestion: ran `check` in `.scratch/proj2` with
  `draft_itemz:` — got `configuration error: ... is not a known rule (one of
  ['draft_items', ...]). Did you mean 'draft_items'?`. Mechanism confirmed at
  `src/refdes/configcheck.py:128-133`.
- Rule evaluation order in the blocked-stamp table: `RULE_NAMES` order
  matches the doc's table and the printed order
  (`src/refdes/lifecycle.py:597`, `cli.py:250-257`).
- The eight rule bodies against the doc's "Blocks a release when..." table,
  one by one, at `src/refdes/lifecycle.py:508-582`: draft-item detection
  (`_is_draft`), `unpinned_citations` = citation state `unpinned`,
  `missing_kept_copies` = state `cache_missing`, `uncovered_requirements` =
  stage `open`, `unverified_requirements` = stage `!= verified`,
  `info_check_failures` = per-item `_severity_for(spec, item) == INFO` and a
  failing check (so the "resolves per item, not per type" claim holds),
  `unaccepted_board_moves` / `unaccepted_workspace_moves` = `project.board_moves`
  / `project.workspace_moves`. Draft items are excluded from both coverage
  rules (`_coverable_offenders`) — matches the doc.
- Gate-blocked output shape and exit code: ran `release rev-b` in
  `.scratch/proj` — printed the table to stderr, exit 1, exit path
  `cli.py:284-288`.
- Successful release: ran `release rev-b` in `.scratch/proj3` with the three
  failing rules switched off — `release 'rev-b' stamped: 20 items, all gates
  passed.`, the `.refdes/baselines/rev-b.yaml` path, and the design-log
  nudge with a real `date:` line (`cli.py:316-336`).
- `revision` is the same shape minus the gate and minus the log nudge: ran
  `revision rev-c` — `revision 'rev-c' stamped: 20 items.`, no log nudge.
  Matches `cli.py:327-335`.
- `gate:` present only for `kind: release`: read both stamped files — the
  revision baseline has no `gate:` key.
- Re-stamping an identical name is a no-op, exit 0, file untouched: re-ran
  `release rev-b` — `release 'rev-b' unchanged since <ts> -- nothing to
  stamp.`, exit 0.
- Re-stamping a name with different content errors and writes nothing: after
  changing an item, `release rev-b` exited 1 with
  `error: 'rev-b' is already stamped as a release ... delete
  .refdes\baselines\rev-b.yaml first`.
- `--no-write` is the global flag, before the subcommand: ran
  `--no-write release rev-d` — `release 'rev-d' not stamped (--no-write):
  would stamp 20 items to .refdes/baselines/rev-d.yaml.`, exit 0, no file.
- `refdes audit` is the third command; the "Baselines:" section header, the
  `most recent stamp:` / `most recent release:` lines, and the two
  `Since last revision` / `Since last release` blocks: ran `audit` in
  `.scratch/proj3` and `.scratch/proj4`. The unstamped project prints
  `(none stamped yet -- project is in draft)` plus `(no revision stamped yet)`
  / `(no release stamped yet)` — exactly the doc's "not an error" claim.
- `relabelled`: renamed `REQ-B-PWR-001` -> `REQ-B-PWR-007` keeping the key,
  re-ran `audit` — `relabelled 1` with
  `REQ-B-PWR-001 -> REQ-B-PWR-007   (bv170ga0xfk)`, i.e. removed+added is
  *not* what it reports.
- `removed` lines carry `(type) title`: deleted a requirement from
  `.scratch/proj3` — `removed 1` with
  `REQ-B-PWR-001 (requirement) 'The board shall accept...' — no longer in
  the project`.
- `HASH_FORMAT` is currently 5, and the 1-5 history in "Hash format
  versioning": `src/refdes/build.py:1404-1435` (comment enumerates exactly
  formats 2/3/4/5 with the same "an item with none hashes exactly as under
  the previous format" framing the doc repeats).
- The hash-format migration rule (carry forward on match, `uncomparable`
  otherwise) and the "reported as `uncomparable`, never as `changed`" claim:
  `src/refdes/lifecycle.py:348-401` and `cli.py:558-564`, `cli.py:291-306`.
- `refdes keys adopt` names what it cannot carry, as
  `uncomparable baseline entry <name>: <id>`: `cli.py:1050`. Ran
  `keys --help` and `keys adopt --help` to confirm the subcommand exists and
  takes `--dry-run`.
- Relative links: `change-tracking.md`, `workspaces.md`,
  `design-log.md#after-a-release` all resolve (`docs/design-log.md:193` is
  the `## After a release` heading).

### Discrepancies fixed

1. **The baseline-file example was missing the `standard:` block and most of
   the per-item fields.** A real stamped baseline carries
   `standard: {base, version}` (the standard pin at stamp time), and each
   `items:` entry carries `hash_format`, `key`, and — when they apply —
   `verdict`, `calc_hash`, `calc_refs`. The doc showed only
   `{hash, type, title}`, which is now the *majority* shape rather than the
   whole one. Verified against `.refdes/baselines/rev-b.yaml` in
   `.scratch/proj3` and the builder at `src/refdes/lifecycle.py:300-329`
   (`items_map()`). Added the `standard:` block, the extra per-item fields
   in the example, and one sentence naming which of them are conditional.
   Also corrected the surrounding "assembly, not new machinery" sentence,
   which listed only `item.content_hash`, `item.type`, `item.title` and the
   gate results, to include the standard pin and the conditional fields.
2. **The `removed` line in the `audit` transcript was quoted with double
   quotes.** The printer uses Python `repr` (`cli.py:569`), so a title with
   no embedded quote renders in single quotes. Corrected the transcript to
   `'Legacy input protection'`.

### Unverifiable claims left as-is

- The illustrative project in the console transcripts (`REQ-PWR-004`,
   `BND-THM-002`, 41 items, `refdes_version: "0.3.0"`, `stamped_by: "jbin"`)
   is a worked example, not a runnable fixture; only the *shape* of the
   output was checked. The version in the example is deliberately not the
   installed one.
- "`--no-write` … report what would be stamped" — the flag's effect is
   confirmed, but the doc's phrasing of the `revision` variant's help text is
   quoted from `refdes revision --help`, which I ran and which matches.
- The prose about *why* `unverified_requirements` defaults off, and the
   rationale paragraphs about candidate→selected severity, are design
   argument, not verifiable behaviour. Left as written.

## docs/change-tracking.md

### Claims checked

- The three `on_change` modes and their names: `src/refdes/model.py:14-22`
  `ON_CHANGE_MODES = (INVALIDATE, LOG, IGNORE)`, with the source comment
  stating `log` and `ignore` are currently indistinguishable — the exact
  claim the table's "the last two columns are implemented; the first is
  not" note makes.
- The hash covers `invalidate` fields only, and links/body participate:
  `src/refdes/build.py:1469-1484` (`mode != INVALIDATE: continue`) and
  `compute_hashes` at `build.py:1797`.
- Precedence "item field override → whole-item mode → schema field →
  project default": `Item.on_change_for` at `src/refdes/model.py:566-574`
  returns in exactly that order, with the same precedence applied to `body:`
  (`build.py:1481-1482`).
- `history.default` falls back to `invalidate` when `history:` is absent:
  `src/refdes/configcheck.py:247` (`self.mode(block.get("default"), ...,
  "invalidate")`). Ran `refdes init` in `.scratch/fresh` — the starter
  `refdes-project.yaml` has no `history:` block at all, so the fallback
  *is* the default a fresh project gets; the repo's own project file spells
  it out explicitly.
- Scalar whole-item form `history: ignore` is accepted and validated
  against the three modes: `src/refdes/parse.py:412-420` (raises a
  `project.error` for anything outside `ON_CHANGE_MODES`).
- Omitting `reason:` on a per-field override is a warning, not an error:
  `src/refdes/parse.py:423-428`; the `refdes audit` printer shows
  `NO REASON GIVEN` in that case (`cli.py:607`).
- The `audit` transcript on the page is accurate. Ran `refdes audit` in
  `.scratch/proj3` and compared: the `Schema fields not tracked as
  'invalidate':` block for `bound` lists exactly
  `last_reviewed ignore / note log / owner log / source log / tags ignore`,
  the item-level line is
  `  REQ-PWR-004    owner -> ignore  — Owner rotates weekly during bring-up; not a meaningful change.`,
  and `Append-only entries edited after sealing:` prints `(none)`.
- The schema example in "Setting it" validates as written. Copied it
  verbatim into `.scratch/proj4/refdes-schema.yaml` and ran `check` — exit
  0, no config error. Every field type used (`limit`, `text`, `person`,
  `list`, `date`) is in `_FIELD_TYPE_MAP`
  (`src/refdes/schema_json.py:32-46`); `body: { on_change: invalidate }` is
  legal (`configcheck.py:472-475`).
- `content_hash` appears in `items.json` and at the foot of every item page:
  ran `refdes index` (found `"content_hash": "f5a7efe654062d62"` in the
  JSON) and `refdes build`, then grepped `_site/bnd-thm-001.html` for the
  same hash — found in a `content hash <code>…</code>` footer.
- "Imported items keep the hash their own project computed": the docstring
  at `src/refdes/build.py:1803-1804` states it, and `compute_hashes` is
  reached only through the ordinary build path over `project.local_items`
  for stamping purposes.
- `hash_format` currently 5 and the format history: matches
  `src/refdes/build.py:1404-1435`, same as the lifecycle.md check.
- The list of commands that trigger the hash-format migration — `audit`,
  `revision`, `release`, `former-ids propose`, `keys adopt` — was tested
  rather than read. Downgraded every entry in
  `.scratch/proj5/.refdes/baselines/rev-c.yaml` to `hash_format: 4` and
  ran each:
  - `refdes audit` — carried 19 of 20 entries forward to format 5, left
    `DEC-PWR-001` behind and reported it in an `uncomparable 1` line with
    the "older-format entries whose stored hash can't be checked" note
    (`cli.py:558-564`). Matches the doc exactly.
  - `refdes former-ids propose` (writable) — likewise carried 19 forward.
  - `refdes former-ids propose --no-write` — left the file byte-identical.
  - `refdes check` — left the file untouched, i.e. `check` correctly is
    *not* in the list.
- `uncomparable baseline entry <name>: <id>` and
  `uncomparable seal entry <file>: <id>` are the `keys adopt` wording:
  `src/refdes/cli.py:1050` and `cli.py:1059`.
- Relative links: `lifecycle.md#the-diff-what-changed-and-since-when`
  (`docs/lifecycle.md:228` is that heading) and the in-page
  `#what-is-not-built-yet` (`docs/change-tracking.md:180`). Both resolve.

### Discrepancies fixed

None. Every claim checked held.

### Unverifiable claims left as-is

- The "Why `log` exists" and "Changing the policy later" sections argue
  about the *future* history layer (suspect-link badge fatigue; re-blessing
  on a policy change). Design intent, not current behaviour; explicitly
  labelled as such in the page text. Left as written.
- "The `on_change` policy and the content hash it depends on are
  implemented and tested" — the implementation half is confirmed above; the
  "and tested" half is a statement about `tests/`, which I did not audit
  (out of scope for a docs pass). Noted rather than changed.

## docs/parts.md

### Claims checked

- `parts.html` global plus `parts-<board>.html` scoped exist: built
  `.scratch/proj` and listed `_site` — `parts.html` and
  `parts-board-a.html` present. The workspace-scoped variant is emitted
  from the same code path (`src/refdes/render.py:1256`,
  `parts-{workspace_key}.html`).
- `refdes audit` gets a "Parts:" section listing every part number, not
  filtered to multiply-used ones: ran `refdes audit` in `.scratch/proj3` —
  got a `Parts:` heading with
  `TPS62913  used by CMP-PWR-001 (component), CMP-PWR-001 (citation)
  — board: board-a`, and that part is used exactly once in the project, so
  it is demonstrably not filtered to multi-use.
- The parts page is derived, not authored: the section is computed at build
  time from field values; no `links:` entry is involved. The
  `item.links`-only scope of the cross-workspace lint is confirmed at
  `src/refdes/workspaces.py` (see the workspaces.md check below).
- `refdes new component --list` prints the documented skeleton: ran it in
  `.scratch/proj` — got a `---` / `defaults:` block with
  `type: component` / `status: candidate` and one empty `items:` entry,
  with the type's real optional fields (`part_number`, `citations`,
  `drop_in`, `alternate`, …) commented out. The doc's
  "prints this skeleton (with the type's own status default and field set)"
  is accurate, and the redirect form
  `refdes new component --list > items/power/candidates.yaml` is exactly
  what `refdes new --help` suggests.
- The dead-`defaults:` warning: emptying a candidate list so no entry
  carries `status: candidate` produced
  `this file's defaults: declares 'status: active' but no item in it has
  that status -- the defaults entry is dead configuration. Set an item's
  status to 'active', or drop the 'status:' key from defaults:.`
  (`src/refdes/parse.py:590-620`), matching the doc's description.
- `{{index by=...}}` exists and is documented on the blocks page:
  `docs/blocks.md` present and linked.
- Links: `markdown.md#citing-a-datasheet`, `blocks.md`,
  `workspaces.md`, `links.md#part-equivalence-drop_in-and-alternate` — all
  targets exist (`docs/links.md` has the `drop_in`/`alternate` section).

### Discrepancies fixed

None.

### Unverifiable claims left as-is

- "A component's own fields table links straight to its part's section on
  `parts.html` when something else also uses it" and "A board whose only
  parts are included ones now gets a `parts-<board>.html` (and the nav link
  to it) instead of no page at all" (that sentence is on multi-board.md, and
  its mechanism is the `includes:` behaviour, which I did verify). The
  first is a rendering detail I confirmed only indirectly — the scoped
  pages exist and carry part rows; I did not construct a two-board shared
  part to see the cross-link on the component page specifically. Noted.
- The "exact string, deliberately" section is a design argument about
  normalization schemes. Left as written.

## docs/multi-board.md

### Claims checked

- `boards:` is opt-in and adding it later changes no ID: the doc's claim is
  structural (a registry adds resolution, not identity), and the board
  token lint (below) confirms the registry is a lint, not a renamer.
- Two boards mapping to the same path segment is a load-time hard error:
  set `board-b.path: board-a` in `.scratch/proj6` and ran `check` — got
  `configuration error: boards.board-b and boards.board-a both map to
  items/board-a/ — path segments must be unique`, before any item was
  parsed (the message names only the two boards).
- The board `token:` lint: renamed an item on `board-b` to `REQ-PWR-004`
  (prefix without the token `B`) and ran `check` — got
  `WARNING items/board-b/requirements.yaml:14 [REQ-PWR-004] — item is on
  board 'board-b' (token 'B'), but its id prefix 'REQ-PWR' does not
  contain that token`. Message and file:line match the doc.
- Per-board pages: `document-<board>.html`, `coverage-<board>.html`,
  `log-<board>.html`, `summary-<board>.html` — all four are written from
  `src/refdes/render.py:1124-1181`; confirmed in a built workspace project
  that each registered board got `document-`/`coverage-`/`summary-` pages,
  and `log-` is written only when the board has log entries
  (`render.py:1149`, guarded), which is the same conditional the page
  describes two sections later.
- "A board with no items yet gets no report pages and no nav group":
  registered `board-c` with no items in `.scratch/grp` — no
  `coverage-board-c.html` was written, and the conformance warning for it
  omitted the `— see coverage-board-c.html` pointer, exactly as the page
  says ("that warning therefore leaves out the `— see
  coverage-<board>.html` pointer").
- `refdes check --board NAME` reports only that board's diagnostics while
  the project still parses: ran `check --board board-a` in `.scratch/proj`
  — project-wide coverage warnings still printed, and the count line
  reflected the narrowed report.
- Per-board seals: after a build of `.scratch/proj`, `.refdes/` contains
  `log-seal-board-a.yaml` and no plain `log-seal.yaml` — the log entries
  there resolve onto a board.
- `--accept-board-move` accepts workspace moves too and there is no
  separate flag: `refdes build --help` shows `--accept-board-move  accept a
  recorded board or workspace change for an item`, and no
  `--accept-workspace-move` exists. Verified functionally: moved a file
  across a workspace boundary, got the drift warning naming
  `--accept-board-move`, and one `build --accept-board-move` cleared it for
  both kinds.
- The board-move warning text and its `--accept-board-move` advice:
  reproduced in the workspace project as
  `REQ-B-PWR-001 moved from workspace 'product-b' to 'product-a' since the
  last build. Run 'refdes build --accept-board-move' if this is deliberate,
  or move the file back.`
- `conforms_to:` semantics: built a `group` item `GRP-DBG` with a member
  requirement in `.scratch/grp` and set `board-b.conforms_to: [GRP-DBG]` —
  got
  `IFC-DBG-001 is not satisfied on board 'board-b' (board conforms to
  GRP-DBG) -- its open stage counts only board-b's own items -- see
  coverage-board-b.html`, matching the doc.
- A bare `conforms_to: GRP-DBG` is a configuration error, reported once:
  ran it and got
  `configuration error: refdes-project.yaml: boards.board-b conforms_to must
  be a list of group ids, got 'GRP-DBG' -- write conforms_to: [GRP-001]`.
- `conforms_to:` naming a nonexistent group is a build error: set
  `[GRP-DBUG]` and got
  `ERROR refdes-project.yaml — boards.board-b conforms_to 'GRP-DBUG', which
  does not exist -- a group item must be declared before a board can
  conform to it` (`src/refdes/build.py:660-665`).
- `includes:` is display-only and never counts: registered
  `GRP-COMMON` in `items/shared/` (no board), pointed a board-a
  requirement at it with `part_of:`, and set
  `board-b.includes: [GRP-COMMON]`. After a build, `IFC-DBG-001` is listed
  on `_site/document-board-b.html` with the pill `shared, via GRP-COMMON`,
  while `refdes index` still reports `"board": "board-a"` for that same
  item — displayed on the other board, owned by none of it, and the
  membership manifest unchanged. Exactly the documented split.
- `includes:` is a list of strings with the same two error postures:
  `src/refdes/configcheck.py:323-328` mirrors the `conforms_to` checker
  (`write includes: [GRP-001]`), and `build.py:677` documents
  `validate_includes` as mirroring `validate_conforms_to`.
- Imports: built an upstream `.scratch/platform-interfaces` project with
  `site.version: "2026.3"`, imported its `_site/items.json` from
  `.scratch/board-a` with a matching pin — 2 items, clean.
- Version-pin refusal, with cascading errors: repinned to `"2026.9"` and
  got `import 'platform' is pinned to version '2026.9' but the artifact
  declares '2026.3'. Rebuild the upstream project or update the pin
  deliberately.`, followed by unresolved-reference errors for the items
  the refused import would have supplied — matching "Expect cascading
  errors after a refused import".
- An upstream limit change fails the downstream board: tightened the
  imported `IFC-CAN-001` from `<= 3 A` to `<= 2 A`, rebuilt upstream, and
  the unchanged board-a decision then failed with
  `I_pin violates IFC-CAN-001: worst case 2.4 A vs <= 2 A`, exit 1. The
  payoff example is real.
- Imported IDs colliding with local IDs is a hard error: added a local
  `IFC-CAN-001` and got `import 'platform' defines 'IFC-CAN-001', which
  already exists (items/local.yaml:7). IDs must be unique across every
  imported project — give each project its own prefix.`
- An imported item can be checked against (`limit` works) — confirmed by
  the same failing check above, which is `against:` an imported bound.
- The `refdes build` `--dry-run` / `--no-write` carve-out in the
  "any build that records" sentence: `refdes build --help` shows
  `--dry-run  render the site without sealing`, and the global
  `--no-write` is documented on every subcommand's help. The stronger
  claim — that read-only `check` never prunes stale manifest entries — is
  consistent with the `check --help` text ("Nothing of the project's own
  is written ... no board or citation manifest"), which I ran and which
  left `.refdes/boards.yaml` untouched in every scratch project.
- Links and anchors: `pages.md#grouping-a-page-under-a-board`
  (`docs/pages.md:68`), the in-page `#a-board-with-no-items-yet`
  (`docs/multi-board.md:263`), `workspaces.md`, `standard-library.md`,
  `design-log.md`, `markdown.md#citing-a-datasheet`, `ids.md` — all
  targets present. `standard-library.md` and `cli-reference.md` are owned
  by another worker and were not edited.

### Discrepancies fixed

1. **The quoted "not a list" configuration error ended with the wrong
   example.** The page showed
   `write conforms_to: [GRP-DBG]` (echoing the value that was just
   rejected). The real message is fixed text ending
   `write conforms_to: [GRP-001]` — verified by running it, and by
   `src/refdes/configcheck.py:311-312`. Corrected the transcript. The
   `includes:` sibling message (`write includes: [GRP-001]`) was already
   consistent with the source.

### Unverifiable claims left as-is

- "The site becomes unusable at four or five boards" and the other bullets
  under "When this stops working" are judgement calls, not verifiable
  behaviour. Left as written.
- "Legacy projects key each entry by display id; after `refdes keys adopt`,
  the immutable surrogate is the map key" — the legacy half is confirmed
  by the manifest `.scratch/ws/.refdes/boards.yaml` actually wrote
  (`DEC-B-014: board-b`). The adopted half is shown in the page's example
  and is produced by `keys adopt`; I confirmed `keys adopt` exists with
  `--dry-run` but did not run a full adoption, since that rewrites every
  item file in the scratch copy and nothing on this page depends on the
  difference beyond the manifest shape the source already documents.
- "The federated view does not exist" — a negative claim about a roadmap
  item; the `refdes` subcommand list (`--help`) contains no federated-view
  command, which is consistent with it.

## docs/workspaces.md

### Claims checked

All of this was exercised in `.scratch/ws`, a purpose-built project with
`item_layout: workspace`, three registered workspaces (`platform` marked
`shared: true`), two registered boards, and items at
`items/platform/shared/`, `items/product-a/board-a/` and
`items/product-b/board-b/`.

- The `workspaces:` block keys and their defaults (`label` = the key,
  `shared` = `false`, `path` = the key): `WORKSPACE_KEYS = {"label",
  "shared", "path"}` at `src/refdes/configcheck.py:56`, and each default is
  what the checker passes (`configcheck.py`, the `workspaces` block).
- `item_layout` is a fixed choice of `flat` or `workspace`, not a path
  template: verified by switching the scratch project between the two
  values; the board is then read from the 1st vs 2nd path segment, with the
  error text naming exactly that ("no board: it has no second items/ path
  segment to read a board from under item_layout: workspace").
- `path:` is honored as an alias for the `items/` segment: declared a
  second workspace `renamed-key` with `path: product-b` and got
  `workspaces.renamed-key and workspaces.product-b both map to
  items/product-b/ — path segments must be unique`, which proves the alias
  resolved.
- The cross-workspace lint message, verbatim: with
  `DEC-B-014 satisfies: [REQ-A-PWR-001]` crossing `product-b` into
  `product-a`, `check` printed
  `satisfies points at REQ-A-PWR-001, in workspace 'product-a', which is
  not marked shared: true -- workspace 'product-b' would gain a hidden
  dependency on it`. Matches the page's transcript.
- The `shared: true` exemption: repointed the same link at the platform
  workspace's `IFC-CAN-001` and the diagnostic disappeared entirely.
- A link within one workspace is exempt: the same-workspace case produced
  no diagnostic in the runs above.
- The lint walks only `item.links` (authored), never a derived view: the
  message is emitted from resolved link targets, and the parts page (a
  derived index) provably does not trip it — the `parts-<workspace>.html`
  report is generated from field values with no link involvement
  (`src/refdes/render.py:1254-1264`, and the same for boards at 1170).
- `cross_workspace_severity` defaults to `warning` and accepts
  `error | warning | info`: the repo's own `refdes-project.yaml` carries
  `cross_workspace_severity: warning`; the value is validated in the same
  config pass as the rest.
- Override precedence `workspace:` > `defaults.workspace` > path: switched
  the scratch project to `item_layout: flat` and added
  `workspace: platform` to a file's `defaults:`. That file's item stopped
  being reported as workspace-less while every other item was, which is
  the override winning over a path that no longer encodes a workspace.
- The `workspace:` override works under **either** layout: that is exactly
  the flat-layout run above.
- An override naming an unregistered workspace is a build error: the
  flat-layout run produced `no workspace: 'board-a' is not in the
  workspaces: registry and no workspace: key was set` for items whose path
  segment was not a registered workspace.
- A board key and a workspace key colliding is a load-time error naming
  both sides: registered `product-a` as *both* a workspace and a board and
  got
  `'product-a' is declared as both a board and a workspace — boards and
  workspaces share one namespace for generated report names (e.g.
  coverage-product-a.html); rename one of them`. Matches the page.
- Scoped pages per workspace: after a build of `.scratch/ws`, `_site`
  contained `document-`, `coverage-` and `summary-` pages for
  `platform`/`product-a`/`product-b`. `log-`, `references-` and `parts-`
  were absent — because the project has no log entries, citations or parts
  — and each is written under an `if` on report presence
  (`src/refdes/render.py:1230`, `1244`, `1254`), the same conditional the
  page states for boards one section earlier.
- The same five page kinds for a board, including `parts-<board>.html`:
  `render.py:1124-1181` for boards, `1209-1265` for workspaces, with
  `parts-` in both lists.
- `refdes build --accept-board-move` accepts workspace moves and there is
  no `--accept-workspace-move`: `refdes build --help` shows
  `--accept-board-move  accept a recorded board or workspace change for an
  item` and no workspace-specific flag. Moving a file across a workspace
  boundary produced a warning naming `--accept-board-move`, and running it
  cleared the drift; `.refdes/boards.yaml` then carried both sections.
- The drift manifest shape, both sections, and the legacy scalar form: read
  the `.refdes/boards.yaml` a build actually wrote —
  `boards:` with `DEC-B-014: board-b` style entries and a `workspaces:`
  section with the same. Matches the page's "Legacy `DEC-A-001:
  product-a` scalars remain readable, and non-adopted projects keep writing
  that legacy shape."
- `refdes audit` lists workspace moves in their own section, next to board
  moves: ran `audit` and got a `Workspace moves since the manifest was last
  written:` heading with `(none)` after acceptance, alongside the
  pre-existing `Board moves since the manifest was last written:` heading.
- A project with no `workspaces:` never gets a `workspaces:` section
  written: `.scratch/proj` (flat, no `workspaces:`) wrote a
  `.refdes/boards.yaml` with a `boards:` section and no `workspaces:`
  section at all.
- `refdes check --workspace NAME` narrows only what is printed: ran
  `check --workspace product-a` in `.scratch/ws` — the DEC-B-014
  cross-workspace warning (product-b's item) was not printed, while the
  project-wide coverage warnings still were, and the total item count
  stayed the project's. Ran `--board board-b --workspace product-b`
  together: both filters applied, matching the "combinable" claim.
- Links: `multi-board.md#separate-projects-with-imports` (that heading
  exists in multi-board.md) and the in-page
  `#a-board-with-no-items-yet` on multi-board.md. Both resolve.

### Discrepancies fixed

None.

### Unverifiable claims left as-is

- "The sidebar nests each board's group inside its workspace's group …
  a board with no items yet … falls back to a top-level group": a nav
  rendering detail. The scoped pages it depends on are confirmed above; I
  did not diff the sidebar markup for a nested-vs-flat group, since the
  scratch project renders the same nav machinery in both layouts and
  nothing on this page turns on the difference.
- The "Why" section's argument about `items/` being scanned recursively but
  board derivation reading one segment is structural, and is what the
  `item_layout` error messages above independently confirm.

## docs/schema-reference.md

### Claims checked

- **The generated per-type examples block.** The page says it is written by
  `python docs-site/gen_examples.py` and gated by
  `tests/test_docs_examples.py`. Ran `python -m pytest
  tests/test_docs_examples.py -q` — 6 passed, and ran `refdes new <type>`
  for all seven types in a hardware@3 project and compared each against
  the page. All seven match byte for byte. (My first comparison showed a
  `board:` field on the `log` example; that is the *repo's own*
  `refdes-schema.yaml` overlay, which the generator deliberately replays
  without — confirmed by the generator docstring and by the fact that the
  gate test passes. Not a docs error.)
- `site` keys and their defaults: `SITE_KEYS` at
  `src/refdes/configcheck.py:47-49` is exactly the eight keys in the page's
  table, and the defaults (`_site`, `pages`, `default`, empty `nav`/
  `version`/`assets`/`tokens`) are the values the checker passes.
- The four built-in theme names and the "unknown name is a build error
  naming the themes that exist, never a silent fallback" claim: set
  `site.theme: nonexistent` and got
  `site.theme 'nonexistent' is not a theme. Available themes: default,
  high-contrast, paper, slate`. The four names match the page.
- Theme-token safety: an unknown token name is refused
  (`site.tokens.--nosuchtoken is not a design token`), and a non-plain
  value is refused
  (`site.tokens.--bg is not a plain CSS value: 'expression(' is not
  allowed. A theme token takes one value, like #b3541e or Georgia, serif --
  not a rule, a comment, or a URL.`), matching the prose.
- The contrast claim ("a pair below 4.5:1 … is a warning naming the pair
  and the measured ratio. The build proceeds"): built a `slate` project
  with a low-contrast `--accent` override and got warnings of the form
  `theme contrast: theme 'slate' (dark): --accent on --bg is 3.60:1,
  below the 4.5:1 WCAG AA minimum` — pair and ratio both named — and the
  build still wrote the site.
- `assets/theme.css` is emitted and linked after `style.css`: after the
  build, `_site/assets/` contained both `style.css` and `theme.css`.
- `date_format`: default is `YYYY-MM-DD`; `MM/DD/YYYY` loads; a malformed
  one is refused with
  `date_format must use YYYY, MM, and DD exactly once, separated by one
  repeated '-', '/', or '.', got 'YYYY-DD/MM'`. Matches the page.
- `sets` carries exactly `fields`/`links`/`body` and nothing else:
  `_SET_ENTRY_KEYS` at `configcheck.py:85` plus the explicit error at
  `configcheck.py:412-417` ("a set carries fields, links and body only").
- `link_types` keys: `LINK_TYPE_KEYS = {"inverse", "label", "trace",
  "doc"}` (`configcheck.py:86`) — exactly the page's four rows. The
  standard sets `trace: false` on exactly `amends`, `records`,
  `supersedes` and `addresses` (grepped `base.yaml`), as the page states.
- `types` keys: `TYPE_KEYS` at `configcheck.py:58-77` is the 16-key set
  the page's table describes.
- The `doc:` example validates and propagates: copied the page's `doc:`
  block verbatim into `.scratch/th/refdes-schema.yaml`, ran `check` (exit
  0), and found the type and field `doc:` strings present in
  `.refdes/schema.json` as JSON Schema `description` — exactly the
  "reaches the editor through the two exports" claim.
- `doc:` error postures: `doc: 42` →
  `types.thermal_budget.doc must be a non-empty string, got 42`;
  `docs:` → the unknown-key error ending
  `Did you mean 'doc'?`. Both as documented.
- All four `required_when` rules, each run: `required: true` together with
  `required_when:` is a `SchemaError` ("declares both 'required: true' and
  'required_when:'"); a condition naming an undeclared field is refused; a
  value outside the enum's `choices:` is refused, naming the choices; and a
  condition field that is not `type: enum` is refused
  ("required_when condition fields must be type: enum").
- The standard's own two `required_when` uses: `decision.rationale` with
  `{status: rejected}` and `component.rationale` with `{links: alternate}`
  (`src/refdes/standards/hardware/v3/base.yaml:229` and `:265`).
- `satisfying_statuses` requires a `status` field: declared it on a type
  with no `status` and got
  `types.my_type.satisfying_statuses requires a 'status' field on
  my_type`.
- `check_severity` must be one of the three levels: `check_severity:
  bogus` → `must be one of ['error', 'warning', 'info'], got 'bogus'`.
- Citation entry keys: `_FIELD_TYPE_MAP["citations"]` at
  `src/refdes/schema_json.py:71-87` lists exactly `path` (the only
  `required`), `rev`, `page`, `section`, `part_number`, `keep_copy`, `id`
  — the page's list, in the same terms.
- `imports` keys: `IMPORT_KEYS = {"name", "items", "version"}`
  (`configcheck.py:57`), matching the page's three rows.
- `boards` keys: `BOARD_KEYS = {"label", "token", "path", "conforms_to",
  "includes"}` (`configcheck.py:55`).
- `workspaces` keys: `WORKSPACE_KEYS = {"label", "shared", "path"}`
  (`configcheck.py:56`) — matches the page's three rows.
- The board path-collision error quoted on this page (and on multi-board.md)
  is the real one: reproduced as
  `configuration error: boards.board-b and boards.board-a both map to
  items/board-a/ — path segments must be unique`.
- Item-level `history` scalar and mapping forms, and the precedence line:
  same verification as on change-tracking.md (`model.py:566-574`).
- All 26 relative links and anchors on the page were resolved by hand
  against the target files' headings — `pages.md`, `change-tracking.md`,
  `checks.md` (both anchors), `coverage.md` (both anchors), `blocks.md`,
  `links.md` (+ the `drop_in`/`alternate` anchor), `math.md`, `ids.md`,
  `parts.md`, `multi-board.md` (both anchors), `output.md` (both anchors),
  `markdown.md` (both anchors), `design/composition.md`,
  `design/backlog.md`, `standard-library.md` (both anchors), and the two
  in-page anchors `#doc` and `#extends`. `cli-reference.md` is owned by
  another worker and was not edited.

### Discrepancies fixed

1. **`equations:` was missing from the "Top level" block**, on a page whose
   opening sentence claims to cover "Every key in `refdes-project.yaml`".
   It is a real block key (`_PROJECT_SETTING_KEYS` at
   `src/refdes/schema.py:56-68`), it validates as a top-level block (a bad
   `equations:` entry is reported as
   `equations.ohms_law must be a mapping with 'params' and 'expr'`), and
   two other pages already document it (`math.md:386`, and the retired-
   config error text quoted in `troubleshooting.md:17`). The other nine
   block keys were all listed. Added it, with a one-line gloss.
2. **`boards.includes` was missing from the `boards` key table.** It is a
   real board key (`BOARD_KEYS`), it is documented at length on
   `multi-board.md` ("Including a shared group"), and its behaviour was
   verified there. Added the table row, the example line, and a pointer to
   that section.
3. **`types.plural` was missing from the `types` key table.** It is in
   `TYPE_KEYS`, is the third identity key the `extends` section already
   names ("declaring all three is required"), and defaults to
   `label` + `s` (`src/refdes/schema.py:663`). Added the row.
4. **The `extends:` example does not load under the pinned standard.** The
   page shows `thermal_bound` with `extends: bound`, but in hardware@3
   `bound` is itself `extends: requirement` (`base.yaml:201`), so
   single-level inheritance rejects it:
   `types.thermal_bound.extends names 'bound', which itself extends
   'requirement'. Single-level inheritance only; thermal_bound must extend
   'requirement' directly or not use extends:.` Kept the example's shape
   (it illustrates the identity keys well) and added a paragraph naming the
   trap, since the same error is the page's own documented rule and a
   reader following the example verbatim would hit it. Verified the
   corrected parent loads.
5. **The `site.tokens` example does not load.** It showed a bare
   `--accent`/`--sans` pair *and* `light:`/`dark:` headings in one block,
   which the checker refuses:
   `site.tokens.--accent is not valid here. A tokens: block that uses the
   light and dark headings may contain only them; a bare --token pair
   applies to both palettes.` The page's own prose two paragraphs below
   already states that rule correctly, so the example contradicted its own
   text. Split it into the two legal forms and added one sentence saying
   they are alternatives rather than a mix. Both corrected forms were
   loaded and built successfully.

### Unverifiable claims left as-is

- **`docs/output.md` carries the same broken `site.tokens` example**
  (lines 35-42, `theme: paper` with a bare `--accent` beside
  `light:`/`dark:`). It is not one of the eight pages in this batch, so I
  did not edit it; the fix is the same split. Flagged for whoever owns it.
- The "Filled-in examples" preamble's claim that the generator is run
  "against the resolved **hardware@3** schema pinned in this repo's
  `refdes-project.yaml`" — confirmed via `gen.standard_pin()` (the gate
  test asserts base `hardware` and an integer version), and the examples
  themselves match live output.
- "That fallback, and the requirement-only restriction on the per-item
  coverage warnings it preserves, is removed in refdes 1.0" is a roadmap
  statement about a future release, not current behaviour. Left as written.
- `site.assets` / `site.nav` / `site.pages` semantics are described
  behaviourally and are cross-referenced to `pages.md` and `markdown.md`;
  I confirmed the keys and defaults rather than re-auditing those pages
  (already audited by a previous session).

## docs/vocabulary.md

### Claims checked

- **The generated block is current.** The page says it is written by
  `python docs-site/gen_examples.py` and gated by
  `tests/test_vocabulary_page.py`. Ran `python -m pytest
  tests/test_vocabulary_page.py -q` — 22 passed. Also ran
  `python docs-site/gen_examples.py --check`, which reported both
  `docs/schema-reference.md` and `docs/vocabulary.md` up to date, exit 0.
- The block structure the page's preamble promises — item types, link
  verbs, sets, engine-reserved keys — is present in that order
  (`## Item types` :42, `## Link verbs` :272, `## Sets` :532,
  `## Engine-reserved keys` :699).
- Engine-reserved keys are "defined in code, not YAML", in
  `refdes/vocabulary.py`: the module docstring says exactly that
  (`vocabulary.py:20-22`) and `RESERVED_KEYS` is the single definition
  site. Compared the page's eleven `###` entries under "Engine-reserved
  keys" against `sorted(RESERVED_KEYS)` — the same eleven names, in the
  same order.
- "A term with no definition says so": `NO_DEFINITION = "No definition."`
  at `vocabulary.py:51`, with the source comment explaining that project
  terms are not required to define themselves. The page carries that
  exact string.
- "Every example is schema-true … real values from the standard and this
  repo's `items/` tree, never invented fields": spot-checked the
  engine-reserved examples against the real files —
  `key: 1zn5skrv6k3` / `id: REQ-PWR-001` is
  `items/requirements/power.yaml`, and
  `id: BND-THM-001` / `former_ids: [CON-THM-001]` is
  `items/constraints/thermal.yaml`. Both are real.
- A built site carries the same page as its own `vocabulary.html`,
  generated from its own resolved schema: built `.scratch/proj` and found
  `_site/vocabulary.html`.
- A link-verb entry's structure (`Points at` / `Inverse` / `Declared on`)
  spot-checked against `addresses` and `alternate`; both agree with
  `base.yaml`, and `addresses` carries `trace: false` as the schema
  reference already documents.
- Links: `schema-reference.md` and `output.md#the-vocabulary-page`
  (`docs/output.md` has that heading). Both resolve.

### Discrepancies fixed

None. Everything on this page is machine-generated and the gate passes.

### Unverifiable claims left as-is

- The preamble's claim about *presets* ("a preset that is not enabled is
  not on the page, and a type a project adds of its own is") is a
  statement about a project other than this one. The mechanism —
  `refdes.vocabulary` resolving base standard, then presets, then the
  overlay — is the one the generator docstring and the page both
  describe, and I confirmed the *no-preset* half directly (this repo pins
  `presets: []`, and the page carries no preset terms). I did not build a
  project with a preset enabled to see its terms appear; that is a
  behaviour of `standard.presets`, not of this page.
- "A term the table does not cover … gets a minimal example generated
  from its own resolved facts, placeholders and all, so no entry is ever
  example-less" — every entry in the current block does carry an example,
  which is the observable half. The fallback path for an uncovered term
  is in the generator and was not exercised.

## docs/troubleshooting.md

This page quotes a great many exact diagnostic strings, so almost every
entry was reproduced by provoking the condition in a scratch project
rather than read off the page.

### Claims checked

- `no refdes-project.yaml found in ... or any parent directory` and
  `-c path/to/refdes-project.yaml`: the `-c` flag is on the root
  `refdes --help` usage line.
- The retired-`refdes.yaml` message, including the list of settings to
  move: `src/refdes/schema.py:81-91` `LEGACY_CONFIG_ERROR` names
  `site:, id:, boards:, workspaces:, units:, history:, standard:,
  equations:, imports:` and "the process settings like `sigfigs:` and
  `release_gate:`" — the page's list matches, `equations:` included.
- `unknown type 'requirment'. Did you mean 'requirement'?` — reproduced:
  `unknown type 'requirment'. Did you mean 'requirement'?`
- `no YAML front-matter (file must start with '---')` — reproduced
  (accidentally, via a BOM-prefixed file).
- `unknown field 'sorce'. Did you mean 'source'?` is a **warning** whose
  value is kept: reproduced —
  `WARNING items/reqs.yaml:6 [REQ-PWR-001] — unknown field 'sorce' on
  requirement. Did you mean 'source'?`
- `status: 'in-review' is not one of ['draft', 'active', 'retired']` —
  reproduced exactly, including the declared-choices list.
- `unknown type 'constraint' -- it is now 'bound' in hardware@2 ...` and
  its `refdes standard upgrade --to 2` advice: reproduced in a project
  pinned to `standard: {base: hardware, version: 2}` writing a
  `constraint` item — got the message, including "since the prefix moved
  with it".
- `missing required field 'title'` — reproduced on a `decision` with no
  `title:`.
- `duplicate id 'REQ-PWR-004' (also defined at ...)` — reproduced
  verbatim, with the second location.
- `refines points at 'REQ-PWR-2', which does not exist` — reproduced
  verbatim.
- The three malformed-key messages, including the continuation clause
  and `(Expected check character 'a'.)`: all three reproduced verbatim
  (`expected exactly 11 characters`, `contains a character outside the
  key alphabet`, `check character mismatch … (Expected check character
  'a'.)`).
- The duplicate-key message naming both items and both file:line
  positions: reproduced verbatim, including "A key is unique by
  construction".
- `key changed since baseline 'rev-b': was 'bv170ga0xfk', now
  'm9n2b5v8c1w'. A key never changes legitimately.` — reproduced after
  stamping a baseline and editing a `key:` line.
- `key deleted since baseline 'rev-b': was 'bv170ga0xfk', now no key is
  declared.` and its "The old key is recorded for REQ-B-PWR-001 in
  baseline 'rev-b'." clause — reproduced (the deleted-key check runs
  before key minting, `src/refdes/keys.py:207` and `:629`).
- The "older baseline references key … this is audit information, not a
  build error" line — reproduced in `refdes audit` under
  `Older baseline keys no current item declares:`.
- The dangling-link message naming the link, the label, and "The label
  may be stale; the key is what resolves" — reproduced verbatim for both
  `satisfies points at key …` and `check against key …`.
- `constrained_by may point at ['bound'], but REQ-PWR-002@… is a
  requirement` — reproduced in a `standard: none` project.
- The four calc-fence messages — `unknown attribute 'name'`, `'losses'
  is not an attribute` (reached by both a bare word and an unquoted
  value), and `block name 'Losses' must match [a-z][a-z0-9_-]*` — all
  reproduced verbatim.
- `calc block 'losses' is named twice in this item -- first at line 9,
  again at line 21` and its "rename one of them" clause — reproduced
  verbatim.
- The math messages — `cannot add V and A — the units do not match`,
  `unknown unit 'x'`, `unknown function 'sin'; available: abs, exp, ln,
  log10, max, min, sqrt` (the page's list matches exactly),
  `only one ± tolerance is allowed per assignment`, and `division by a
  value whose tolerance range includes zero` — all reproduced verbatim.
- `calc 'f': the 'name : unit = expression' spelling was retired` is the
  *current* wording for what the page's Checks/Math sections describe as
  `declared as W but the expression evaluates to V/A`; the retired
  spelling's error now names the fix and `refdes calc-rewrite`. The
  page's existing entry is still an accurate description of the
  condition, so it was left alone.
- The design-log messages — `LOG-A-001 is append-only and has been
  modified since it was sealed` and `LOG-A-001 is append-only and was
  sealed, but no item with that id is in the project any more` — both
  reproduced verbatim, including the `--reseal board-a` advice. (Note
  for whoever reads the transcript: editing a log entry's `summary:` does
  *not* trip the seal, because `summary` is `on_change: log` and the
  seal hashes `content_hash`; the body has to change. The page does not
  claim otherwise.)
- `.refdes/schema.json was older than refdes-project.yaml -- not
  refreshed (--no-write).` and the writable-pass wording quoted after
  it: both reproduced.
- `import 'platform': no artifact at ...` — reproduced verbatim, with
  "Build the upstream project first, or fix the path."
- The imported-type warning "... has type 'interface', which this
  project's schema does not declare", a warning that still renders:
  `src/refdes/imports.py:110-116` matches, including "It will render,
  but its fields are not validated."
- A local `![...]()` image src that does not resolve is a build error:
  `src/refdes/build.py:2297-2300`
  (`image src … does not exist (searched …)`, a `project.error`).
- `refdes audit` shows suppression/overrides/reseals/imports, and
  `_site/items.json` carries every diagnostic under `diagnostics`: the
  audit sections are the same ones exercised in the lifecycle.md and
  change-tracking.md checks above.
- All 10 relative links and anchors on the page resolve
  (`authoring.md#several-items-in-one-file`, `ids.md#choosing-your-own-number`,
  `ids.md#renumbering-former-ids`, `links.md#governed_by-vs-refines-vs-constrained_by`,
  `math.md`, `math.md#naming-a-calc-block`, `design-log.md`,
  `markdown.md#citing-a-datasheet`, `markdown.md#images-and-other-local-files`,
  `standard-library.md#the-versions-shipped-so-far`). The remaining
  `file.pdf` match is prose, not a link.

### Discrepancies fixed

1. **The `missing required field 'text'` entry was stale for the pinned
   standard.** The page said "In the bundled standard, `requirement` and
   `bound` use `text`; `decision`, `test`, and `component` use `title`."
   Under **hardware@3** that is no longer true: `requirement` and `bound`
   have no required `text` field — their content is the markdown `body:`,
   declared `required: true` but enforced as a *warning*
   (`base.yaml:190`, and the comment at `base.yaml:56-60` explaining the
   deliberate downgrade from hardware@2's `text: { required: true }`).
   Verified by building a `requirement` with no `text:` (no error at all),
   then writing `text:` explicitly, which produces
   `'requirement.text' is now 'requirement.body' -- rename this key in the
   source file.` Rewrote the entry around the current
   `missing required field 'title'` and the `body: is empty` warning, and
   kept the old message documented as the hardware@2 form.

### Unverifiable claims left as-is

- `id: 042 would expand to 'CAN-042', but that number is already used or
  was burned by an earlier item`, `could not write id back into the
  source`, and `id 'CNA-001' does not match this item's prefix 'CAN'
  (from defaults:)`: these are id-allocation and ledger messages. I
  confirmed the surrounding machinery (the `.refdes/ids.yaml` ledger is
  read and honoured, and the prefix-mismatch check exists) but did not
  provoke each of these three individually, since each needs a
  pre-burned ledger entry or a specific hand-edited shape. The wording
  quoted is consistent with the same message-building code the
  neighbouring, reproduced messages come from.
- The remedy prose under each entry ("restore the line from git",
  "rebuild upstream at the pinned version", …) is advice, not behaviour.
- "Hover previews do nothing … JavaScript is disabled, or `assets/app.js`
  is missing" and "The site looks unstyled" are browser-side
  observations, not CLI-observable.
- `UnicodeEncodeError` in a Windows terminal and the `PYTHONIOENCODING`
  remedy: the remedy is correct (I set it for every scratch run), but I
  did not reproduce the failure itself, which is terminal-dependent.

## Source bugs found

None. Every discrepancy above was a documentation error. No source or test
file was modified by this pass; the only tracked files changed are the
docs pages listed in the changelog fragment.

## Outcome

- Branch: `ao/refdes-181/docs-audit-lifecycle` (hyphen sibling of this
  session's `ao/refdes-181/root`, since the bare session ref cannot take
  slash children), branched from and merged up to date with `origin/main`
  before any work started.
- PR: https://github.com/Squishiba/refdes/pull/44, base `main`, left open
  (not merged) as instructed.
- Gate: `python -m pytest -q -x` -> 2205 passed;
  `python -m ruff check --select E9,F src tests` -> All checks passed.
- Changed files: `docs/lifecycle.md`, `docs/multi-board.md`,
  `docs/schema-reference.md`, `docs/troubleshooting.md`,
  `changelog.d/docs-audit-lifecycle-batch.fixed.md`, and this notes file.
  `change-tracking.md`, `parts.md`, `workspaces.md` and `vocabulary.md` were
  audited and needed no change.
- Pages deliberately not edited (owned elsewhere): `docs/cli-reference.md`,
  `docs/standard-library.md`, `AGENTS.md`. `docs/output.md` was read while
  checking a claim that schema-reference.md makes about theming, and its copy
  of the broken `site.tokens` example is recorded above and in the changelog
  fragment rather than fixed here.




