# editor-source-picker.md — Slice C status staleness

## Task

Fix the stale claim in `docs/design/editor-source-picker.md` that Slice C (the
panel) is still design-only. The doc's top status line and its
`**Slice C — the panel.**` entry in §11 both still described it as unshipped.

## Verification, before editing

- `git log --oneline --all | grep -i "slice.c\|source-picker"` →
  `07b20f5 feat(serve): source-value picker panel (Slice C) (#62)`.
- `git show 07b20f5 --stat` → 9 files, 473 insertions, 5 deletions, including
  `src/refdes/serve/static/sourcepicker.js` (249 lines) plus the
  `editor.js` / `item.js` / `drafts.js` / `style.css` wiring, and
  `tests/test_serve_static.py` + `tests/test_serve_sources_accept.py`. That is
  exactly the artifact list the doc's Slice C entry names.
- `gh pr view 62` → `MERGED`, branch `feat/source-picker-slice-c`, title
  "feat(serve): source-value picker panel (Slice C)", `mergeCommit.oid`
  `07b20f57a9ad583a3dd73752f8ef3977a27f5fd0`, `mergedAt`
  `2026-09-28T00:24:32Z`.
- `git branch -a --contains 07b20f5` includes `main`, so it is on the base
  branch this branch was cut from.

Note it is a squash merge, so `07b20f5` is a single-parent commit on `main`
rather than a merge commit; `git show <merge-commit> --stat` is still the right
command, it just shows one parent's diff.

## The date: 2026-09-27, not 2026-09-28

`gh` reports `mergedAt` as `2026-09-28T00:24:32Z`, but the commit's own dates
on `main` are author *and* committer `2026-09-27T20:24:31-04:00`. The UTC
timestamp merely crosses midnight relative to the author's timezone.

The repo's existing convention is to date a LANDED marker by the commit's local
date, not the UTC merge instant, and there is a direct precedent: Slice P-C
(`docs/design/editor-pdf-picker.md:592`, `gh pr view 71`) has
`mergedAt 2026-09-28T02:58:39Z` and commit date `2026-09-27T22:58:38-04:00`, and
is recorded as "LANDED 2026-09-27". Same author, same situation. So the marker
reads **LANDED 2026-09-27**, consistent with the adjacent Slice B marker.

(Out of scope, noticed while checking: Slice A at line 539 reads
"LANDED 2026-09-25" but PR #49 `mergedAt 2026-09-26T04:17:23Z` with commit date
`2026-09-26T00:17:23-04:00` — that one is off by a day under either reading.
Left alone; not this task.)

## §10's "UI rows" — checked, and they did ship

The task asked me to verify rather than assume this. §10 has four lists;
checked each against the tree on `main`:

- **Reader** and **Endpoints** rows are Slice A, already claimed as landed.
- **UI, static** — all four shipped with PR #62. `git show 07b20f5 --
  tests/test_serve_static.py` adds exactly
  `test_the_picker_is_wired_into_the_editor`,
  `test_the_browser_parses_no_csv`,
  `test_the_picker_inserts_through_the_existing_draft_mechanism`, and
  `test_the_unit_field_starts_empty_and_accept_is_disabled_until_it_is_filled`,
  which is the §10 list verbatim, in the same order.
- **End to end** — §10 lists two. Only
  `test_a_picked_value_saves_and_resolves_without_a_cli_step` shipped.
  `grep -rn "survives_a_rebuild" tests/` finds nothing, so
  `test_a_picked_value_survives_a_rebuild_and_drifts_when_the_csv_changes` was
  never written.

So "the UI rows of §10" is now false — they are the tests PR #62 added — and
the one genuinely outstanding row is the rebuild-and-drift end-to-end case. Both
edited spots now say that instead.

## Slice C description vs. what shipped

Every item the entry already named is real, confirmed in the code, not just the
file list:

- `src/refdes/serve/static/sourcepicker.js` exists, and `editor.js` imports
  `createSourcePicker` from it (the `import { createSourcePicker } from
  './sourcepicker.js';` line in the PR diff).
- file → key → confirm flow: present in the module's step structure.
- unit field with no default: `unit.value = ''; // never pre-select a unit,
  including dimensionless 1`, and the Accept button is gated on
  `!unit.value.trim()`.
- insertion through `setDraftBody`: `editor.js`'s `insertSourceLine` sets
  `area.value` then calls `setDraftBody(handle, area.value)`, and refuses with
  "Add a ```calc``` fence to this body before picking a source value." when
  there is no calc fence — the §7 placement rule.

Two things shipped that the entry did not list, so I added them:

- the proposed, editable variable name field of §7 (`name.value =
  initial.name`, re-proposed on input and sent as the `name=` query param);
- read-only browsing for sealed and imported bodies, which §6 and §9 Q6 had
  specified. `item.js` builds the panel with
  `edit.body && edit.body.editable ? acceptSource : null`, and `sourcepicker.js`
  renders "This body is read only." when the accept callback is absent. This
  also matches the PR's own `in-prog-logs/source-picker-slice-c.md` note about
  "read-only browsing for sealed/imported bodies".

## Scope

Only the two staleness spots the task named were edited: the top status
paragraph and the §11 Slice C entry. Two adjacent sentences were left alone
deliberately, because they are not the claimed-stale fact:

- "This document still changes no authoring behaviour" is arguably now loose,
  since the editor's behaviour has changed — but it reads as a statement about
  *this document* settling the requirement recorded in
  `docs/design/calc-sources.md` §1, which is still true, and the task said to
  keep the fix strictly to this one issue.
- The `Status: **proposed**` word was left as-is; the task asked to mark the
  slice landed, not to restatus the document.

## Status

Finished. Verified against `07b20f57a9ad583a3dd73752f8ef3977a27f5fd0` (PR #62,
merged into `main`). No test run: this is a docs-only change.
