# Finding 25 — part 1: citations as an includable field set (hardware@3)

## What I did

1. Synced the worktree to main's tip (`git merge --ff-only main`,
   e2a04eb → 8e33c08, clean fast-forward).
2. `src/refdes/standards/hardware/v3/base.yaml`:
   - Added a third `field_sets:` entry, `citations:`, beside
     `provenance`/`stewardship`:
     `citations: { type: citations, on_change: invalidate }`.
   - `component`: deleted the inline
     `datasheets: { type: citations, on_change: invalidate }` line and now
     includes `[provenance, stewardship, citations]`.
   - `decision`: `include:` is now `[provenance, stewardship, citations]`.
     Nothing else about `decision` changed.
3. `src/refdes/standards/hardware/v3/migration.yaml`: added
   `component: { datasheets: citations }` under `fields:`, and rewrote the
   header paragraph that claimed every v3 change was purely additive — it
   now says the additive changes need no rewriting but the
   `datasheets:` → `citations:` move is a rename this file carries.
4. `items/components/power.yaml`: `datasheets:` → `citations:` (field key
   and the one comment naming it).
5. Docs — field-key references only:
   - `docs/markdown.md`: both YAML examples in "Citing a datasheet".
   - `docs/schema-reference.md`: the "a project can call the field …"
     example now names `references`/`sources` and notes the standard
     itself calls it `citations`.
   - `docs/output.md`: both `"citations": { "datasheets": [...] }` JSON
     examples (the map is keyed by field name, so they now read
     `"citations": { "citations": [...] }`).
   - `docs/parts.md`: the nested-`part_number` YAML example.
   - `docs/design/standard-library.md`: prose `component.datasheets` →
     `component.citations` (§ "No new type, no new field type").

## Deliberately NOT touched

- `publish_datasheets` (project setting) in schema.py, model.py,
  refdes-project.yaml, render.py — unrelated, shares only a word.
- `assets/datasheets/` output path in citations.py / render.py — asset
  path, not a schema field.
- Ordinary English "datasheet(s)" in prose.
- `docs/design/standard-library.md` line ~181: that YAML block is a
  verbatim snapshot of `hardware/v1/base.yaml` (labeled as such); renaming
  inside it would falsify the frozen v1 shape. Only the prose reference
  was updated.
- v1/v2 base.yaml, CHANGELOG.md, backlog.md — per task prohibitions.
- No `path:`/CitationSpec changes — deferred half.

## Difficulties

- The shell whitelist refused `cd`, so commands ran with absolute paths /
  `git -C`; pytest was pointed at the worktree's `tests/` by absolute path
  and resolved `refdes` from the worktree (no global install), so the run
  genuinely exercised the edited standard.
- Deciding doc scope: several `datasheets` occurrences are prose, asset
  paths, the v1 snapshot, or `publish_datasheets`; each was checked
  against "is this the schema FIELD KEY" before editing.

## Verification (all five gates)

1. `grep -rn datasheets items/ src/refdes/standards/hardware/v3/base.yaml`
   → no matches.
2. `grep -rn publish_datasheets src/refdes/schema.py refdes-project.yaml`
   → still matches in both.
3. `git diff --stat` on v1/v2 base.yaml → empty.
4. `python -m pytest tests/ -q` → **650 passed, 0 failed**.
5. `git status --short` → only the files named above, plus this log.

## Finished?

Yes — part 1 complete and committed. The `url:` → `path:` half remains
deferred, as specified.
