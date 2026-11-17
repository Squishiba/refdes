# run17-evidence-nits — fix the six reviewer nits on the merged run-17 report

Task: correct six evidence/report nits reviewers found on PR #479 (merged
as c5b6d58a). Deliverable-report rules: no evidence regenerated; claims
corrected or annotated honestly. Docs-only; src/ untouched.

Base: worktree fetched and fast-forwarded to origin/main fed21b80 (clean
ff, rule 1 satisfied).

## The six nits and what was done

1. Head labeling (report line 3) — FIXED. Verified with
   `git log --oneline -3 f8a5308`: f8a53086 (reviewer fix round) sits on
   ac7e7b0f (the report), on 86c0d043; `gh pr view 479` confirms PR head
   branch user-sim-run17, squash-merged as c5b6d58a. `git-context.txt`
   records 86c0d043 as the captured git-log tip, so the run exercised
   86c0d043. Report now labels the run head (86c0d043) and the PR head
   (f8a53086) separately.
2. git-context.txt merge-base line — FIXED. Ran
   `git merge-base f8a53086 origin/main` -> 86c0d0438c68f00895753fbcf3567efb3d753793
   (same result against 19399122, the main tip at merge time). The old
   line labelled the scope baseline 9f15af87 as the merge-base; the file
   now separates "scope baseline" (9f15af87, the fragment range) from
   "merge-base of the PR head with main" (86c0d043), citing the command.
3. edge-subdir-serve.txt --no-write label vs E10 shape — FIXED (label).
   Reasoning from the evidence only: E10_subdir_pane has 3 tick
   checkboxes (and line 5 says "3 tick rows, tip key") = the writable
   shape; the --no-write probes on the same fixture show
   `checkboxes: 0` and no tip key (E3_no_write_pane in the same json,
   edge-nowrite-note.json: preview.js, no tick module). The report's
   subdir bullet never labels this server --no-write. Header re-labelled
   to writable; captured lines 2-5 untouched; an added note records the
   basis and the date.
4. edge-readonly-tree.json project field — REPAIRED (recoverable). The
   value lost the `<worktree>` placeholder the redaction pass uses
   (report footer: "worktree paths to `<worktree>`"), leaving a dangling
   relative path. True value recovered from sibling evidence:
   edge-file-0444.json records the same probe pair (item key
   g52ptehpvx6, same pre-probe sha bae7e8b5dcd7...) on
   ".scratch/proj17ff2 (served on 8762, writable)"; api-navis-actions.txt
   independently ties 8762 to proj17ff2. Field restored to
   "<worktree>/.scratch/proj17ff2 (served on 8762, writable)". Note:
   edge-file-0444.json carries the same relative form and was NOT nit'd;
   left as-is to keep the captured records byte-identical where no
   reviewer finding exists.
5. flow-a-capture-once.txt wording — FIXED (report). The file's explicit
   per-predecessor event check names only LOG-A-002 and LOG-A-003
   (line 25); the report implied a per-predecessor check over
   LOG-A-003..LOG-A-012. Report now states what the file shows: ten
   `Snapshot Captured:` lines (LOG-A-003 through LOG-A-012), the events
   dir counts, and the named check quoting the file's LOG-A-002/003
   line verbatim.
6. upgrading-transcript.txt step-5 edit — RECORDED. The report (section
   6, step 5: "after renaming the mode") shows the edit; a note added
   between the refusal block and the successful run says the edit was
   renaming on_change mode 'log' -> 'timeline' in items/log.yaml, and
   says plainly that the edit itself was not captured as a diff.

## Verification

- claims-check.py re-run: 124 fragments (new `f8a53086` span lands in
  git-context.txt), 0 misses; claims-check.txt regenerated with the
  count updated.
- tests/test_crossplatform_lint.py run; full suite run once (see result
  in the PR thread / final report). No test reads in-prog-logs/
  contents (grep over tests/ shows docstring citations only).
- No new em-dash glyphs inside verbatim quotes; new report prose matches
  the report's existing em/en style.

## Status

Finished. Per-nit outcome: 1 fixed, 2 fixed, 3 fixed (label), 4 repaired
(recoverable), 5 fixed (report wording), 6 recorded. Nothing left
unsettled.
