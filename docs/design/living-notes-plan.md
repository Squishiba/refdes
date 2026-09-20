Status: Proposed — implementation plan for living notes; the decisions it
implements are in `docs/design/living-notes.md` and are not reopened here. All
eight open questions (§Open questions for Jared) were ratified by Jared on
2026-09-19 as the conservative defaults this plan already assumed, so **H1 is
unblocked**.

# Living notes: implementation plan

This is the plan `living-notes.md` was waiting for, and the thing threads
phase 4a is held behind (`docs/design/threads.md` §7 on branch
`ao/refdes-64/root`, and the measured analysis in that branch's
`in-prog-logs/4a-sealing-analysis.md`). It is a plan, not a spec: every design
question in it was answered on 2026-09-16 and stays answered. What it does is
order the work into phases small enough to land and verify alone, name the
files each one touches at current `main` line numbers, say what mechanically
proves each phase, and state precisely when threads 4a can land and what has to
change in it at that moment.

Granularity matches threads' own history — phase 1, 2a, 2b, 3a, 3b — so each
phase below is one reviewable change with its own tests, not a milestone.

**Line numbers are against `main` as of this writing** (`build.py:1977` is
`seal.verify`, `build.py:1054` is `HASH_FORMAT = 3`). `living-notes.md` cites
slightly older numbers for the same functions; where they differ, this document
is the newer read of the file, and the function names are the real anchors.

## The one-paragraph shape of the work

Build the store first with no call sites (H1), then the single capture point
that writes into it (H2), then the diagnostic that reads from it (H3), then the
two commands an author needs to use it directly (H4). Only then touch sealing
(H5) — because until H1–H4 exist, removing the build-time lock leaves nothing
behind, which is exactly the "docs and behaviour diverge" failure the analysis
rejected as option d2. Everything after H5 is the task-list and query-surface
half, which the capture model does not depend on and which therefore must not
delay 4a: `tasks:` (H6), the two read commands and the index projection (H7),
the optional gate rules (H8), and the optional baseline/site layer (H9).

**Threads 4a lands after H5.** The minimum that unblocks it is H1 + H2 + H5;
H3 and H4 are included in the handoff because H5 without them is the rejected
option, and both are small. Details in §Threads handoff.

## Phase H1 — the history store, with no call sites

**Adds.** `src/refdes/history.py`: the file format, the canonical semantic
payload, the digest, load, save, and an idempotent event append. Nothing
imports it except its own tests.

**Files.** New `src/refdes/history.py`; new `tests/test_history.py`.
`src/refdes/parse.py:33` (engine-reserved keys) is checked, not changed —
`tasks:` and history's own metadata must not collide with a field named on an
item.

**Format.** As decided in `living-notes.md` §3:

```text
.refdes/history/
  objects/<semantic-sha256>.yaml   # canonical snapshot payload
  events/<event-id>.yaml           # {kind, occurred_at, item_key, object, reason, successor_key?}
```

`objects/*.yaml` carries `history_format: 1`, the item's key, display id, type,
own declared fields, raw link spellings (not resolved ids — `model.py:378-396`
keeps raw and resolved deliberately separate and writes/hashing need raw),
body, and the source file/line it was captured from. It excludes rendered HTML,
diagnostics, backlinks, coverage — everything rebuildable.

**One stated deviation from the doc's sketch.** The doc writes
`events/<uuid>.yaml`. Event ids must be **derived, not random**: `uuid5` over
`(kind, item_key, successor_key)`. Random ids make the idempotence rule of
decision 2/§2 depend on remembering to look the file up, and make the
old-branch-replay case (§2, case four) produce a second file with a second id
for the same fact. A derived id makes a replay write the identical path with
the identical bytes, which is a no-op at the filesystem level and needs no
index. `occurred_at` is excluded from the id and, per §2, is display metadata
only — never ordered, compared, or gated on.

**Digest.** `semantic_digest(item)` is a new, separately versioned digest over
the canonical payload. It is **not** `item.content_hash`: that one
intentionally excludes `on_change: log` and `ignore` fields
(`model.py:477-489`, `docs/design/keys.md` §on_change), and a task tick must
be visible in history while it must not churn a baseline. It is also not
affected by `HASH_FORMAT` (`build.py:1054`): a `HASH_FORMAT` bump must never
make an item look edited, and history objects are migrated only by an explicit
history migration that proves semantic equivalence.

**Verified against.**
- Round-trip: write an object, load it, compare to the payload dict.
- Canonical stability: the same item expressed as block YAML and as flow YAML,
  and the same item with fields in a different declaration order, produce the
  same digest. Equivalent defaults from a `defaults:` block produce the same
  digest as fields written on the item.
- Sabotage: change a field marked `on_change: log` — digest changes,
  `content_hash` does not. This is the test that keeps the two digests from
  collapsing into each other later.
- Idempotence: appending the same `(followed, predecessor, successor)` event
  twice writes one file, byte-identical.
- `history_format` is written and read; an unknown higher version refuses
  rather than guessing.

**Deliberately does not do.** No call site, no CLI, no build change, no seal
change, no `tasks:`. A project that never uses history gains an unused,
uncreated directory: `.refdes/history/` is not written by any command in this
phase, so every existing test — including the whole-tree byte-identical
`--no-write` test at `tests/test_no_write.py:189` — passes untouched.

## Phase H2 — capture at the `follows:` edge, announced

**Adds.** The capture moment. When a writable load freezes a `follows:` edge, it
captures a `followed` event holding the **predecessor's** snapshot, and prints
the visible line: `captured LOG-A-011: LOG-A-012 now follows it`.

**Files.** `src/refdes/cli.py:125` — the `freeze_follows(project,
write=not args.no_write)` call inside `_load()` (`cli.py:69-136`) — plus
`src/refdes/links.py:592-693` (`plan_follows_freeze` / `freeze_follows`,
`FollowsFreezePlan` at `links.py:509`). Capture is added **alongside** the
freeze, in the same write pass, sharing its `write` flag; `freeze_follows()`
keeps exactly what it does today. `src/refdes/history.py` gains the one
function that turns a resolved (predecessor, successor) pair into an event.
Tests: new `tests/test_history_capture.py`, and an extension of
`tests/test_no_write.py` (its tree-hash helper at `:65` already hashes every
file under the project, so `.refdes/history/` is covered the moment it exists).

**The five cases, as code.**
1. *Typo corrected on the next save.* When a later writable load resolves a
   successor's edge to a **different** predecessor, write a `followed-corrected`
   event naming both and treat the original as superseded. Never delete or
   rewrite the first event.
2. *VS Code's writable save refresh* (`editors/vscode/extension.js` runs
   `index --compact` on save). Accepted deliberately — the save is the author
   moment. The announcement is the price, paid visibly. Machine output stays
   clean: `index --compact` prints JSON only and never the capture line
   (open question Q4).
3. *CI.* Capture sits behind the same `write=not args.no_write` gate as every
   other incidental write in `_load()`. An explicit capture under `--no-write`
   refuses through `_refuse_no_write()` (`cli.py:137`), it does not pretend.
4. *Old-branch checkout replaying an edge.* Derived event ids (H1) make the
   replay write the identical bytes; where the branch's store lacked the event,
   the replay is the repair.
5. *Idempotence.* One event per (predecessor key, successor key), enforced by
   the id, so the every-save load cannot accumulate duplicates.

**Transaction.** The successor's frozen edge and the event are one unit: if the
event write fails, the edge rewrite is rolled back by the existing load-time
write guard (`tests/test_load_time_writes.py:130` and `:153` already prove that
guard rolls a write back when the result stops parsing; H2 adds the case where
the guard passes and the *event* write is what fails).

**Verified against.**
- The analysis's own §3 transcript, inverted: a project with `follows:` on an
  append-only type, a bare edge authored after the entry was sealed, `refdes
  index` → the edge **freezes**, the line prints, `.refdes/history/events/`
  holds one file. (Under H5 this is the normal case; under H2 alone it is
  still refused for a *sealed* entry, and the test asserts the refusal is
  unchanged — H2 must not silently change `links.py:623-634`.)
- Two consecutive writable loads → one event, second load prints nothing.
- Corrected edge → second event of kind `followed-corrected`, first event
  still on disk.
- `--no-write` across every capturing command → `tests/test_no_write.py:189`
  passes with the history directory included in the tree hash.
- A project with no `follows:` anywhere → no `.refdes/history/` directory at
  all, and a byte-identical site.

**Deliberately does not do.** No `refdes history` command, no redaction, no
edited-after-captured marker, no seal change, no baseline events, nothing in
`render_site()` (`render.py:756`) — the hard rule that no render creates an
event is enforced here by the absence of any history call under `render.py`.

## Phase H3 — "edited after captured", a diagnostic and never a failure

**Adds.** Comparison of live semantic content against the newest snapshot for
an item, surfaced as a diagnostic and an index field.

**Files.** `src/refdes/history.py` gains `edited_after_captured(project)`
returning `(item, event, captured_digest)`; `src/refdes/build.py` gains one
call after `compute_hashes` (`build.py:1219`) and before the seal step
(`build.py:1977`), reporting through `project.warn` — never `project.error`.
`src/refdes/render.py:511` (`items_json`) gains a per-item `captured` /
`edited_after_captured` pair so VS Code and the future editor read it from the
index rather than recomputing it. Tests: `tests/test_history_edit.py`.

**Verified against.**
- Sabotage: capture an entry, edit its body, `refdes check` → warning naming
  the entry, the capture event, and the successor; **exit code unchanged**;
  `refdes build` → site still written, "0 errors".
- The same edit with `--reseal`-style history absent (no event) → no warning.
- A field with `on_change: log` edited → warning fires (the digest covers it),
  while the baseline diff and `content_hash` do not move — the two-digest split
  asserted from the other side.
- `items_json` snapshot: the new keys appear for captured items and are absent
  for uncaptured ones, so an uncaptured project's payload is byte-identical to
  before (the same "absent key, not null" convention `items_json` already uses
  for `boards`).
- `render_site()` writes no history file — asserted by a tree hash around a
  build with `seal_write=False`.

**Deliberately does not do.** No release gate (H8), no site history disclosure
(H9), no restore-as-new-entry command, no diff UI, no VS Code hover change.
The marker is in the data and the diagnostics; surfaces come later.

## Phase H4 — `refdes history capture`, `redact`, and `migrate-seals`

**Adds.** The author-facing commands for everything the thread cannot supply:
terminal and unthreaded notes, and redaction.

**Files.** `src/refdes/cli.py` — a `history` subparser alongside the others at
`cli.py:1180-1520`, with `capture`, `redact`, and `migrate-seals`
sub-subcommands following the `keys`/`standard`/`former-ids` group pattern
(`cli.py:1454`, `:1415`, `:1518`). `src/refdes/history.py` gains `capture()` and
`redact()`. Docs: `docs/cli-reference.md`. Tests: `tests/test_history_cli.py`.

- `refdes history capture <item>` — a `manual` event. Says "captured", never
  "final". Refuses under `--no-write` through `_refuse_no_write()`
  (`cli.py:137`), the pattern already tested for `fetch` and `standard upgrade`
  (`tests/test_no_write.py:221`, `:258`).
- `refdes history redact <item-or-object>` — requires an explicit
  acknowledgement flag, removes the matching current objects and events, writes
  a `redacted` event naming what was removed **without repeating its content**,
  and prints the Git/clones/published-copies warning in its own output.
- `refdes history migrate-seals` — reads legacy seal files and writes
  `legacy-seal` markers (see H5 for what a marker is; the command lands here so
  the migration is one documented transaction, per `living-notes.md` §8's "do
  not delete legacy seal support until a migration has run").

**Verified against.**
- `capture` writes one object + one `manual` event, announces, and is idempotent
  on a second run.
- `capture --no-write` refuses with a nonzero exit and writes nothing
  (tree-hash test).
- `redact` without the acknowledgement refuses; with it, the object and its
  events are gone, the `redacted` event exists, and the warning text — asserted
  by substring — names Git, clones, and published copies.
- Sabotage: `redact` output must not contain the redacted body text. This is
  the test that keeps the audit event from becoming a leak.
- `migrate-seals` on a fixture carrying a legacy seal file produces markers and
  leaves the seal file itself untouched.

**Deliberately does not do.** No `history show`/`diff`/`restore` (H9 or later),
no project policy about who may redact (decided against), no Git integration.

## Phase H5 — sealing becomes history-backed; legacy-seal markers

**This is the phase threads 4a waits for.**

**Adds.** For a type whose standard declares history-backed capture, the
first writable build no longer writes a hash lock, an edit is no longer a build
error, and `links.py:623-634` no longer refuses to freeze a bare `follows:` on
an entry that a legacy seal file mentions. Existing seal files keep being read
and become **legacy-seal markers**: "recorded hash only; original content was
not captured."

**Files.**
- `src/refdes/seal.py` — `verify()` (`:222`), `append_only_items()` (`:187`),
  `is_sealed()` (`:199`), `_report_deleted()` (`:343`). The change is scoped by
  a per-type policy so v1/v2 behaviour is byte-for-byte untouched.
- `src/refdes/links.py:623-634` — the sealed-entry refusal in
  `plan_follows_freeze`. For a history-backed type the refusal is not reached;
  for a build-sealed type it stays exactly as written, including its warning.
- `src/refdes/build.py:1977` — the `seal.verify(project, write=seal_write,
  reseal=reseal)` call site; unchanged in shape, and it is the only seal write
  in the codebase (`cli.py:283` is the only place `seal_write` is ever true).
- `src/refdes/standards/hardware/v3/base.yaml` — `log` at `:239`,
  `append_only: true` at `:243`, which **stays**: it keeps its authoring
  meaning ("an entry is not rewritten in place; corrections are new entries")
  and loses the build lock. The knob that expresses that is open question Q1;
  the conservative shape is a type-level `sealing: history` defaulting to
  `build`, so nothing written before this phase changes behaviour.
- Tests: `tests/test_seal.py` (15 tests, all must pass **unmodified** — they
  exercise build-sealed types), `tests/test_history_seal.py` (new),
  `tests/test_integration.py:205` (`test_log_entries_are_sealed_and_edits_are_caught`
  — stays green, because the example project is not history-backed).

**The asymmetry, stated explicitly.** `_report_deleted()` (`seal.py:343`)
iterates **seal files**, not append-only items. So a legacy seal file whose
type stopped sealing would keep erroring on deletion while no longer locking
edits — hash lock off, deletion lock on. For a history-backed type, a missing
sealed record becomes the same class of diagnostic as an edit: a warning naming
the key and the seal file, never an error. That is what makes this repo's six
seals (`.refdes/log-seal-board-a.yaml`, `LOG-A-001`..`LOG-A-006`, all
`hash_format: 2`) behave coherently: they become six markers, they never error
on edit or on deletion, and `audit` still reports them.

**`--reseal` and `audit`.** For build-sealed types, unchanged. For
history-backed types there is nothing to reseal: the flag is accepted, says so,
and captures nothing (Q2). `audit`'s "Append-only entries edited after sealing"
section (`cli.py:644`, fed by `seal.resealed_ids()` at `seal.py:411`) keeps
printing for build-sealed types and gains a sibling section for
edited-after-captured items, which is the honest replacement in the report.

**Verified against.**
- **The decisive one, taken from the analysis §3 transcript:** a history-backed
  project, entry sealed by a legacy seal file, bare `follows:` added to it,
  `refdes index` → the edge **freezes**, the chain forms, the capture line
  prints, and `check` reports zero errors. Before H5 this transcript ends with
  a refusal and an edge that stays bare forever.
- Edit a history-backed entry after capture → `check` and `build` both exit
  **0** with the H3 warning. Before H5 this is a build error.
- `--reseal` on a history-backed entry → no hash overwrite, no silent loss of
  the prior hash. Assert the legacy seal file's bytes are unchanged.
- v1 and v2 projects: `tests/test_seal.py` and `tests/test_integration.py:205`
  pass unmodified; a v2 project's whole tree is byte-identical across
  build/check.
- This repo builds: `python -m refdes build` on the repository's own `items/`
  with the six seals present exits 0, and after `history migrate-seals`,
  `.refdes/history/events/` holds six `legacy-seal` markers while
  `.refdes/log-seal-board-a.yaml` is unchanged.
- Sabotage: delete `LOG-A-001` → warning naming the seal file, exit 0 (not the
  current error). Restore it.

**Deliberately does not do.** No deletion of legacy seal support, no rewrite of
`seal.py`, no change to v1/v2, no `tasks:`, no site changes, no change to
baselines (`lifecycle._items_map`, `lifecycle.py:265`) or their hash-format
handling. Legacy seal files are still read; nothing is deleted from disk.

## Phase H6 — `tasks:` on the merged log type, and its fold

**Adds.** The `tasks:` field and the fold that resolves "the list at this
tip", under the four fold rules of `living-notes.md` §5.

**Files.** `src/refdes/standards/hardware/v3/base.yaml` (the `log` type at
`:239`) gains `tasks:` as a structured list field with `on_change: log` — the
single most important byte in this phase, because it is what keeps a task tick
out of `content_hash` (`build.py:1219`), seals, and baseline diffs. The fold
reuses `chains._fold_from_tip()` (`chains.py:515`) and
`resolve_current_with_source()` (`chains.py:581`) rather than adding a second
fold: nearest own declaration wins, inherited `defaults:` do not declare
(`chains.py:440-451`), omitted preserves, explicit `tasks: []` clears,
differing equally-near declarations are ambiguous and reported, and an unmerged
fork returns one labelled list **per tip** via `chains.thread_tips()`
(`chains.py:361`) — never a union, never one global list. Validation of task
rows (unique ids, known state values) goes where field validation already goes
(`build.validate_items`). Tests: `tests/test_tasks.py`.

Task rows are `{id, text, state}` with `state: [open, done, dropped]`.

**Verified against.**
- Fold: nearest declaration wins; omission preserves; `[]` clears; a
  replacement replaces the whole list.
- Ambiguity: two equally-near differing lists → the item reports "task
  reconciliation required" and prints no single list; equal lists are agreement
  and print one.
- Fork: two tips → two labelled lists, and no assertion of a single current
  list anywhere in the output.
- **The `on_change: log` guarantee, from both sides:** ticking a task changes
  `semantic_digest` (so history sees it) and leaves `content_hash` and the
  baseline diff untouched. Sabotage: flip the field to `on_change: invalidate`
  and the baseline test fails — that is the test that protects the property
  this whole design leans on.
- A task on an entry with no `follows:` at all (an ordinary log head, which is
  the decided shape of "the first task list", §5) folds to itself.

**Deliberately does not do.** No `refdes work`, no `refdes thread`, no gate, no
checkbox UI (the browser editor is a separate design and an optional client),
no `tasks_add:`/`tasks_done:` (decided against), no writing derived rows into
`tasks:` (they are not tasks).

## Phase H7 — `refdes thread`, `refdes work`, and the index `threads` projection

**Adds.** The two read commands and the machine projection, so none of this
requires a site build.

**Files.** `src/refdes/cli.py` (two subparsers at the `cli.py:1180` block; new
`cmd_thread` / `cmd_work` alongside `cmd_index` at `:405`);
`src/refdes/render.py:511` `items_json()` gains a `threads` key — the payload
today exports `boards`, `workspaces`, `coverage`, `types`, `items`, `next_ids`,
`diagnostics` and has no thread projection, and the extension must not rebuild
the chain itself. The fold and tip logic are imported from `chains`, and the
derived rows come from what already exists: coverage
(`build.compute_coverage`, surfaced by `lifecycle._rule_uncovered_requirements`
`lifecycle.py:548` and `_rule_unverified_requirements` `:552`), checks
(`build.run_checks`, `build.py:937`), blocked chains
(`blocked.resolve` `blocked.py:68`, `blocked.by_item` `:135` — currently absent
from the index), citations (`citations.verify` `citations.py:483`,
`_rule_unpinned_citations` `lifecycle.py:508`,
`_rule_missing_vendored_copies` `:519`), proposed/on-hold verdicts via
`chains.resolve_current(..., "status")` (`chains.py:552`), and forks
(`chains.resolve` `chains.py:726`, `thread_tips` `:361`). Tests:
`tests/test_thread_cli.py`, `tests/test_work.py`.

**The five binding rules land here, as output structure, not polish.** Two
separate labelled groups with separate numbering and derived rows never written
back; derived rows self-closing with no tickable state; every open task printing
its declaring entry and that entry's date (`open since LOG-A-004, 2026-08-30`),
relative spans only under an explicit `--as-of`; a concluding folded verdict
printed **together with** its tip's open tasks (the `satisfying_statuses`
question `blocked._is_settled()` `blocked.py:23` already asks, pointed at the
thread); and the gate rule of H8, which is not in this phase's output at all.

**Verified against.**
- `refdes thread <ref>` on a one-tip thread: header, tip, capture line, tasks
  with age, derived block.
- Forked thread: both tips listed, one `Tasks at <tip>` block per branch, and
  no line anywhere asserting a single current status.
- `--as-of` absent → absolute declaring dates only, no relative span, and the
  output is byte-identical across two runs on different simulated clocks (the
  reproducibility rule).
- Derived rows self-close: fix the uncovered requirement, re-run, the row is
  gone and no "done" was recorded.
- `items_json` `threads` key: present for threaded projects, absent otherwise,
  so a non-threaded project's payload stays byte-identical.
- Neither command writes a byte: tree-hash test around both, and neither
  appears in the sealing path.

**Deliberately does not do.** No VS Code hover change, no `refdes serve`, no
site panel, no stale-tip prompt (deferred, and it needs an explicit
`last_touched_at` that nothing here writes), no writing into source files.

## Phase H8 — two optional release-gate rules, both off

**Adds.** `open_tasks` (a release blocks while any thread tip carries an open
author task) and `captured_edits` (a release blocks while any item is edited
after captured). Both off by default, both enabled through the existing
`release_gate:` overlay.

**Files.** `src/refdes/model.py:52` `RELEASE_GATE_DEFAULTS` gains two entries
of `{release: false, revision: false}`, which makes them members of
`RULE_NAMES` (`lifecycle.py:588`) and of the overlay validation
(`schema.py:174-209`) automatically; two `_rule_*` functions added to `_RULES`
(`lifecycle.py:575`), after which `evaluate_gate()` (`lifecycle.py:604`) and
`stamp()`'s refusal (`lifecycle.py:697-699`) need no change. Docs:
`docs/lifecycle.md`'s printed defaults block. Tests: `tests/test_lifecycle.py`.

**Verified against.**
- Default-off: an existing project with open tasks and an edited-after-captured
  item stamps a release exactly as it does today — the strongest
  nothing-changed test in the phase.
- Enabled via overlay: each rule blocks with an offender list naming the item,
  and `revision` stays false while `release` is true.
- An unknown rule name in the overlay is still rejected with the existing
  message (`schema.py:189`).
- `open_tasks` counts **author** tasks only: a thread whose only open work is
  derived rows does not trip it (rule 1 and rule 2 of §5, enforced at the gate).

**Deliberately does not do.** No note type that blocks on its own, no
project-policy engine, no default-on anywhere.

## Phase H9 — baseline snapshot events and the site history disclosure (optional)

**Adds.** `revision`/`release` write `baseline` events into the same store, and
the item page gains a history disclosure showing captured content, the
edited-after-captured marker, and a baseline selector.

**Files.** `src/refdes/lifecycle.py` — `stamp()` (`:642`) writes events beside
the compact baseline it already writes; `diff_against()` (`:804`) unchanged in
contract. `src/refdes/render.py:756` `render_site()` and
`src/refdes/templates/item.html.j2` (the thread panel at `:36-80` is the
pattern for a panel that is absent, not empty, on pages that have nothing to
show).

**Verified against.** A baseline created after this phase resolves
"what did this item say at rev-B?" from the store; a baseline created before it
says rich content is unavailable rather than inventing text from current files
— that assertion is the phase's reason to exist.

**Deliberately does not do.** No change to the compact baseline schema, no
change to `diff_against`'s hash-only semantics, no backfill of old baselines.
The threads 4b static panel is a **client** of H7's projection and this phase's
events; it must not own computation or trigger writes.

## Threads handoff

**4a lands after H5.** Stated plainly: the minimum that unblocks it is H1 + H2 +
H5, and H3 + H4 are included in the handoff only because H5 without them is the
option the analysis rejected (a lock removed with nothing behind it, or docs
claiming a policy the code does not implement). H6–H9 are **not** on the path —
nothing in 4a waits for `tasks:`, the two read commands, or the gates, and
delaying 4a for them would repeat the mistake this plan exists to end.

**Why H5 and not earlier.** The blocker is not the type merge; the analysis is
explicit that the merge, `merge_types`, `owner`, `legacy_prefixes: [DEC]`, the
guard tests and the per-rename hint all stand unchanged. The blocker is that
`links.py:623-634` refuses to freeze a bare `follows:` on a sealed append-only
entry, so the edge stays bare forever and no chain ever forms — and the entry is
sealed by the first writable build (`build.py:1977`, `seal_write` true only at
`cli.py:283`). Only H5 changes that. H2 alone leaves the refusal in place for
sealed entries, because until sealing is history-backed the refusal is correct.

**What must change in the held branch when it lands.** From the analysis §5,
against the code as it will be after H5. The `tests/test_decision_merge.py` line
numbers below are branch-side — that file exists only on `ao/refdes-64/root`.

1. **Three docs.** `docs/design-log.md`, the release-nudge transcript in
   `docs/lifecycle.md`, and `docs/design/threads.md` §5/§7 wherever `append_only`
   is described as "build seals every new log" — including §7's own held-status
   paragraph, which becomes a historical note pointing here, and §4's "sealed
   the first time it's built" claim, which is what the analysis proved wrong.
2. **Two tests.** `tests/test_decision_merge.py:88` (`log["append_only"] is
   True`) — **stands**: H5 keeps the flag as the authoring declaration.
   `tests/test_decision_merge.py:221` (a sealed log entry survives the upgrade)
   — becomes vacuous as written and must be rewritten to assert the new
   contract: the seal file survives as a legacy-seal marker and the entry is
   editable with exit 0.
3. **The six seals** in this repo's `.refdes/log-seal-board-a.yaml`
   (`LOG-A-001`..`LOG-A-006`, `hash_format: 2`; `.refdes/log-seal.yaml` is
   `sealed: {}`). Landing 4a runs `refdes history migrate-seals` over them,
   producing six `legacy-seal` markers, leaving the seal file itself on disk,
   and stating the `_report_deleted()` asymmetry (it iterates seal files, so
   the deletion lock would otherwise outlive the hash lock). Their prior text is
   unrecoverable and no marker may imply otherwise (Q3).
4. **A rebase, and its known cost.** The branch was last rebased onto `1963e54`
   and main has moved since. The one conflict area is
   `revise.py::_rewrite_type_and_prefix_lines` (`revise.py:313` on main),
   where main's flow-style rewrite met `merge_types`; the resolution recorded in
   the analysis (widen the rename lookup to `{**mapping.types,
   **mapping.merge_types}`) must survive the rebase, and its two disclosed gaps
   — a merge-only mapping being invisible to `_stale_mapped_names`
   (`revise.py:662`), and
   flow-style field renames being refused rather than half-migrated — stay
   disclosed, not fixed, in 4a.

**Then 4b.** This repo's own decision→log migration, the static thread panel,
and removal of the `refdes-schema.yaml` bridge (which exists only because main
still has the `decision` type 4a deletes). Blocked on: 4a landing (the type
merge), and H7 for the panel — 4b's panel is a client of the `threads` index
projection and must not compute its own fold. The `items/` migration itself is
blocked on nothing else: `standard upgrade --to 3` applies `migration.yaml`'s
`merge_types` automatically, and the analysis verified that path live
(`defaults: { type: decision, prefix: DEC }` → `{ type: log, prefix: DEC }`,
`title:` → `summary:`, id preserved).

## Risks

**R1 — the store becomes a second source of truth for content.** A history
object is a snapshot, not the live item, and any surface that shows one must
name the event and the date. Mitigation: every read of an object goes through
the event that produced it, and the object format carries no "current" flag.

**R2 — file count.** One object per distinct item state plus one small event
per edge. Content addressing deduplicates repeated baselines, and there is no
global mutable index, so branch work does not funnel into one conflict file.
Mitigation: H1's tests assert a no-op load writes nothing; watch the count on
this repo after H5's migrate.

**R3 — capture noise.** VS Code runs a writable `index` after every save, so
the capture line could become wallpaper. Mitigation: it prints only when an event
was actually written, and never in `--compact` output (Q4).

**R4 — the interim lock.** Between H5 landing and 4a landing, `main`'s v3 `log`
is history-backed while `decision` still exists separately. That is a strictly
better interim than today's (nothing new gets sealed under the rejected policy),
and it is the reason H5 lands on `main` before 4a rather than inside it (Q7).

**R5 — the two digests drift apart.** `semantic_digest` and `content_hash`
differ by design; a future change that "simplifies" one into the other would
silently make task ticks churn baselines, or make history blind to edits.
Mitigation: H1 and H6 each carry the sabotage test from opposite sides.

**R6 — finding 35 (cross-item calc references) wants resolved upstream values
inside the content hash** (`docs/design/backlog.md` finding 35 §4, with a
coordinated `HASH_FORMAT` bump shared with finding 26). If that lands, an item
whose *upstream* value moved would be reported as changed by `content_hash`
consumers. If the history digest ever absorbed those values, the same item
would read "edited after captured" with nobody having edited it — which
contradicts decision 2's promise that the marker is about the author's own
content. Mitigation, taken as the conservative default: `history_format: 1`
digests the item's **own** declared payload only, and the divergence from
`content_hash` is documented as intentional. This is Q5 — it was the one place
where two decided designs want opposite things; Jared ratified the conservative
default on 2026-09-19.

**R7 — `--reseal` is a documented user habit** that H5 makes meaningless for
history-backed types. Silently no-oping it is the worst outcome; the message
must say why (Q2).

## Open questions for Jared

**All eight are decided.** Jared ratified every one of them on 2026-09-19, in
each case as the conservative option this plan had already assumed; the assumed
text above each decision stands as the decision itself. Nothing below blocks a
worker, and H1 can start.

**The owner's caveat, in his terms.** The defaults are accepted, but the
vocabulary has to be reviewed before these terms settle: he wants to know
whether any words are duplicated in meaning or unclear in their connotations,
because the goal is that the vocabulary be intuitive. That review is a separate
task already under way. It may rename terms this plan introduces — `record`,
`recorded`, `history`, `snapshot`, `tasks` — without reopening the eight
decisions themselves: a rename touches the names on disk and in output, not what
was decided about them.

**Applied 2026-09-20 (owner-approved, `docs/design/vocabulary-review.md` §3):**
P1 renamed `record`/`recorded` to `capture`/`captured` throughout these design
docs — the moment, the marker, the `refdes history capture` command, the
`captured_edits` gate rule, and the planned identifiers (`edited_after_captured`,
the `captured`/`edited_after_captured` index pair). `history`, `snapshot` and
`tasks:` keep their names (P3 keeps `snapshot`; P6 keeps `tasks:`). The shipped
`records:` link verb and its `recorded_by` inverse are untouched — that is the
collision P1 removed.

**Q1 — what expresses "this type captures instead of locking"?**
(a) a type-level `sealing: history` in the standard, defaulting to `build`;
(b) a project/standard-level `sealing: build | none` switch (the analysis's
b2); (c) an implicit `standard_version >= 3` test in `seal.verify`.
**Assumed: (a).** It is per-type where the property is per-type, it needs no
project knob that living notes will delete again, and the default keeps every
existing project byte-identical. (c) is the smallest diff but hides a policy in
a version comparison, which is how the `records:` confusion happened.

**Decided (Jared, 2026-09-19): (a)** — a type-level `sealing: history` in the
standard, defaulting to `build`.

**Q2 — what does `--reseal` do on a history-backed type?**
(a) accepted, prints "sealing no longer applies to this type; nothing was
rewritten", captures nothing; (b) captures a `reseal` event capturing current
content; (c) errors. **Assumed: (a).** (b) invents a second capture moment the
decisions do not include, and (c) breaks a flag people have in muscle memory.

**Decided (Jared, 2026-09-19): (a)** — accepted, prints "sealing no longer
applies to this type; nothing was rewritten", captures nothing.

**Q3 — do the six existing seals get `migrated-current` snapshots?**
`living-notes.md` §8 permits capturing their *current* content as a clearly
dated `migrated-current` event. **Assumed: no — bare `legacy-seal` markers
only**, with `migrated-current` available behind an explicit flag on
`history migrate-seals`. Capturing current text is one flag away from being
mistaken for seal-time text, which is the specific lie §8 forbids.

**Decided (Jared, 2026-09-19): no** — bare `legacy-seal` markers only, with
`migrated-current` available behind an explicit flag on `history
migrate-seals`.

**Q4 — when does the capture line print?**
**Assumed: only when an event was actually written**, never on an idempotent
no-op, and never in `index --compact` (machine output stays parse-clean). A
project that wants silence passes `--no-write` and captures explicitly.

**Decided (Jared, 2026-09-19): as assumed** — the line prints only when an event
was actually written, never on an idempotent no-op, and never in `index
--compact`.

**Q5 — does the history digest include resolved upstream calc values?**
See R6. **Assumed: no** — own declared payload only, diverging from
`content_hash` deliberately if finding 35 lands.

**Decided (Jared, 2026-09-19): no** — the history digest covers the item's own
declared payload only, and diverges from `content_hash` deliberately if finding
35 lands.

**Q6 — is `tasks:` allowed on types other than the merged `log`?**
**Assumed: no** — `log` only in hardware@3, `state: [open, done, dropped]`,
`on_change: log`. A second type gets a decision of its own.

**Decided (Jared, 2026-09-19): no** — `tasks:` is on the merged `log` type only
in hardware@3, with `state: [open, done, dropped]` and `on_change: log`.

**Q7 — does H5 land on `main` before 4a, or inside it?**
**Assumed: before.** It is independently verifiable against v1/v2 (unchanged)
and against this repo's own six seals, and it makes the interim strictly safer
than today. Landing it inside 4a makes the biggest untested combination
(merge + migration + sealing reversal) one review.

**Decided (Jared, 2026-09-19): before** — H5 lands on `main` ahead of 4a.

**Q8 — do the two H8 gate rules ship together?**
**Assumed: yes, both off by default.** They are the same two-line mechanism, and
`captured_edits` without `open_tasks` (or vice versa) leaves a decided policy
with no enforcement path.

**Decided (Jared, 2026-09-19): yes** — the two H8 gate rules ship together, both
off by default.

## What this plan does not decide

Nothing in `living-notes.md` §§1–9, `threads.md` §§1–6, or
`browser-editor.md`'s Decisions. The browser editor stays an optional client:
its architecture decision (Option B, `refdes serve` with a separate `/edit/`
app, Python authoritative) means every capability in H1–H8 is reachable through
Python services and the index payload, and H7's `threads` projection is the
contract it will consume. Nothing here creates `refdes serve`.
