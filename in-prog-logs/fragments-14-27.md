# fragments-14-27

Task: write two changelog fragments for changes that landed just before the
fragment system existed. Sync first with `git merge --ff-only main` (done;
fast-forward e2a04eb..0a50e3d). One transient "short read while indexing"
error during the first `git status` cleared on re-run; tree confirmed clean.
Read `changelog.d/README.md` (naming: `<slug>.<category>.md`, one bullet per
change, `- ` lead, no headings) and the existing fragment
`changelog.d/changelog-fragments.added.md` as the worked example of tone and
length. Skimmed both commits' diffs and the `[Unreleased]` sections of
CHANGELOG.md for voice.

## Fragments written

- `changelog.d/hardware-v3-group-type.added.md` — commit 1330dee: new `group`
  type (prefix GRP) in the bundled hardware@3 standard; membership declared by
  the member via `part_of:` (inverse `contains` only ever a computed backlink),
  `coverable: false`, deliberately absent from every `satisfies:` target list.
  Mentioned the standard itself is unreleased so pinned v1/v2 projects know
  they see none of it.
- `changelog.d/calc-project-equations.added.md` — commit c96d96b: `equations:`
  block in refdes.yaml, callable from any calc block; units flow from
  arguments, tolerances propagate; `note:` is provenance; shadowing a built-in
  is an error and cycles are detected (both with example messages);
  project-wide namespace like `units:`.

Both kept in the changelog voice (bold lead-in, what the reader can now do),
with the "backlog finding" provenance and testing details kept out per the
task instructions. No headings inside the fragment files; each starts with
`- `.

## Judgement calls (kept out of the changelog)

- Neither entry mentions the backlog finding numbers (14 / 27), the agent, or
  how it was tested — per task instructions, the fragments are for a reader of
  the project.
- The group type's "deliberately absent from `satisfies:`" is phrased as the
  feature it is (nothing may claim a group), matching the commit's framing
  rather than as a gap.
- `contains` described only as the computed inverse backlink (it is never
  authored), so readers don't try to write `contains:`.

## Verification

- `git status --short` -> only the two new fragments under `changelog.d/` and
  `in-prog-logs/fragments-14-27.md`.
- `python -m pytest tests/ -q` -> 685 passed (no code changed).

## Status

Finished. Commit made locally (not pushed).