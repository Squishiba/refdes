# backlog.md — bring current: five shipped, four added

## Step 0

`git merge --ff-only main` → `e2a04eb..a077cb2`, clean fast-forward. Header
line updated to `a077cb2` (2026-09-13, `main`), found with
`git log -1 --format=%h main`.

## Verification of every "done" claim written (all against the tree, not the brief)

- **12** — `docs/authoring.md` "Bodies in list files" (lines ~35-40) and
  `parse.py`'s `RESERVED` comment (lines ~28-33) both state the prose-vs-list
  tradeoff; neither still says "one file per entry". Commit `8e33c08`.
- **13** — `blocks.py:413` `optional=("board", "tag")`; `_render_index`
  builds `known_tags` from local items, raises with `_suggest`, and the select
  comprehension ANDs `board` and `tag`. Commit `1cf3e88`.
- **16** — `standards/hardware/v3/base.yaml:163`: `recorded_by: [log]` in
  `decision.links`. Commit `3c52c4e`.
- **18** — `calc.py:187-188`: `_SEGMENT` continuation class
  `[A-Za-z0-9_Ωµμ°]*`, `_UNIT_RUN = (?:{_SEGMENT}(?:[/·]{_SEGMENT})*|%)`.
  Commit `3a2fced`.
- **23 part 1** — `templates/item.html.j2:115-116`: both the upstream and the
  `local copy` href append `#page={{ c.spec.page }}` under `{% if %}`.
  Commit `a077cb2`. Part 2 confirmed absent: no `section:`/`pypdf` in
  `citations.py`, `pyproject.toml` optional extras are `dev` only.
- **25 part 1** (cited in the new entry) — `v3/base.yaml:85-86` `field_sets.
  citations`, `include:` on both `decision` (156) and `component` (191),
  `migration.yaml` `component: {datasheets: citations}`. Commit `f8e7ee0`.
  Part 2 confirmed absent: `CitationSpec` (model.py:247-263) still `url`, no
  `path`.
- **26/27/28 outstanding** — no `openpyxl`/`xlsx` support; `calc.py`
  `FUNCTIONS` is the built-in registry with no `equations:` setting;
  `schema.py:30/36` still `CONFIG_NAME = "refdes.yaml"` /
  `PROJECT_SETTINGS_NAME = "refdes-project.yaml"`.

## What changed in docs/design/backlog.md (the only file edited)

- Header commit reference → `a077cb2`.
- `## Source` rewritten to record both attachments and which findings came
  from which (12-24 = issue body, fetched 2026-08-29; 25-28 = second
  attachment posted as a comment 2026-09-01), including that the newer
  document renumbers 1-28 so only 25-28 are new here.
- Status lines rewritten for 12, 13, 16, 18 (done, naming what landed and the
  commit) and 23 (part 1 done / part 2 outstanding and undecided).
- New section "GitHub issue #7 (second attachment), findings 25-28" with one
  entry each for 25, 26, 27, 28 in the established format.
- Finding 25 carries four conversation-only decisions flagged as such (one
  field name `citations` over the source's `references`/`datasheets`+
  `documents`; the accepted breaking rename; v3-only scope; part 2 deferred,
  with 26 parked behind it).
- Part D: 26 and 28 marked "(not decided — my read): not suitable", 27
  "(not decided — my read): suitable", 25 part 2 likewise — none of the three
  was put through the suitability rule in conversation, so none is presented
  as settled.

## Deliberately not touched

- Findings 1-11, 14, 15, 17, 19-22, 24 entries and the Surrogate-keys section.
- Any code, doc, or CHANGELOG file. (CHANGELOG has no entries for these five
  commits, so the backlog entries cite commit hashes and file locations
  instead.)

## Verification

- `python -m pytest tests/ -q` → see below.
- `git status --short` → `docs/design/backlog.md` and this log only.
