Status: Proposed, and **blocked on the owner**. Ten questions in §Open
questions for Jared are open as this is written; each phase below names the
answers it needs, and §8 tabulates which phases each answer gates. The rules this plan implements
are decided already — `docs/design/thread-workbench.md` §7a — and nothing here
reopens them. Unlike `docs/design/living-notes-plan.md`, which was written
after its questions were ratified, this one is written before: the shape of the
work is stable, the answers are not.

**Citations.** Line numbers are against `main` at `374a4aa`. The read-only task
pane is on `main`: PR #197 merged as `7c72311`, so `task_pane.py`, the pane
block in `item.html.j2`, and `taskpane.js` are cited like everything else.
Claims about CLI behavior were produced by running
`PYTHONPATH=$PWD/src python -m refdes.cli --help` and the relevant
`<command> --help`. Where something does not exist, this document says so, and
says how it was checked.

# Thread workbench W5b: ticks → a draft continuation

This is the plan for the second half of §8's W5. It is a plan, not a spec: the
decisions in §7a stand, and the job here is to order the work into steps small
enough to land and verify alone, name the mechanism each one builds on, and put
the genuinely open questions in front of the owner with options and a
conservative default each.

Granularity matches `living-notes-plan.md`'s — one reviewable change per phase,
each with its own tests — and the same rule applies: for every rendered fact,
name the Python mechanism that produced it.

## 1. The goal, and the one decided sentence it implements

§7a.2, quoted exactly (`docs/design/thread-workbench.md:238-242`):

> **Ticking collects into a draft.** Ticking a task in the pane collects the
> change into a draft continuation that the author saves deliberately. Ten
> ticks never become ten log entries. This is consistent with living-notes
> §5's decided complete-list model: saving appends a continuation with the
> copied-and-updated list and never mutates the tip.

W5b makes the pane's tick glyph (`task_pane._task_block`'s `"glyph"` field,
`src/refdes/task_pane.py:195`) a control that **collects** instead
of writing, and makes a deliberate save write exactly one new thread entry: the
tip's copied-and-updated complete `tasks:` list, with the ticked rows in the
state the author chose, appended to the thread's own file by the existing
creation path. It
adds no fold, no field, no storage, no site capability, and no second write
path. What it must add — a way to write `tasks:` and a way to append a thread
entry through the editor — does not exist yet, and §2 spells out how far the
current code gets.

## 2. What W5b builds on, verified

The eight mechanisms it stands on, and the four things it needs that do not
exist.

### Exists

**The task list, its states, and its change policy.** `tasks:` on the merged
`log` type is declared `type: tasks, on_change: timeline`
(`src/refdes/standards/hardware/v3/base.yaml:302`) — so a tick is visible to
history while leaving `content_hash`, seals, and baseline diffs alone. The row
state vocabulary is `TASK_STATES = ("open", "done", "dropped")`
(`src/refdes/model.py:209`), and row shape is diagnosed at the item by
`build.validate_items` (`src/refdes/build.py:329-380`), not discovered by a
consumer. Note the vocabulary drift from the design doc: `living-notes.md` §5
proposed `on_change: log` for this field; what shipped is `on_change: timeline`
(vocabulary review P2 renamed the project key to `on_change:` and this field's
value to `timeline`). The shipped spelling is the one W5b must cite.

**The fold and the projection — the pane's only source of truth.**
`chains.fold_tasks()` (`src/refdes/chains.py:811-816`) is the one walk;
`threads.threads_projection()` (`src/refdes/threads.py:328`) turns it into the
per-tip block `threads.py:441-494` renders, keeping the fold's four postures
distinct: `declared`, `cleared` (an explicit `tasks: []`), `undeclared`, and
`ambiguous` — the last two carry `rows: None`, because there is no list, not an
empty one. Open rows carry `open_since` (the declaring entry and its date). The
index payload carries this same object under `threads`
(`src/refdes/render.py:651`), and `refdes thread` / `refdes work` are the two
read commands over it (both verified present in `refdes --help`, and both say
in their own `--help` text that they compute no fold of their own). The
`open_tasks` release-gate rule exists and is off on both gate kinds
(`src/refdes/model.py:112`, `src/refdes/lifecycle.py:652`, dispatch at `:756`).

**The pane itself, read-only.** `src/refdes/task_pane.py` is a pure
client of that projection (`thread_views` `:80`, `panes_by_entry` `:100`,
`pane_for` `:115`, `_tab` `:128`, `_task_block` `:160`, `_derived_groups`
`:225`); `render_site` computes every pane once per render and emits the toggle
only for projects that show one (`src/refdes/render.py:997-1023`);
`templates/item.html.j2:311-373` renders the rows with `row.glyph` **as text**
(`:360`) — "it emits no input that writes"; and
`templates/taskpane/taskpane.js` "fetches nothing and writes nothing" (its own
header comment, `:1-14`) — it toggles, switches tabs, and greys. §8 of
`thread-workbench.md` records W5a **Landed** and W5b **Not started**
(`docs/design/thread-workbench.md:282-289`).

**One write path, and its shape.** `serve/edit.py` is the single mutation entry
point the permission seam demanded (`src/refdes/serve/edit.py:1-62`; the seam
is `docs/design/browser-editor.md:996-1017`), and it is a value-returning one:
`Applied` `:157`, `Conflict` `:177`, `Refused` `:204`, `Invalid` `:220` (each
cited at its `class` line). Its
order is: per-project write lock → side-effect-free load → revision compare
(`Conflict`, never a merge) → sealed-item refusal → patcher plan → delta
diagnostic gate → atomic write with read-back. `EditRequest` carries
`expected_revision`, the content revision of the target **file** (`:131-150`,
`file_revision` `:269`). Cross-process safety comes from `_disk_write_lock`
(`:281`), which is the same `write_lock.project_write_lock` the CLI wraps its
commands in.

**Creation, including appending to an existing thread file.**
`edit.create_item()` (`src/refdes/serve/edit.py:1058`) mints a key, reserves an
id, and writes — under the same lock, with the same refuse-as-a-value posture.
`_resolve_destination` (`:1289-1330`) admits exactly three shapes:
**append-yaml** (an existing list file), **append-md** (an existing
multi-item Markdown file), and **new-md**. The append shapes read the
destination's own `defaults:` so the id series and inherited fields are the
file's to decide (`:1297-1303`); `ids.reserve_id` runs inside the lock
(`:1212`) and `Created` reports the reserved id and minted key (`:1040-1055`).
Links at creation are spelled server-side by `links.composite_for`, called in
`_amends_line` (`:1427`) and `_link_target` (`:1455`) — the request names
targets, the composite on disk is never taken from the client.
`serve/api.py:651-700` is that path's HTTP face (`POST /api/items/create`), and
it refuses outright on a `--no-write` server (`:655-659`, wired from
`src/refdes/cli.py:460`).

**The draft mechanism, already built for the editor.**
`src/refdes/serve/static/drafts.js` is exactly the design's
"Drafts: what the editor holds before it saves" (`docs/design/browser-editor.md:785-805`):
live copy in the page's memory (`memory`, `:8`), a `sessionStorage` mirror keyed
`refdes.draft.v1.<handle>` that survives a tab reload and dies with the tab
(`:7-18`, `:38-45`), `isDirty` (`:52-59`), `clearDraft` (`:121-128`), and the
`beforeunload` prompt (`:132-136`). The save side is `editor.js`: one POST per
dirty part with the file revision the form opened on (`:234-236`) and the
three-outcome conflict screen — keep mine / keep theirs / copy it out
(`:295-320`). The mechanism is real; its draft shape is
`{revision, fields, body, pins, links}` — per item, scalars only.

**The serve-only seam for anything that writes.** `serve/server.py:_decorate`
(`:738-776`) injects the preview toolbar and `_reload_probe` (`:62-73`) into the
HTTP response only — "It is never written into the rendered files (Option A's
boundary): a published `_site/` has no edit affordance at all" (`:740-741`).
W2's `_decorate_images` (`:83`) and the calc-value toggle work the same way.
Every `/api/` call requires the launch token in `X-Refdes-Token`, reads too
(`:782-783`), and every POST additionally requires a matching `Origin`
(`:785-787`); the preview CSP's `default-src 'self'` and `script-src 'self'`
(`src/refdes/serve/security.py:86-88`) mean a write-capable script can only be a
packaged same-origin module.

**Capture at the `follows:` edge, and the diagnostic it feeds.**
`links.anchor_follows()` (`src/refdes/links.py:770-815`) is the writable-load
capture point decided in `living-notes.md` §2 (`:179-207`): it rewrites bare
edges and writes the predecessor's `followed` event through
`history.capture_followed()` (`src/refdes/history.py:552`) in one pass, rolling
the edges back if the event write fails (`:803-812`). It is reached from
`loader.load_tree()` at `src/refdes/loader.py:143` with the load's own `write`
flag. The history digest covers an item's own declared payload — type, fields,
raw links, collapsed body (`history.semantic_payload`, `:161-179`;
`semantic_digest`, `:194`) — and the allow-and-detect policy of §3 is enforced
as `captured_edits` (`src/refdes/lifecycle.py:724`, off by default at
`src/refdes/model.py:113`) with `build.warn_uncaptured_edits()`
(`src/refdes/build.py:3260`) beside it.

### Does not exist

**A way to write `tasks:` through the editor.** `tasks` is in
`NON_SCALAR_FIELD_TYPES` (`src/refdes/model.py:198-200`), so the editor model
marks the field `"not a scalar value: collections are not editable here"`
(`src/refdes/serve/api.py:213`), `set_field` refuses a collection outright
(`:508`), and the patcher's `SetField` is documented as "one direct scalar
field" (`src/refdes/patcher.py:127-132`). Creation is no better: `_item_lines`
emits initial fields through `patcher._emit_scalar`
(`src/refdes/serve/edit.py:1533-1551`). What `src/refdes/build.py:339-341`
does say is about a different keystroke: a non-list `tasks:` (scalar or
mapping) "is the loader's error — `_reject_scalar_collection` owns that
keystroke (`tasks` is in `NON_SCALAR_FIELD_TYPES`)" — the loader's
`parse._reject_scalar_collection` (`src/refdes/parse.py:741`) is the one that
reports that malformed shape, and the build's per-row task diagnostics skip
non-lists (`:342-343`). The comment says nothing about the editor; the gap is
what the three sites above show. **Verified by reading those three sites;
W5b's core addition is the operation that closes this gap.**

**`refdes continue`, or any CLI continuation.** `refdes --help` lists
`serve, build, check, revision, release, index, ls, thread, work, id, fetch,
audit, init, new, schema, standard, keys, rename, calc-rewrite, stub-tests,
former-ids, history`. `refdes new` "print a starter item for one type to
stdout"; `refdes id` "allocate IDs for items that have none". No command
appends a thread entry. Hand-authoring the YAML is the only continuation today.

**A conflict check on creation.** `CreateRequest` has no `expected_revision`
(`src/refdes/serve/edit.py:1013-1038`); creation takes the locks and plans
against the state it is about to commit, but it cannot say "this is the tip I
was looking at". The tip-moving-mid-draft question (Q3) is therefore not a
policy question for the create path — the mechanism it would need is missing.

**A `followed` event from a save.** `serve/edit.py` loads with `write=False`
(`:340`), and no module under `src/refdes/serve/` calls
`history.capture_followed` or `links.anchor_follows` (checked by grep over
`src/refdes/serve/*.py`; the `capture` hits there are `upload.py`'s unrelated
"would capture a bare-name reference" lint). So a continuation written by the
editor captures its predecessor on the **next writable load**, not at save
time. That is a real gap against `living-notes.md` §2's "one transaction:
neither the successor nor the event survives a partial write" (`:185-188`), and
Q2 asks what to do about it.

## 3. The one-paragraph shape of the work

The client holds **intent**, never a list: a set of `{task id, wanted state}`
pairs against one named tip, plus the revision it saw. The **server** owns the
complete list — it re-runs `chains.fold_tasks` under the write lock, copies the
tip, applies the ticks to the copy, and refuses anything its own fold says is
`ambiguous`, `undeclared`, or `cleared` when the tick implies a list. The
continuation is written by the creation machinery as it stands today
(append-yaml / append-md into the thread's own file, id reserved under the
lock, `follows:` spelled by `links.composite_for`), reported through the
existing `Applied/Conflict/Refused/Invalid` shape, and reaches the browser
through the same token-and-Origin API every other mutation already uses. The
tick-capable pane is a **serve response decoration**, never bytes in the
generation, so §7a.6 holds by construction rather than by review. The draft
lives where the editor's drafts already live.

## 4. Phases

Each is independently shippable and independently verifiable. Q-numbers refer to
§6.

### W5b.1 — the continuation apply-operation, with no UI

**Adds.** One operation that takes `(thread ref, {task id → wanted state},
expected revision)` and returns one of the existing four result values: take
`write_lock_for` and `_disk_write_lock`, re-fold with `chains.fold_tasks`,
refuse postures that carry no list, copy the tip entry's own declared payload,
apply the ticks to the copy, plan the append with the patcher, run the delta
diagnostic gate, and write. No HTTP route, no template, no JS.

**Files.** `src/refdes/serve/edit.py` (the operation, beside `apply_edit` and
`create_item`, sharing their locks); new `tests/test_serve_continue.py`.

**Verified against.** The complete-list invariant: the written entry carries a
whole `tasks:` list, every untouched row preserved verbatim (id, text, state),
and the tip entry's bytes unchanged. Refusals: `ambiguous` / `undeclared` /
`cleared` folds; an unknown task id; a wanted state outside `TASK_STATES`; a
second tick for the same id; a sealed target. Id/key: the new entry's id comes
from the destination file's own `defaults.prefix` series, reserved under the
lock (the same proof `tests/test_serve_create.py` makes for creation).
`follows:` lands as the composite, never the client's text. `--no-write`
refuses.

**Deliberately does not do.** No endpoint, no pane change, no CLI, no capture
event (those are Q2's and W5b.5's).

Gates on: nothing. Startable now.

### W5b.2 — the endpoint, and the permission seam's three rules

**Adds.** `POST /api/item/<ref>/continue` in `serve/api.py:41`'s dispatcher,
mapping the four results to statuses exactly as `_apply_edit` and `_create_item`
do. Nothing else: the token check and `Origin` check are already at
`serve/server.py:782-787` and cover `/api/` by path prefix, and the operation
carries `who` like every other request.

**Files.** `src/refdes/serve/api.py`; `tests/test_serve_api.py` (or a new
`tests/test_serve_continue_http.py`, matching `test_serve_edit_http.py`'s split).

**Verified against.** No token → 403; wrong `Origin` → 403; a refusal is a
status + a message + "nothing changed", never a 500; `--no-write` → 403 naming
the reason; a request that lies about the revision → `Conflict` with the current
list, and no write.

**Deliberately does not do.** No new CSP allowance, no new content type, no
body-cap change, no read API (the pane's data is already server-rendered).

Gates on: Q2 (endpoint vs. reuse of `/edit/`), Q10 (whether the CLI is expected
to reach the same operation before it ships).

### W5b.3 — ticks in the pane, serve response only

**Adds.** In `task_pane.py`, one flag on the pane model —
`interactive` — and the row's checkbox markup behind it; in
`serve/server.py:_decorate`, the response-only injection of the write-capable
module (the `_reload_probe` pattern, `:62-73`) so only preview pages get it.
`taskpane.js` stays a show/hide/tab script; the tick state is a second, separate
module. The site keeps the read-only glyph and the read-only toggle exactly as
W5a shipped them.

**Files.** `src/refdes/task_pane.py`, `src/refdes/templates/item.html.j2`,
`src/refdes/templates/taskpane/taskpane.css`, a new
`src/refdes/serve/static/taskpane-ticks.js`, `src/refdes/serve/server.py`;
`tests/test_threads_render.py`, `tests/test_serve_preview_decorations.py`,
`tests/test_serve_static.py`.

**Verified against.** **§7a.6 by test, not by review:** a `refdes build` of a
project with a threaded log emits no checkbox, no tick module, no token and no
write route into the generation — asserted against the built tree, in the spirit
of `docs/design/browser-editor.md:1227` ("`_site/` built without `serve`
contains no editor UI, token, or write route"); the same project under `serve`
gets the checkboxes in the **response** while the file on disk in the preview
generation is byte-identical to what `build` wrote. Plus: a checkbox is a real
`<input>` with a label and no inline handler (the module rules
`tests/test_serve_static.py:33-47` enforce), and derived rows still render no
glyph and no control at all.

**Deliberately does not do.** No save, no draft, no call to the W5b.2
endpoint (that is W5b.4), no list assembled in the browser (R1), no control
on derived rows, no change to what `refdes build` writes (R3).

Gates on: Q9 (confirm the site's pane is untouched), Q6 (which states are
tickable), Q4 (which list the checkboxes belong to).

### W5b.4 — the draft's identity and lifetime, and the save

**Adds.** The tick draft in the page, keyed by **tip** rather than item handle —
reusing `drafts.js`'s persistence rules, not its draft shape — plus the
unsaved indicator, discard, and the `beforeunload` prompt. The save button posts
the W5b.2 request with the revision the pane was rendered at.

**Files.** `src/refdes/serve/static/drafts.js` (a second, sibling draft kind),
a new pane-tick module, `src/refdes/templates/taskpane/taskpane.js` or its
write-capable sibling; the same test files as W5b.3.

**Verified against.** Reload recovers the draft in the same tab; closing the tab
discards it; a second tab on the same tip sees its own draft (never a shared
one); a second tab on a **different** tip of a forked thread keeps a separate
draft (the tab rule of §7a.3); a save after the file moved returns `Conflict`,
shows the current tip's list against the ticks, and offers the three outcomes
the design already commits to — keep mine, keep theirs, copy it out — and
nothing that merges.

**Deliberately does not do.** No new endpoint (W5b.2's), no server-side draft
file (Q1's (c) — R4's named temptation), no rebase of ticks onto a moved tip
(Q3's (b) is refused), no `followed` event written by the save (W5b.5's, per
Q2).

Gates on: Q1 (where the draft lives), Q3 (tip moved), Q5 (drafts and tips), Q8
(discard/undo/indicator).

### W5b.5 — the capture moment, and CLI parity

**Adds.** Only what Q2 and Q10 ask for: the `followed` event written by the
same operation that writes the entry (or an explicit statement that the next
writable load does it, per the current mechanism), and/or a CLI route to the
same operation.

**Files.** `src/refdes/serve/edit.py` and/or `src/refdes/cli.py`;
`tests/test_history_capture.py`, `tests/test_thread_cli.py`, a new
`tests/test_cli_continue.py` if the CLI half lands.

**Verified against.** If the save captures: one save writes entry + event or
neither, and the announcement line prints exactly once (the rule at
`living-notes.md:204-207`). If the CLI lands: it reaches the same function as
the endpoint, not a second implementation, and its refusal text is the same
values rendered as exit codes.

**Deliberately does not do.** No new endpoint, no pane change, no change to
the capture model beyond what Q2/Q7 answer, no interactive CLI (Q10's (c) is
a TUI, explicitly not this).

Gates on: Q2, Q7, Q10.

## 5. Risks

**R1 — a second fold.** The pane computing "the new list" client-side would be
a second authority over the fold, and the disagreement between it and
`chains.fold_tasks` is the silent-wrong class this project keeps finding
(the same reasoning `browser-editor.md:818-822` gives for refusing to merge).
Phase W5b.1 puts the list-building on the server for exactly this reason; treat
any patch that builds a list in JS as a bug report.

**R2 — writing the tick into the tip.** A convenience save that mutates the tip
in place would break `§7a.2` and, once the tip has been captured, would trip
`captured_edits` (`lifecycle.py:724`) with an edit the author never meant to
make. W5b.1's "tip entry's bytes unchanged" test is the guard.

**R3 — the checkbox leaking into the generation.** §7a.6 and
`browser-editor.md:21-24` are the same rule as W5a's `taskpane.js` header: the
site's pane is read-only. W5b.3's byte-identical-on-disk test is the guard; a
green review without it is not a pass.

**R4 — a draft that outlives the model.** `sessionStorage` is per-tab and
per-origin, and `serve` binds an ephemeral port by default
(`docs/design/browser-editor.md:955`; `serve --help`: "ephemeral by default,
`--port` to pin one"), so a plain *restart of `serve`* lands on a new port —
a new origin — and the draft is gone. Since #210 the pinned case is different:
with `--port`, a relaunch reclaims its own port (commit `8b6a52e`), the origin
is unchanged, and the draft can survive the restart. W5b.4 must not paper over
the unpinned case with a server-side draft file — that would be the "second,
worse autosave next to git" the design refuses (`:804-805`) — and Q1 asks
whether the owner accepts that loss.

**R5 — the id ledger and the file, twice.** A continuation reserves an id and
writes a file. `create_item` already commits or rolls back both together; W5b.1
must reuse it rather than re-implement the pairing, or a refused save can burn
an id.

## 6. Open questions for Jared

Each has options, the trade-off, and the conservative default this plan assumes
until told otherwise. Nothing here contradicts a §7a decision.

**Q1 — where does the tick draft live, and what survives what?**
(a) page memory only. (b) page memory + `sessionStorage`, i.e. `drafts.js`'s
rules (`:7-18`, `:132-136`) with a new draft kind keyed by tip. (c) a
server-side draft file under `.refdes/`. (d) the editor's existing draft
mechanism as it stands.
*(d) is not really an option: the existing draft shape is
`{revision, fields, body, pins, links}` per item handle — no task rows, and not
keyed by tip. It is listed to record why.*
**Trade-offs.** (a) is the smallest and most honest — a reload losing ten ticks
is annoying and recoverable. (b) costs one `sessionStorage` key and buys reload
survival, and it matches what the editor already promises the same author; it
dies on tab close, and its `serve`-restart behavior splits: unpinned, the next
launch binds a new ephemeral port — new origin, draft gone; pinned with
`--port`, a relaunch reclaims the same port and the draft can survive (R4).
(c) is the only one that survives a browser restart, and it is a new piece of
project-owned state that `thread-workbench.md` §9's "no new storage" rule was
written against.
**Conservative default: (b)** — same lifetime promise as the editor's drafts,
nothing new on disk. Reload survives; an unpinned `serve` restart kills the
draft, a pinned-port restart can keep it; a second tab has its own draft and
never a merged one.

**Q2 — what exactly does save write, and through what door?**
Concretely: a new entry appended to the thread's own file, by the creation
mechanism (`append-yaml` / `append-md`, `edit.py:1289-1330`), with `follows:`
naming the tip as a `DISPLAY-ID@key` composite, an id reserved from the
destination file's `defaults.prefix` series, and `tasks:` the tip's whole list
with ticked rows `done`. **Which fields are copied** is the live question:
(a) the tip's own declared fields verbatim minus identity (`id`, `key`) and
minus `follows:` — the same exclusion list the history payload's identity split
implies (`history.object_payload`, `:204-211`) — so `board`, `author`, `date`,
`summary` and friends carry over; or (b) copy nothing but `tasks:` and `follows:`,
forcing the author to fill a form. (a) matches "copied-and-updated list" and
the `defaults:` inheritance the append shape already does; (b) is more explicit
and turns a tick into a form-filling chore, which is the friction §7a exists to
remove. **What the body says:** (i) empty body; (ii) a generated one-line stub
naming the ticks; (iii) the tip's body carried forward. **Default: (a) + (i)** —
copy the declared fields, leave the body empty: an invented body is a sentence
the tool wrote into an append-only entry, and an entry is exactly where that
costs the most.
**The door.** (i) reuse `POST /api/item/<ref>/edit` — impossible as the code
stands, since `tasks:` is a collection (`api.py:508`) and the op writes a field
of an existing item rather than a new entry; (ii) reuse
`POST /api/items/create` — it already appends and mints, but its body shape is
`{type, fields, destination, amends, links}` with scalar fields only
(`:651-700`), so it needs the same new field handling; (iii) one new endpoint,
`POST /api/item/<ref>/continue`, riding the same token + `Origin` checks
(`server.py:782-787`) and the same `Applied/Conflict/Refused/Invalid` mapping.
**Default: (iii)**, because the permission seam's price is "one entry point
applies every mutation" (`browser-editor.md:1007-1009`) — which is about
`serve/edit.py`, not about the URL — and a named operation whose request is
"these ticks at this tip" is honest about its transaction, whereas stretching
`set_field` to write a list of maps would widen the most-used op for one
caller. **Sub-question, and it is not cosmetic:** does the save also write the
predecessor's `followed` event? Today it does not (§2, "a `followed` event from
a save"). `living-notes.md:185-188` asks for entry + event in one transaction.
(a) W5b.5 writes both from the one locked operation; (b) leave it to the next
writable load. **Default: (a)** — (b) leaves a window where the newest entry is
live and its predecessor un-captured, which is the state
`uncaptured_edits` (`history.py:760`) exists to diagnose.

**Q3 — the tip moves while a draft is open** (another tab, VS Code, a CLI
write, another author).
(a) refuse the save and show the current tip's list against the pending ticks,
offering keep-mine / keep-theirs / copy-it-out — the editor's existing contract
(`browser-editor.md:810-822`, `editor.js:295-320`). (b) rebase the ticks onto
the new tip automatically. (c) a three-way compare (list-at-open, draft, current
tip).
**Trade-offs.** (b) is exactly the automatic merge the design refuses, and for
the same reason: a merged task list "parses cleanly and means something neither
author wrote". (c) is the honest shape of what actually happened — task lists
*are* the three-way case, not a scalar field — but it needs a revision token to
put the operation on, which creation does not have today (§2, "a conflict check
on creation"). (a) is available now.
**Conservative default: (a)**, implemented as W5b.1's revision compare, with
(c) — a per-task-row diff rather than a text diff — held as the follow-up if
refusals turn out to be annoying. The pane should also *notice*: the preview
already auto-reloads on revision change (W1's `_reload_probe`,
`server.py:62-73`), so "the list you are ticking is stale" is partly a freshness
problem before it is a conflict problem.

**Q4 — ticks shown on an older entry: the save continues the tip, not that
entry.** §7a.1 puts the tip's list on an older entry's page
("`viewing LOG-007 · tasks as of tip LOG-012`"), and §7a.2's save "appends a
continuation". **This plan assumes confirmed**: the operation names the **tip**,
and an older entry's page saves a successor to the tip, never to the entry the
reader is looking at. The alternative — continuing the older entry — would fork
the thread from the pane, which is a different act (§7a.3's tabs are for tips
that already exist, not for creating one). Only flag it if that is not what you
meant.

**Q5 — forks, tabs, and whose draft is whose.**
(a) a draft belongs to exactly one tip, keyed by that tip's key (not its display
id — `DISPLAY-ID@key` is the identity, and a composite's display half is
refreshed on rename by `links._planned_target`
(`src/refdes/links.py:323`)), and drafts on two tips of one fork coexist in the
same tab; (b) one draft per thread, last-tip-wins; (c) one draft per browser
tab, refusing a second tab on the same thread.
**Trade-offs.** (a) is what §7a.3's "one tab per open tip, never a union"
implies for the write side, and costs one key. (b) silently drops ticks when
you switch tabs — the exact surprise the tab rule was written to avoid. (c) is
safe but hostile.
**Conservative default: (a)**, with the tab-switch UI simply showing each tip's
own pending count.

**Q6 — states beyond `done`: `dropped`, reopening, and un-ticking.**
`TASK_STATES` is `(open, done, dropped)` (`model.py:209`).
(a) the pane offers open→done and open→dropped only, and a `done` row is
read-only; (b) it also offers un-tick (`done`→`open`) and `dropped`→`open`;
(c) full three-way cycling.
**Trade-offs.** (a) keeps the pane's verbs to "the author decided this is
finished / not happening" and avoids the pane claiming to *undo* history — but
mis-ticks happen, and under (a) an un-tick means a second entry that says
"actually not done", which is noise in an append-only record. (b) is cheap here
specifically because the model is a complete-list snapshot: the previous state
is not a delta to reverse, it is just the row's prior value, and the *entries*
are still append-only even when a row's state moves backwards. (c) adds nothing
over (b).
**Conservative default: (b)** — un-ticking a row in the *draft* is free (the
draft is not history; nothing is on disk yet), and writing an entry that flips a
row back to `open` is a true record of the author's current judgment. Flagging
this one as *not obviously conservative in either direction*: if you want (a),
say so and W5b.1 refuses a wanted-state change on a row that is not `open`.

**Q7 — captured / recorded entries: is there any interaction?**
**Assumed: none, and this is a request to confirm the reasoning rather than the
conclusion.** The check: `history.semantic_payload` digests an item's *own*
declared payload — type, fields, raw links, collapsed body (`:161-179`) — and
`uncaptured_edits` / `captured_edits` compare that against what was captured
(`history.py:760-800`, `lifecycle.py:724`). A W5b save never touches the tip's
bytes (R2), and appending a sibling entry to the same **file** does not change
an earlier entry's payload, because the digest is per item and the payload
carries no file-level state. So ticking neither creates nor clears a
captured-edit marker. The one thing that *does* interact is the save's own
predecessor: it becomes captured by the `follows:` edge (Q2's sub-question),
which is the design working, not a side effect. `living-notes.md` §3's
allow-and-detect policy (`:267-284`) is unaffected either way. If you read
§3 as intending a marker for "the thread's task state moved", that is a design
change, not a W5b implementation detail, and it should be said out loud.

**Q8 — discard, undo, and what an unsaved draft looks like.**
(a) the editor's rules verbatim: an "unsaved" badge, an enabled Save only when
dirty, Discard, and the generic `beforeunload` prompt (`drafts.js:132-136`,
`editor.js:77-81`); (b) the same plus an in-pane per-tick undo (Ctrl+Z is not
the same thing); (c) autosave-with-undo into a draft the server knows about.
**Conservative default: (a)** with one addition worth naming: the pane's header
shows the pending count ("3 unsaved ticks"), because the pane is floating over a
document and a badge the size of the editor's is easy to miss. (c) is (Q1)'s
option (c) by another route and inherits its objection.

**Q9 — the static site, forever read-only.**
**Assumed: confirmed and enforced by test, not by review.** §7a.6 and the rule
at `browser-editor.md:21-24` are the constraint; W5a's `taskpane.js` already
ships "fetches nothing and writes nothing". W5b keeps the write-capable pane
out of the generation by construction — the checkbox and its module arrive in
`serve`'s HTTP response, the way the toolbar and the reload probe already do
(`server.py:740-741`) — and the test asserts the *built tree* has no checkbox,
no tick module, no token and no write route (W5b.3). Nothing to decide unless
the intent is actually "the site's pane grows a control of some kind", which
this plan reads as forbidden.

**Q10 — CLI parity: is there a `refdes continue`?**
The rule is semantic reachability: `refdes --help` today has `thread` and `work`
(the pane's read half, both landed) and no write counterpart — `new` prints to
stdout, `id` only allocates (§2). So the pane's one write verb exists *only* in
the browser, which is the state parity was written against.
(a) no CLI in W5b — the pane is the feature, hand-editing the YAML stays the
parity answer ("that is the honest description of what it is",
`living-notes.md:418-420`); (b) a `refdes continue <ref> --done T-x --dropped
T-y` that calls the same W5b.1 operation and prints the same refusal values as
exit codes; (c) something bigger (`refdes continue --interactive`), which is a
TUI and not this.
**Trade-offs.** (a) ships the pane sooner and keeps the CLI surface small, but
leaves a decided capability with exactly one way to reach it — and no scripted
way, so CI cannot exercise it. (b) is small *if* W5b.1's operation is the real
entry point rather than an endpoint-only helper, which is the reason to design
it that way from the start. **Conservative default: (a) for W5b, with W5b.1
shaped so (b) is a thin `cli.py` addition** — that way choosing (b) later is
one commit, and choosing it now costs one phase. If you want (b) in W5b, that is
a scope change, not a redesign.

## 7. Not in W5b

- No change to the fold, `tasks:`'s schema, or `on_change: timeline`.
- No derived-row ticking or editing: derived rows are self-closing and carry
  no author-settable state (§7a.4, `living-notes.md` §5 rule 2), and are
  never written back into `tasks:` (rule 1, `living-notes.md:461-464`).
- No merge of a forked thread, and no creating a fork or a merge from the pane.
- No automatic merging of task lists from two writers, ever (Q3, and
  `browser-editor.md:818-822`).
- No multi-item pages: §7a's scroll-following and greying rules stay gated on
  the multi-anchor page shape that does not exist
  (`docs/design/thread-workbench.md:220-229`'s W5a status note).
- No change to what the published site renders, beyond W5a's read-only pane.
- No captured-edit / `uncaptured_edits` behavior change (Q7).
- No `tasks:` on any type but the merged `log`, and no second task vocabulary.
- No autosave to disk, no draft file, no autosave into the source.
- No accounts, roles, or per-item permissions; the launch token stays "a request
  came from this browser" (`browser-editor.md:996-1017`).
- No new endpoint that writes anything other than one continuation entry.

## 8. What this plan does not decide

Nothing in `docs/design/thread-workbench.md` §§1–9 or
`docs/design/living-notes.md` §§1–9, and no §7a sub-decision. It does not
decide Q1–Q10 either: it assumes defaults and says which phase each answer
gates. The map, from each phase's "Gates on" line:

| Answer | Phases it gates |
|---|---|
| Q1 | W5b.4 |
| Q2 | W5b.2, W5b.5 |
| Q3 | W5b.4 |
| Q4 | W5b.3 |
| Q5 | W5b.4 |
| Q6 | W5b.3 |
| Q7 | W5b.5 |
| Q8 | W5b.4 |
| Q9 | W5b.3 |
| Q10 | W5b.2, W5b.5 |

W5b.1 gates on nothing. If an answer lands, the phases it gates are the
things that change. Most answers move exactly one phase; **Q2 and Q10 each
gate two** (W5b.2 and W5b.5), and **Q6 reaches into W5b.1 too**: its (a)
option makes W5b.1 refuse a wanted-state change on a row that is not `open`
(Q6's flag), so answering (a) reopens the phase that gates on nothing.
