# docs-cfg-rest — scattered `refdes.yaml` references (backlog finding 28 tail)

Branch `ao/refdes-61/root`, fast-forwarded onto `feat/config-split`
(`git merge --ff-only feat/config-split` → 4c4b8ea; `git merge-base --is-ancestor
4c4b8ea HEAD` confirms). Working tree was clean before edits.

Scope: the ten assigned files only (docs/math.md, docs/ids.md, docs/pages.md,
docs/markdown.md, docs/links.md, docs/index.md, docs/concepts.md,
docs/change-tracking.md, docs/authoring.md, AGENTS.md) + this log. Nothing in
tests/, src/, CHANGELOG.md, docs/design/backlog.md, or the files owned by the
two sibling workers was touched.

## What I checked before editing (ground truth)

- `src/refdes/schema.py` (this branch): `PROJECT_SETTINGS_NAME =
  "refdes-project.yaml"` (line 38, "the project marker ... every project
  setting"), `SCHEMA_NAME = "refdes-schema.yaml"` (line 43, optional overlay,
  "types:, link_types:, field_sets: only"), `SCHEMA_KEYS = {types, link_types,
  field_sets}` (line 53), `_PROJECT_SETTING_KEYS` includes site/id/boards/
  workspaces/units/history/standard/equations/imports (56-66), and
  `LEGACY_CONFIG_ERROR` (79-89) confirms `refdes.yaml` is retired and that
  `types:` left in refdes-project.yaml is an error.
- Ran the tool from this branch (PYTHONPATH to worktree src, venv python):
  - `refdes schema --graph -c <tmp>/refdes-project.yaml` on a minimal
    pages-only project (`site:` + `standard: none`, no overlay) →
    `configuration error: ... declares no item types -- add a standard: block,
    or a types: block in refdes-schema.yaml`. So pages.md's "A schema block is
    still required by the config format, even when nothing uses it" is still
    true; the block just lives in `refdes-schema.yaml` now (or the standard).
  - `refdes schema -h` confirms the command loads the project.
- docs-site/refdes-project.yaml + docs-site/refdes-schema.yaml (the real
  project pages.md's "that is how this documentation is built" refers to)
  confirm the split shape its example now shows.

## Edits (13 mention-renames + 2 context fixes)

- `refdes.yaml` → `refdes-project.yaml` (settings/process keys): math.md ×3
  (units aliases; `units.preferred`; `equations:` — see note below), ids.md
  `id.width`, pages.md project tree, markdown.md `site.assets:`, index.md cell.
- `refdes.yaml` → `refdes-schema.yaml` (type/field/link declarations):
  ids.md ×2 (type's `prefix` in the prefix-order list and in the
  `<TYPE>-<BOARD>-<CATEGORY>-<NNN>` shape), links.md (link names on a type,
  followed by a `types:` example), concepts.md (item types declared), 
  change-tracking.md (invalidation policy: "Per field, in the schema"),
  authoring.md (legal fields, followed by a `types:` example).
- math.md equations note (task requirement): `equations:` is a project
  setting, so it lives in `refdes-project.yaml`; sentence reworded to say so
  (`equations:` is a project setting, so it lives in
  [`refdes-project.yaml`](schema-reference.md)...). Verified `equations` is in
  `_PROJECT_SETTING_KEYS` and `_load_equations` reads it from the settings
  mapping.
- pages.md pages-only example: split the single mixed `site:`+`types:` yaml
  into two labelled blocks (`# refdes-project.yaml` / `# refdes-schema.yaml`),
  mirroring the real docs-site files. The trailing "A schema block is still
  required by the config format" line was left as-is — verified still true
  (see above).
- AGENTS.md: added a "current state" bullet describing the two-file layout
  (precisely, since future agents read it as fact) and renamed the
  `refdes schema` run-location mention to `refdes-project.yaml`.

## Judgement calls

1. **AGENTS.md bullet added** — the task said the AGENTS.md mention "should be
   corrected" and "it is worth being precise there since future agents read it
   as fact". A `Current state` bullet is the precise form; one bullet, no
   restructuring.
2. **AGENTS.md keeps one deliberate `refdes.yaml` hit** — the new bullet says
   "`refdes.yaml` is retired". That is the only remaining
   `grep -n "refdes\.yaml"` hit in my files, and it is deliberate (naming the
   retired file), not a stale reference.
3. **pages.md example split** — the old single-block example implied settings
   and types share one file, which is now wrong ("If a passage implies
   settings and types share one file, that is now wrong"). Splitting the one
   example into two labelled blocks is the minimal truthful fix; no document
   restructuring.
4. **cid/type-prefix mentions → refdes-schema.yaml** — a type's `prefix`,
   field legality, link legality, and the invalidation `on_change` policy are
   all `types:`/`link_types:` declarations, i.e. the schema overlay. The
   bundled standard usually supplies them, but the docs' "declared in X" /
   "from X" phrasing points at where the project would declare them itself.
5. **Did NOT touch the sibling workers' files** (cli-reference.md,
   getting-started.md, multi-board.md, schema-reference.md,
   standard-library.md, troubleshooting.md, README.md, CHANGELOG.md,
   backlog.md) even though they still carry `refdes.yaml` hits — out of scope
   per instructions.
6. Did not run the docs-site build as a sanity check: it writes
   docs-site/.refdes/ids.yaml + citations.yaml (committed, not gitignored) and
   would leave untracked ledger state behind; the edits are prose + one code
   fence split (verified all fence counts even per file).

## Verification

- `grep -n "refdes\.yaml"` over the ten files: only AGENTS.md's deliberate
  "is retired" bullet remains (judgement call 2).
- All remaining `refdes.yaml` hits in docs/ are in files owned by the sibling
  workers.
- All code fences balanced in every edited file.
- No files outside the assigned set modified (git status clean apart from the
  ten + this log).

## Status

**Finished.** Committed locally (not pushed).