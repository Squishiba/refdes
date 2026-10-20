# Qwen manager trial plan — 2026-10-20

Deliverable report (not a task-progress log). Planning only: no manager is
activated by this document, nothing is installed, no script is run. Written
during Sol's cover of the Claude lane, on worker e9643b77, Claude-lane work
(PROGRESS.md row 144). Every claim marked **[verified]** was checked by
reading the named file on 2026-10-20; everything else is a **proposal** for
Jared/Claude to accept, amend, or reject. Activation requires Jared's go —
orchestrator-todo-2026-10-18.md l.93 records "Waiting for his go; write the
runbook after the release week settles" **[verified]**, so §11's schedule
assumption is itself an open owner decision (§13.1).

## 1. What the manager is, and what it is not

Provenance **[verified]** (orchestrator-todo-2026-10-18.md l.91-93): Jared's
2026-10-19 idea was a permission classifier + cheap manager model; Claude's
reply, which this plan follows, is that the classifier stays the rule-based
#269 hook, and a cheap Qwen "manager" runs the mechanical loop from a written
runbook plus a queue file, escalating judgment calls to the baton-holding
orchestrator.

Division of labor (proposed): Claude/Jared write plans and acceptance
criteria. The Qwen manager launches workers from plan files, watches them,
runs the merge gate as an unchanged script, archives merged workspaces, and
escalates everything else.

Hard exclusions — the manager never:
- decides security permissions. It runs no `paseo permit allow`, never runs
  or extends `qwen-approver.sh`-style auto-approvers **[verified: that
  script exists in .scratch and is scope-whitelisted, Oct 17]**, and never
  touches the #269 hook (`tools/paseo-worker-permissions/`) — no edit,
  install, reload, enable, no proposed automatic model approvals. #269
  remains security-sensitive and open: its merge-holds entry says the
  classifier ignores `request.input.patterns` and merge/install need Jared's
  OK plus Sol back **[verified: merge-holds.txt l.3; PROGRESS.md l.82]**.
  Merging #269 would not install it — installing is Jared's act
  **[verified: orchestrator-todo l.19-20]**.
- merges through a `merge-holds.txt` entry, adds/removes holds (each
  orchestrator edits only their own lane's entries **[verified: PROGRESS.md
  l.12]**), bypasses the Sol-lane file check, rebases to force MERGEABLE,
  reruns red CI more than once, force-pushes, or touches git history.
- deploys: plugin reload (TASK-11 is built, NOT deployed **[verified:
  orchestrator-todo l.21-24]**), PyPI/Marketplace uploads (Jared's hands
  **[verified: orchestrator-todo l.60]**), `release.py` cuts, production
  anything.
- writes plans, acceptance criteria, design decisions, or review verdicts.

## 2. Exact scope of mechanical operations (allowlist)

All in-place primitives, verified by reading them 2026-10-20 in the main
checkout `.scratch/`:

| Op | Primitive | Verified source |
| --- | --- | --- |
| Merge gate | run `.scratch/gate-merge.sh PR:reviewer[,...]` unchanged | gate-merge.sh (24 lines, read in full) |
| Watch workers/reviewers | `.scratch/wait-idle-or-perm.sh <ids>` backgrounded, `IGNORE_AGENTS` for unrelated prompts; never bare `&`, never loose `pkill -f` | wait-idle-or-perm.sh; rule text orchestrator-todo l.81-82 |
| Status reads | `paseo ls -g`, `paseo inspect <id>`, `paseo logs <id>`, `paseo permit ls` (read-only), `gh pr view/checks`, `git fetch` + `git merge --ff-only origin/main` | used by the scripts above |
| Launch worker | create a Qwen agent whose prompt is the plan file's verbatim worker-prompt text, in a fresh worktree branched from the plan's `base:` | proposal (uses standard Paseo launch as in the 2026-10-15 Qwen sweeps, PROGRESS.md l.71-77) |
| Post worker PR | open PR with plan id in the body; append PROGRESS.md row marked Claude-lane | proposal, per lane-authorization rule **[verified: PROGRESS.md l.2]** |
| Nudge stalled reviewer | `paseo send` a reviewer that stopped before its verdict line | **[verified: orchestrator-todo l.85]** — proposal to allow, text limited to "post your verdict line", no content steering |
| Archive | archive the PR's author workspaces after a verified merge; worktrees with unpushed commits or no PR go to the escalation queue, never deleted | **[verified rule: orchestrator-todo l.75, l.61-63]**; plugin TASK-11 stays undeployed, archive stays manual **[verified l.24]** |
| Write state | sections 3-6 files under `.scratch/qwen-manager/` (gitignored, consistent with PROGRESS.md being gitignored **[verified: PROGRESS.md l.17]**) | proposal |

Everything not on this list is out of scope; default answer to "can the
manager do X?" is no.

## 3. Plan-file schema (proposal)

Claude/Jared author `.scratch/qwen-manager/plans/<id>.yaml`; the manager
treats it as read-only except a `status:` block and an append-only journal
`<id>.journal.log`:

```yaml
id: DOC-VERIFY-348
title: verify docs/foo.md against refdes schema
lane: claude            # claude|sol; sol-lane plans are never touched
author: claude-f3993852 # plans only execute with author: claude|jared
status: approved        # draft|approved|launched|pr-open|gated|escalated|done
base: main              # exact branch/sha the worker branches from
worker_prompt_file: .scratch/qwen-manager/plans/DOC-VERIFY-348.prompt.txt
acceptance:             # machine-checkable, written by Claude, run verbatim
  - cmd: python -m pytest tests/test_docs_foo.py -q
    expect: exit 0
max_fix_rounds: 1       # round >max => escalate, never a silent 3rd round
reviewers: []           # filled by Claude, gate-merge.sh argument: PR:rev1,rev2
merge_spec: null        # the ONLY accepted merge invocation; null => dry-run
escalate_always:        # keyword tripwires in worker output
  - security | permission | parents.json | #269
  - parser | loader | history | HASH_FORMAT | release.py | deploy
  - needs Jared | Sol lane
```

Rule: the manager executes acceptance commands verbatim; a command it cannot
run as-written is an escalation (`plan-ambiguous`), not an interpretation.

## 4. Escalation queue format (proposal)

Append-only `.scratch/qwen-manager/escalations.md`; one line per entry:

```
2026-10-21T14:05Z | DOC-VERIFY-348 | gate-fail | #348 checks red on head
abc1234 (2nd time) | .scratch/qwen-manager/logs/348-checks.txt | paused item
```

Fields: time | plan id | kind | one line | evidence path | manager action
(almost always `paused item`, i.e. no action). Kinds:
`security-permission`, `gate-fail`, `ci-red`, `reviewer-dispute`,
`worker-nonconverge`, `lane-conflict`, `scope-creep`, `plan-ambiguous`,
`env-blocked`, `manager-stalled`, `proposed-merge` (§11). On escalate:
freeze that plan, notify via the baton file
(`.scratch/msg-to-sol-baton.txt` protocol **[verified: PROGRESS.md l.6-7,
l.11]**), keep running other approved items; at 3 open escalations stop the
whole queue (§9). The manager never resolves its own escalations.

## 5. Durable state and heartbeat (proposal)

- `.scratch/qwen-manager/queue.txt` — plan ids, one per line, file order =
  priority. Only Claude/Jared reorder; the manager only skips
  escalated/paused ids.
- `.scratch/qwen-manager/state.json` — one line, atomically rewritten
  (tmp+rename): `{"ts":...,"plan":...,"phase":"launch|watch|acceptance|
  pr-open|gate|merge|archive|idle","agent":"...","pr":...}`. `merge` phase
  set *before* invoking the gate, cleared after journaling the result.
- `manager.log` — one line per loop tick (`ts plan phase`). Liveness = log
  mtime.
- Heartbeat: a separate cheap scheduled check (paseo heartbeat/schedule —
  owner picks, §13.2) that alerts on `state.json.phase == merge` older than
  10 min, `manager.log` mtime > 15 min, queue item `launched` with no agent
  and no PR > 30 min, or 3+ open escalations. The heartbeat only alerts via
  the baton file; it never acts — it is not a second manager.

## 6. Idempotent restart (proposal)

On (re)start, before touching the queue:
1. `phase == merge` stale > 10 min: check the PR's real state via
   `gh pr view` (merged? head sha?) and journal the reconciliation. Never
   re-issue a merge blindly.
2. For each plan `launched`/`pr-open`: `paseo ls -g` reconciliation —
   running agent: adopt (re-arm watcher); agent idle + PR exists: set
   `pr-open`; no agent, no PR: escalate `env-blocked` and freeze the item.
   Never relaunch a worker on an existing branch (double-writer risk).
3. Merge idempotency is structural **[verified]**: gate-merge.sh reads
   `headRefOid` at gate time and merges with
   `gh pr merge --squash --match-head-commit $head` (l.8, l.22), so a merge
   is refused if the head moved after the checks — and re-running the gate
   on an already-merged PR can only fail the checks, not double-merge.
4. All state files: journal append-only, state.json atomic. No manager
   side-effect outside `.scratch/qwen-manager/`, the plan's worktree, its
   PR, and PROGRESS.md rows it created.

## 7. The three-tier merge gate (verified contract, run unchanged)

`gate-merge.sh` (read 2026-10-20) enforces, per PR:

1. **Holds/lane tier** — PR number in `.scratch/merge-holds.txt` → "ON
   HOLD", skip (l.7); non-`fix/*` PRs touching a file marked Sol in
   `lane-files.txt` → SKIPPED, check with Sol (l.10). Current holds:
   #344 (Sol) and #269 (security-sensitive; needs Jared + Sol)
   **[verified: merge-holds.txt]**.
2. **Review tier** — every listed reviewer agent `idle`, its `paseo logs`
   tail (60 non-`[` lines) contains APPROVE **and mentions the current
   7-char head sha** — i.e. approval of current head (l.12-18).
3. **CI/mergeability tier** — `gh pr checks` exit 0 (l.19) and
   `mergeable == MERGEABLE` with 6×10 s retries on GitHub's `UNKNOWN`
   (l.20-21).

Only then squash-merge at the pinned head (l.22), then ff local main
(l.24). The manager adds nothing to this: no gate edits, no merges past
holds, no "approvals close enough" — a reviewer verdict on a stale head is
a gate-fail escalation. A CI-red rerun is allowed once for a
pre-existing/infra-flake signature (precedent: PROGRESS.md l.104, Windows
lock-race reran green); second red = `ci-red` escalation.

## 8. Qwen slot accounting

Binding rules **[verified]**: 8 Qwen slots (server 8×200k,
orchestrator-todo l.86-87 memory ref); workers ≤ 6 so reviews keep ≥ 2
slots; refill workers only while total Qwen < 6 (PROGRESS.md l.8, Jared
2026-10-16; the temporary 3-at-a-time cap was lifted 2026-10-19
**[verified: orchestrator-todo l.77-78]**). codex/gpt-6-luna sits in the
rotation for some reviews (l.8) — proposal: count it in a separate pool
outside the 8.

Manager accounting (proposal): before every launch, `paseo ls -g` fresh
count of running Qwen agents; launch only if workers < 6 and projected
reviewer capacity ≥ 2; record the slot in state.json at launch, release on
journal of worker terminal state; reconcile counts on restart.
Instant-breach rule: any observed moment with > 6 workers → stop launches,
escalate `env-blocked`.

## 9. Stop conditions (manager halts queue, writes escalation, idles)

- Any security-class event: a permission prompt on the manager's own
  account; anything naming #269, parents.json, plugins, install, deploy.
- Two same-kind gate-fails, or any gate-fail on a non-docs plan.
- CI red twice on one head; head sha moves mid-gate; reviewer verdict
  contradicting green checks on the same head.
- Reviewer/worker disagreement about acceptance verdicts
  (`reviewer-dispute`).
- Queue/state corruption: unparseable plan, queue id with no plan file,
  state.json unparseable.
- 3 open escalations, heartbeat gap > 30 min, > 6 Qwen running, worktree
  count growth anomaly (the `fix-worker-permission-policy-20261015-*`
  proliferation pattern the archive guard already flags — orchestrator-todo
  l.61-63).
- Release week: queue freezes from feature freeze through Jared's upload
  **[verified: week plan orchestrator-todo l.70-72]**; the manager has no
  release role.

## 10. Rollback

- Merged change: `git revert -s <squash sha>` on a normal branch, normal
  PR, full gate — the manager never rewrites history; if it needs to
  revert, it *escalates the revert* to Sol, who executes (proposal —
  reverts are judgment).
- Bad worker output: close PR, kill agent, archive worktree only if clean;
  unpushed commits → escalation, never deletion (**[verified rule:
  orchestrator-todo l.61-63]**).
- Gate bug discovered mid-trial: immediate merge stop (stop condition),
  escalate; the manager does not repair gate-merge.sh — Claude's script,
  Claude's fix.
- Everything the manager wrote in `.scratch/qwen-manager/` is disposable;
  forensic value only. No rollback needed for gitignored state.

## 11. One-day trial

Phase 0 — preflight (human, ~15 min): Jared go on this plan; Sol prepares
≥ 3 approved plans in the queue, docs-only (the proven cheap-Qwen genre:
docs-verify PRs #274-#320 all merged through this exact gate **[verified:
PROGRESS.md l.91-115]**), each with `merge_spec: null` (dry-run).

Phase 1 — dry-run morning/afternoon: full loop, zero merges. Launch,
watch, acceptance verbatim, PR open, reviewers assigned by Claude, gate run
in **dry-run mode**: all §7 checks executed and logged, the merge line
never reached. Proposal: `gate-merge-dry.sh` = gate-merge.sh with l.22's
`gh pr merge` replaced by echo, authored and reviewed by **Claude**, run by
the manager as an unedited script (same checks, zero divergence from the
real gate; §13.4). Every dry-run PASS is journaled and queued as a
`proposed-merge` escalation for Sol to execute by hand.

Phase 2 — gated live (only after a clean Phase 1 + explicit Sol go, same
day): the manager runs real `gate-merge.sh` on exactly 1 pre-named docs-only
PR that Sol pre-authorizes in writing (plan id + reviewer ids in
`merge_spec`). Holds file untouched; success = merged at pinned head; any
stop condition = phase abort.

Phase 3 — archive: manager archives the merged PR's author workspaces
(clean only), runs the ff-main step, writes the trial report to
`in-prog-logs/` for next-morning review.

Success metrics (measured, reported): zero forbidden ops (manager.log
audited against §2); zero merges past holds; zero security decisions;
would-merge timestamp vs Sol's human merge (latency); gate precision —
Sol re-checks every proposed-merge (target: 100% agreement, one disagreement
= trial failed); escalation precision — Sol judges each escalation
needed/not; slot discipline — sampled `paseo ls -g` never shows > 6 workers.
Abort: kill manager, freeze queue, preserve state; report failures loudly.

## 12. Verified vs proposed (summary)

Verified by reading on 2026-10-20: gate-merge.sh (all 24 lines, §7
contract incl. `--match-head-commit`), merge-holds.txt (entries 344, 269),
PROGRESS.md (baton l.1/l.6-7/l.11, slot rules l.8/l.13, hold rule l.12,
lane authorization l.2, this task's row l.144),
orchestrator-todo-2026-10-18.md (l.74-93 incl. the manager idea l.91-93,
#269 status l.14-20/l.86-90, TASK-11 l.21-24, watcher rules l.79-85,
archive rule l.75, leftovers l.61-63), .scratch watcher/approver scripts
(watch-one.sh, watch-reviews.sh, wait-idle-or-perm.sh,
wait-idle-or-nonroutine-perm.sh, qwen-approver.sh — read; not run, not
modified). Proposed: §3 schema, §4 queue, §5 state/heartbeat, §6 restart,
§8 accounting details, §9-§11, gate-merge-dry.sh, all launch mechanics.

## 13. Unresolved owner decisions

1. Go/no-go and timing: orchestrator-todo l.93 says write the runbook
   *after the release week settles*; this plan is the early draft. Running
   the trial before the Friday upload needs Jared's explicit override.
2. Heartbeat carrier (paseo heartbeat vs Sol cron) and the manager's model
   + budget (which Qwen, how many loop ticks/day).
3. Slot-rule conflict: PROGRESS.md l.8 (≤ 6 workers / ≥ 2 review) vs l.13
   (Claude 5 / Sol 3) — which one binds the manager (plan assumes l.8).
4. `gate-merge-dry.sh` authored and approved by Claude before Phase 1.
5. Manager edits to shared PROGRESS.md: plan allows rows it created,
   marked Claude-lane (l.144 style); Sol to confirm the shared-file rule.
6. #269 is explicitly NOT part of the trial: no dependency, no install,
   no reload, no auto-approvals; it stays on hold pending Jared + Sol.
