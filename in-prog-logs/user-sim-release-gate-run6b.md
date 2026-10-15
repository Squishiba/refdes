# User-simulation release gate, run 6b — the new surfaces (3010883..374a4aa) as an author meets them

Scope per `.scratch/TASK.txt`: living notes end-to-end (threads, `tasks:`,
`refdes thread`/`work`, `--as-of`), history capture lines and the
`edited after captured` path, the W5a task pane in `serve` preview and in
`_site/`, `refdes serve --port` relaunch reclaim, and the `on_change:` key
(including the retired `log` spelling). Run 5's carry-forward and the
upgrade path are run 6a's.

Harness (per `.scratch/COMMON.txt`): `.scratch/rr <projectdir> <args…>`
cd's into the project inside the script and runs
`PYTHONPATH=<worktree>/src /home/jorb/work/venv-refdes/bin/python -m refdes.cli`.
Every project under `.scratch/run6b/`, made with `refdes init`, one copy per
sweep. `serve` started in background with `&`, PID recorded, stopped with
`kill <PID>`. HEAD = 374a4aa (main for this run).

## 0. What's new for a user, from `git log --oneline 3010883..374a4aa` + `changelog.d/`

User-visible in this delta (fragments read): `refdes thread` (H7b),
`refdes work` (H7c), `tasks:` on `log` (H6), decision→log merge + `follows`
verb (threads 4a), `freeze`→`anchor` wording (P4), project/item `history:` →
`on_change:` rename (breaking), `on_change` mode `log` → `timeline`
(breaking), `revise` → `rename` with deprecated alias (P12), the W5a task
pane on preview+site, `serve --port` self-reclaim, uncaptured-log-edit
warning, `edited after captured` remedy text, `open_tasks`/`captured_edits`
gate rules, the `threads` key in `items.json`, `differs_from` (vocab P20),
docs anchors, and a batch of run-5 fixes (F1–F8, B1's class via
decision-options list validation, sealing overlay note, checks: unknown key).

## Findings table

| # | Sev | Surface | Finding |
|---|---|---|---|
| **B1** | **BUG (medium)** | `follows:` tip-anchor | A fork authored in one editing session is silently rewired into a linear chain: a bare `follows:` naming a non-tip entry is anchored to the thread's current tip, and the *only* trace is a capture line that already names the new parent. A merge collapses the same way and its list is left holding a duplicated self-edge, exit 0, no diagnostic. No user doc says tip-anchoring happens, that a bare id cannot fork, or that composites are how you author one. |
| **B2** | **BUG (medium)** | item `on_change:` validation | Mode values *inside* the item's `on_change:` mapping (`mode:` and each `fields:` value) are accepted unvalidated; `mode: timeine` silently stops the whole-item suppression applying (body edit goes `changed 0` → `changed 1` in `audit`), with no diagnostic. The scalar spelling of the same value is validated, and the emitted JSON Schema declares the same enum. |
| F1 | friction (low) | docs | `docs/design-log.md`'s link table says `follows` = "the earlier log entry this one continues" with a bare-id example; the tip-anchor rule that overrides it lives only in the changelog fragment. |
| F2 | friction (low) | keys / merge | A merge needs composite `ID@key` pins (bare ids anchor to the tip and collide), and no human-facing output prints an item's key: `ls` has no key column, `thread --json`'s projection carries no per-entry key — the key is only reachable by scraping the `refdes index` JSON payload (where it does exist, as `items[].key`). |
| F3 | friction (low) | docs (`schema-reference.md`) | §`on_change` says "Only `invalidate` has any effect today … `timeline` … behaves exactly like `ignore`" with no pointer to the history-backed case this release builds on (a `timeline` tick moves the history digest → `edited after captured`, verified in sweep 1); and the item-level section never shows the `mode:` key the engine and the emitted JSON Schema both accept. |

## 1. Living notes, end to end

**B1 — the tip-anchor silently eats the author's fork (and a merge), and leaves a duplicate self-edge.**

Reproduction (`.scratch/run6b/p1`, fresh `refdes init`, hardware@3). One
editing session, four entries: a root with tasks, a continuation, a fork of
the root, and a merge of the two tips — exactly the topology
`docs/cli-reference.md`'s `thread`/`work` sections render:

```yaml
- id: LOG-A-001 …            # root
- id: LOG-A-002
  follows: LOG-A-001         # continuation
- id: LOG-A-003
  follows: LOG-A-001         # fork of the root
- id: LOG-A-004
  follows: [LOG-A-002, LOG-A-003]   # merge
```

First writable load:

```console
$ refdes check
captured LOG-A-001: LOG-A-002 now follows it
captured LOG-A-002: LOG-A-003 now follows it
captured LOG-A-003: LOG-A-004 now follows it
…
```

LOG-A-003 never said it follows LOG-A-002; LOG-A-004 never said it follows
LOG-A-003. The file after the load:

```
21:    follows: LOG-A-001@ryr8arv299b
32:    follows: LOG-A-002@33a58t8ajm8        # author wrote LOG-A-001
40:    follows: [LOG-A-003@kw998es5fes, LOG-A-003]   # author wrote [LOG-A-002, LOG-A-003]
```

Both bare targets were anchored to the thread's current tip. The intended
fork is a chain, and the merge is a **self-duplicated edge** — the list
follows LOG-A-003 twice, once composite, once bare, and the next writable
load quietly composite-expands the second one (`rewrote 1 reference(s)`)
instead of flagging the collision. `refdes thread LOG-A-004` confirms the
topology the author lost:

```
Thread: LOG-A-001 -> LOG-A-002 -> LOG-A-003 -> LOG-A-004  (one tip)
```

Why it matters: tip-anchoring is deliberate (changelog
`threads-4a-follows-link`: "a writable load anchors it to the current tip of
the referenced entry's thread") and sensible for the one-entry-per-session
author it was designed for. But nothing in `docs/` says so: `design-log.md`
describes `follows` as "the earlier log entry this one continues", the
`thread`/`work` docs show forks as a normal thing authors have, and no
document anywhere says how to *author* one. An author who writes a fork in
one sitting loses it with zero signal — the capture line reports the new
parent as if it were the authored edge.

What I'd want instead: (a) a line when anchoring *replaces the named target*
(`LOG-A-003 named LOG-A-001, which is not the tip; anchored to LOG-A-002 —
write LOG-A-001@key to keep it pinned`), (b) a diagnostic when a `follows:`
list resolves to a duplicate target (the composite+bare pair is invisible to
any dedup that compares text), and (c) the tip-anchor rule + composite-for-forks
spelled out in `docs/design-log.md`.

**worked**: first `refdes check` on the thread wrote the three capture lines
per the changelog shape, minted keys and rewrote references with the stderr
notice; a later content edit to captured LOG-A-002 (citation path change)
produced exactly the documented `edited after captured` warning with remedy
and docs URL, warning-only, exit 0; `refdes thread`/`refdes work` text
matches the docs' shape exactly (header, `Verdict: … N open tasks remaining
below`, per-tip blocks, `Derived:` grouped by kind with `Coverage:`/
`Citations:` headings); a YAML footgun (`summary: Merge: …`) gets a clear
error with file:line.

**worked (fork, once authored by hand)** — `.scratch/run6b/p2`, built one
load at a time. A merge authored as `follows: [LOG-A-002@eq05mhr2nd5,
LOG-A-003@1k7f2e1ry72]` (composite pins — the bare spelling collides, B1)
landed cleanly, and a fork exists only when *every* child of the fork point
is composite-pinned (LOG-A-005 and LOG-A-006 both `follows:
LOG-A-004@rwxh540ef23`). The forked output is then byte-for-byte the doc
shape, and it is good:

```console
$ refdes thread LOG-A-005
Thread: LOG-A-001  (forked: tips LOG-A-005, LOG-A-006)
…
Tip: LOG-A-005  2026-09-08  Continue the merged line: layout freeze.
Verdict: accepted (LOG-A-002, 2026-09-02), 2 open tasks remaining below
Tasks at LOG-A-005:
  1. [ ] T-thermal-model  Model worst-case copper temperature.  (open since LOG-A-004, 2026-09-05)
  2. [ ] T-decoupling  Recheck decoupling near U14.  (open since LOG-A-004, 2026-09-05)
Tip: LOG-A-006  2026-09-09  Fork from the merge: thermal re-check.
…
Derived: … (no Forks heading in a per-thread block)
```

`refdes work` adds the `Forks: LOG-A-001 tips LOG-A-005, LOG-A-006` derived
row and prints per-tip `Tasks at <tip>:` blocks, exactly as
`docs/cli-reference.md` says. The task fold follows `docs/design-log.md` §Task
lists verbatim: the merge tip's declared list replaces the inherited one
whole (LOG-A-005 inherits LOG-A-004's list, `open since LOG-A-004`),
LOG-A-006's own declaration replaces it on its branch, the inherited
accepted verdict prints beside each tip's open tasks, and open-since is the
*declaring* entry's date.

**worked (authoring mistakes)** — every mistake a real user makes at the
task list gets a first-class diagnostic, verified in `.scratch/run6b/p3`
(copy of p2, one edit at a time):

- state typo: `tasks[0].state: 'oppen' is not one of open, done, dropped. Did
  you mean 'open'?` — row-naming + nearest-word, as the changelog promises.
- duplicate id: `tasks[1].id: 'T-thermal-model' is already used at tasks[0]
  -- task ids must be unique within a list`.
- `tasks:` on a requirement: `unknown field 'tasks' on requirement -- did you
  mean the field 'tags'? A misspelled field name silently drops it instead of
  erroring.` (correct posture: the type doesn't declare it; the "silently
  drops" sentence names *why* the check exists).
- scalar row `- T-thermal-model` in `tasks:`: `tasks[0]: 'T-thermal-model' is
  not a task -- a task is a mapping with an 'id', a 'text', and a 'state' of
  open, done or dropped, as in tasks: [{id: …}]` — full example in the error.
- dangling `follows: LOG-A-999`: names all three causes and the remedy for
  the rename case, plus the docs URL.

Nit: a typo'd state on a *captured* entry prints `edited after captured`
alongside the ERROR (the bad digest reaches the semantic hash), and the
warning clears when the typo is fixed — noise above the real error, self-
healing, no action taken.

`refdes thread <ref>` on a non-thread item: `error: REQ-A-001 is not part of
a thread (no follows: edge either way) -- refdes thread shows a thread's tip,
tasks and derived rows`, exit 2; unknown ref: the standard
`no item 'LOG-999' … (looked up by display id, then surrogate key)`, exit 2.
`--as-of` prints the relative span (`open since LOG-A-004, 2026-09-05 -- 15
days`) and refuses `--json` with a full-sentence explanation, exit 2 — both
commands, both documented. `thread --json` is byte-identical to the index
payload's `threads[0]` (checked with a Python equality compare). A task tick
by hand-edit (documented way) is exactly a timeline event: `check` stays
clean, a stamped `revision` reports `changed 0 … (7 unchanged)` across the
tick/untick (content hash stable, as designed), and ticking on the *captured*
root entry prints `edited after captured` — matching lifecycle.md §the
`captured_edits` note ("task rows are part of the fields the history digest
covers") and clearing on revert.

## 2. History: capture lines, edited-after-captured, `refdes history`

- **Capture line on first `follows:` write**: `captured LOG-A-001: LOG-A-002
  now follows it` on the first writable load, key minting notice on stderr —
  matches `threads-4a-decision-merge`'s sample block exactly. A capture of
  kind `followed` carries no timestamp (thread line reads `(followed by later
  entry)`, per cli-reference), a manual one does
  (`LOG-A-006 (captured by hand, 2026-10-15T00:59:45Z)`).
- **Edited after captured** fires on a content edit (citation path), on a
  task tick of a *captured* entry, and on a body edit after a *manual*
  capture; names the event id, the kind (`followed`/`captured`), the
  capturing edge when there is one ("captured when LOG-A-002 followed it"),
  gives the `amends:` remedy and the docs URL, warns without changing exit
  codes. Every message says what to do next (the `captured`-kind one omits
  the "captured when …" clause because there is no successor — correct).
- **`refdes history capture`**: `captured LOG-A-006: manual capture` / repeat:
  `LOG-A-006 is already captured; nothing was written` (exit 0) / bogus id:
  exit 2 with the standard lookup sentence. Works on any type
  (`captured REQ-A-001`).
- **`refdes history redact`**: refuses without `--confirm` (exit 2) with the
  irreversibility + Git-limits sentences; with it, `redacted 1 object(s) and
  2 event(s)` + redaction event written naming removals by digest only.
  The 2 events for one manual capture: the store also held the `followed`
  capture of LOG-A-006 created by the tip-anchor rewiring of §1's LOG-A-005
  edge (later undone by hand) — events are append-only and redaction
  removes by item, so the count is honest. The thread's capture line for the
  item disappears afterwards and the `edited after captured` warning clears
  (nothing left to compare).
- **`refdes history migrate-seals`** on a project with no legacy seal:
  `no legacy seal files found; nothing to migrate`, exit 0.
- Subcommand help texts read as decisions, not just flags ("capture one
  item's snapshot by hand (for terminal and unthreaded notes a `follows:`
  edge will never supply)").

## 3. The W5a task pane — preview over HTTP, and the built site

`refdes serve --no-open --port 8737 --token-file ../p2-token.txt` (PID
recorded, stopped with `kill $PID`). Launch URL fetched with curl + cookie
jar → 302 to `/`, then `/preview/log-a-006.html` → 200; the same URL
**without** the cookie → 403 (gate honored).

- Pane markup on a threaded log page (preview *and* `_site`, 20+ refs):
  `refdes-taskpane-toggle` (starts `hidden`), tabs
  `role=tablist` one per open tip of the fork (LOG-A-005 / LOG-A-006),
  the note **`viewing LOG-A-006 · tasks as of tip LOG-A-005`** on panels
  whose tip is not the page's entry (panel for tip LOG-A-006 on page
  LOG-A-006 carries no note — the note only where it means something),
  tip line, verdict line, per-tip `Tasks at <tip>:` list with the exact
  `refdes thread` row text (`(open since LOG-A-004, 2026-09-05)`), and a
  collapsed `<details>` *Derived (auto clears when fixed)* with `Coverage`
  / `Citations` headings. On a doubly-old page (LOG-A-001 of a forked
  thread) both panels carry their own `viewing LOG-A-001 · tasks as of tip
  LOG-A-005/LOG-A-006` note.
- **Read-only posture, checked mechanically:** the site page has no
  `<form>`, no `<textarea>`, no `/api/` or `/edit/` reference, no token
  (the launch token appears only in a preview-only `<meta
  name="refdes-token">`, absent from `_site`); the only `<input>` on a site
  page is the CSS sidenav checkbox. `assets/taskpane.js` (8.7 KB) contains
  the word `fetch` exactly once — inside a comment: "It fetches nothing and
  writes nothing".
- **Assets:** `assets/taskpane.css` + `assets/taskpane.js` are emitted into
  `_site/assets/` and referenced from the threaded pages; a project with no
  `follows:` edge anywhere (p4) gets *neither* asset file, zero taskpane
  markup, and no `threads` key in `items.json` — the "publishes exactly the
  pages it published before" claim, verified as far as one checkout can.
- The preview workbench decorations (diagnostics panel, preview-data JSON,
  editor bar) are response-only; `_site/log-a-006.html` has none of them.
- **Not checkable headless:** visual position (bottom-right floating), tab
  switching feel, pane greying off-anchor behavior, and "invisible unless
  JavaScript runs" — I read the markup and the `hidden` attributes; no
  browser was available. The markup is semantic (roles, aria-selected,
  tabindex) and the hidden-by-default is mechanical.

## 4. `refdes serve --port` — relaunch reclaim (#210) and held-port refusal

- Started serve on 8737, curled it (real accepted connection), `kill $PID`,
  relaunched on the same 8737 ~0.3 s later: came back (HTTP 302 launch
  redirect), token file rewritten. Relaunch is the "ordinary scripted
  recovery" the fragment promises. (The strict server-side-TIME_WAIT
  repro can't be forced reliably from a plain `curl`; the unit level is
  #210's pinned tests. Smoke-level: relaunch works.)
- Port held by a live foreign listener (a plain Python socket):
  `error: cannot listen on 127.0.0.1:8737: Address already in use; choose
  another --port, or drop --port to get an ephemeral one`, exit 2 — word for
  word the documented refusal, and it names the two exits.
- `--port 87370` / `--port 0`: usage error naming the range, exit 2, no
  token file written.
- A SIGTERM'd serve removes its token file (verified twice), and the token
  read from the file carries `_` characters exactly as the docs warn —
  reading the file, not scraping, matters.

## 5. The `on_change:` key, and the retired spellings

All four renames land with the posture the changelog promises, verified on a
copy (p5) of the green tree:

| Spelling tried | Result |
|---|---|
| item `on_change: timeline` | loads clean, no-op, as documented for today's hash |
| item `on_change: log` | ERROR naming `timeline`, the P9 rationale, and "It is read as 'timeline' in this build so the change policy is not silently lost", exit 1 |
| item `history: ignore` | ERROR naming `on_change:` + "Its override is used in this build …", exit 1 |
| project `history: {default: ignore}` | `configuration error: refdes-project.yaml: history: was renamed to on_change: -- it set the default on_change mode, not the history store; rename it in refdes-project.yaml`, exit 2 |
| project `on_change: {default: log}` | configuration error naming `timeline`, exit 2 |
| project `on_change: {default: timeline}` + item `mode:/fields:` | loads clean; WARNING "item-level on_change override has no 'reason'; suppression should be self-documenting" — the reason-requirement is a nudge, not a gate, and the nudge sentence is the *why* |

**B2 — mode values inside an item's `on_change:` mapping are not validated,
and a typo silently flips change-tracking semantics.**

```console
$ # item front-matter:  on_change: {mode: timeine}
$ refdes revision rmode2 && <edit the body> && refdes audit
Since last revision (rmode2, …):
  changed   1   REQ-A-001
```

With the correctly-spelled `mode: ignore` the identical body edit reports
`changed 0` (suppression works — good). Change one letter and: no error, no
warning, and the whole-item suppression quietly stops applying — the edited
field counts toward the content hash again, so downstream invalidation and
baseline churn come back exactly as the author was suppressing them. The
*scalar* form of the same value **is** validated (`on_change: 'bogus' must
be one of invalidate, timeline, ignore`, exit 1), and the emitted
`.refdes/schema.json` declares `mode`/`fields` as the same enum — the
enforcement exists at the load layer's edges and is missing in the mapping
interior. (Run 5's F7 is this exact class: list/mapping *sub-mappings*
escape the validation the scalars get.) What I'd want: load-time validation
of `mode:` and each `fields:` value with the same "must be one of …"
sentence, exit 1.

- **worked**: precedence (item field → whole-item mode → schema field →
  project default) is what the docs state, and the `reason:` nudge fires
  exactly when the item override lacks one; the schema-reference sentence
  "Only `invalidate` has any effect today … `timeline` … behaves exactly
  like `ignore`" is true of the *content hash* and, as sweep 1 showed,
  incomplete for history-backed types (a `timeline` tick moves the history
  digest → `edited after captured`); a cross-reference to design-log.md
  there would close the gap.

## 6. Gate rules, the `rename` alias, and `keys adopt` (rest of the delta)

- **H8 gate rules.** With `release_gate: {open_tasks/captured_edits:
  {release: true, revision: true}}` in p6, `refdes revision blocked-rev`
  is blocked (exit 1) with
  `FAIL  open_tasks  LOG-A-005: open task T-decoupling (items/board-a/log.yaml:44), …`
  — per open tip, per task, clickable source line pointing at the
  *declaring* entry (LOG-A-004 lines), exactly the "who has what open"
  the docs sell. `captured_edits: pass` there is correct: the only live
  captures are `followed`-kind and their content is untouched (the
  edited LOG-A-006 capture was redacted in sweep 2).
- **Default posture unchanged.** A clean default project releases
  (after `refdes fetch` pins the one citation) and the stamped baseline's
  `gate:` block gains *exactly* the two documented `open_tasks: skipped` /
  `captured_edits: skipped` lines — old stamps don't fail, new rules are
  opt-in. The release stamp also prints the design-log nudge with
  placeholder ids, per the docs.
- **P12 rename alias.** `refdes rename map.yaml --dry-run` prints the
  full plan (prefix line, ids, and `addresses: [REQ-A-001@0jm5bs9tmbc] ->
  addresses: [REQ-B-001@0jm5bs9tmbc]` — keys preserved across a prefix
  rename). The old name still works: `refdes revise …` writes to stderr
  "`refdes revise` is now `refdes rename`; `revise` will be removed in the
  next minor release" and runs the same command.
- **P4 adopt wording.** `refdes keys adopt` reports the four counts
  separately — `minted`, `expanded link reference(s)`, `expanded check
  reference(s)`, `anchored 0 follows reference(s) at their thread tips` —
  then changed files (a keyed project's baselines get rewritten) and
  "Review the diff before committing." Re-running says `nothing to do --
  project already adopted`. Adopting on p5 (mid-sweep, baselines stamped
  by display id) prints `uncomparable baseline entry <rev>: <id>` lines
  for every pre-adoption baseline entry — honest: it tells you the old
  stamps stop being comparable, it doesn't pretend to fix them.

## Friction, summed up

The green-path experience on all five surfaces is good: every new command
has a doc section, every rejection names what to do next, and the
authoring-mistake diagnostics ("Did you mean 'open'?", the tasks-on-
requirement misspelling warning, the dangling-follows remedy) are the best
in the tool. The two real bugs (B1, B2) are the same species: *a mapping
interior is trusted where a scalar is validated* — follows' bare ids
anchored to the tip at load time (B1), and on_change mode values inside
the item's mapping escaping the validation the scalar spelling gets (B2).
F1-F3 are all doc-surface gaps that sit one cross-reference away from
closing.

## Coverage

| Area (from TASK.txt) | Status |
|---|---|
| 1. living notes end-to-end, thread/work/--as-of/JSON | done (p1-p3) |
| 2. history: captured/recorded, edited-after-captured, subcommands | done (p2/p3) |
| 3. W5a pane in serve preview and `_site` | done headless (p2/p4) — visual layout/tab feel not checkable without a browser |
| 4. serve --port relaunch + held port | done |
| 5. on_change: key/timeline/retired log | done (p5) |
| not covered | pane visual position/tab-switch feel (no browser); strict TIME_WAIT relaunch repro (#210's unit tests own that); `sets:`/`differs_from` (outside scope); real Git history for the history store |

## Appendix — reproducing the findings

```console
# B1: rr = PYTHONPATH=<worktree>/src <venv-python> -m refdes.cli, run in project dir
rr p1 init (starter)                       # author 6 log entries in ONE file:
# LOG-A-002..004 chain bare follows, LOG-A-005: follows LOG-A-004,
# LOG-A-006: follows [LOG-A-003, LOG-A-004] (intended merge)
rr p1 check && rr p1 thread LOG-A-006
# -> capture lines name LOG-A-003->LOG-A-004; thread is linear;
#    LOG-A-006 follows: [LOG-A-003@<key>, LOG-A-003] (self-edge), exit 0
# p2 = same graph authored with composite pins on every non-tip follows -> fork/merge render
# B2: item front-matter on_change: {mode: ignore}; revision r1; edit body; audit -> changed 0
# change to mode: timeine; revision r2; edit body; audit -> changed 1, zero diagnostics
# scalar spelling on_change: bogus -> ERROR "must be one of invalidate, timeline, ignore"
