# Task: revise the local-model-suitability rule and six verdicts in docs/design/backlog.md

Started from `main` after `git merge --ff-only main` (HEAD `b88f2f1`). Edited
only `docs/design/backlog.md`, plus this log.

## What was done

**Part A — the rule section.** Kept the existing framing (hand out work where
being wrong is loud; this project's characteristic bug is code that reports
success while doing nothing) and added:

1. Loudness is mostly a property of the task specification, not the task —
   with the three concrete examples from this session's delegations (unknown
   tag must error → fixture where OR diverges from AND; prove the link
   RESOLVES → assert backlinks; substring check would pass with the href
   untouched → assert the whole attribute). Conclusion stated: a quiet failure
   mode disqualifies a finding only if the spec cannot make it loud.
2. What stays off a smaller model is design-unsettled work (taste, unresolved
   tradeoffs, no written spec), not merely consequential work.

Plus the stance paragraph: prefer finding empirically over pre-judging; a wrong
delegation costs a revert, a wrong pre-judgment costs work never attempted and
leaves no trace; the verdicts were revised on that basis and may be revised
again. Records the XSS a local model reviewing another model's work found (an
item title containing `</script>` breaking out of the preview-data script
element) that the orchestrator had missed.

**Part B — six verdicts** (descriptions and Status lines untouched):

- **14** → suitable IF the task specifies negative tests (assert a group is not
  coverable; assert it cannot be a `satisfies:` target), named in the task.
- **15** → stays not suitable (taste-dependent UI, no mechanical acceptance
  test); dependency claim corrected — all four blockers have shipped (see
  verification below).
- **19** → split: the `EXPLICIT_REF_RE` fragment-syntax half suitable (same
  shape as finding 18's regex fix, `3a2fced`, done correctly by a local model);
  citation-identity namespace and `revise.py` staleness wiring stay not
  suitable.
- **20** → suitable IF the gate is specified: assert the injected example
  equals `refdes new <type>` output for the pinned standard version.
- **21** → not suitable to design, suitable to implement once specced; the
  substitution-safety judgement is already made, and per the header rule the
  entry earns a `docs/design/` document first.
- **24** → suitable once finding 14 lands; the unregistered-group hard-error
  edge is the same shape as finding 13's unknown-tag case, which went well
  because the task named it. Dependency on 14 kept.

**Part C — entry 25.** Added "(Not in the finding — recorded from
conversation, not from the document.)" to the three unmarked decisions (the
accepted breaking rename, v3-only scope, Part 2 deferred), matching the marker
already on the first decision and the one on finding 14's membership-verb
decision.

## Verification of finding 15's dependency claims (done against this tree)

- **Finding 8** (id completion narrowed by file/board) — **shipped**, commit
  `1044c96` ("vscode: filter id completion on source file and board too
  (finding 8, issue #6)"); confirmed in the code: `editors/vscode/extension.js`
  builds `c.filterText` from `item.id`, `item.title`, `item.source.file` and
  `item.board`, with a "Finding 8" comment at the site.
- **Finding 9** (`refdes ls`) — **shipped**, commit `491283e`; `cmd_ls` at
  `src/refdes/cli.py:347` with its `ls` subparser at `src/refdes/cli.py:976`.
- **Finding 10** (`next_ids` exposure) — **shipped**, commit `c743328`;
  `payload["next_ids"]` at `src/refdes/render.py:456`.
- **Finding 13** (this backlog's `{{index}} tag=` filter) — **shipped**, commit
  `1cf3e88`; `src/refdes/blocks.py` has `optional=("board", "tag")` on the
  `index` `BlockSpec` (line 413) and raises `_BlockError` for an unknown tag
  (line 158).

So the backlog's claim that 15 depends on four unshipped blockers was stale in
every case; the corrected text says all four have shipped.

## Difficulties

- The first multi-block `edit` call was rejected because one `oldText` block
  (finding 24's verdict) did not match byte-for-byte; the call is atomic, so
  nothing was applied. Re-applied in smaller batches with shorter anchors, then
  cleaned up the leftover tail of finding 24's paragraph and the leftover
  remainder of finding 19's old verdict so no duplicated reasoning survived.
- `cd` is blocked by the shell whitelist in this environment; used absolute
  paths and `git -C` instead.

## Status

Finished. `git status --short` lists only `docs/design/backlog.md` and this
log.
