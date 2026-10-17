# User-simulation release gate — run 8b (885e9e6..f33efa4 serve/editor delta as an author)

Scope per `.scratch/task/TASK.txt`: the serve/editor/workbench/patcher fixes in
`git log --oneline 885e9e6..HEAD | grep -iE 'serve|editor|workbench|patcher'`
— #267, #265, #264, #256, #260, #249, #254, #248 — exercised as an author
against live `refdes serve` + curl (no browser), plus an author pass through
the JSON API. HEAD tested: `f33efa4`. Reported version: `refdes 0.5.0`.

**Method:** each PR's own claim read from `gh pr view N` first, then
reproduced in a fresh `.scratch/run8b/` project (`refdes init`, hardware@3),
then pushed one adjacent spelling past it. Servers: `refdes serve --no-open
--port <p> --token-file <f>` (launch URL read from the owner-only token file,
`X-Refdes-Token` header, writes also carried `Origin: http://127.0.0.1:<p>`),
launched detached with recorded PIDs, each killed by PID at the end. Pure-UI
claims are checked in the *served* JS/CSS and in the repo's own node harness;
where a click-through cannot be driven headlessly this report says
**CAN'T VERIFY IN A BROWSER** instead of claiming it. Nothing under `src/`,
`tests/`, `docs/` was modified; report only, per the task.

Severity levels as in run 6a/7: B = bug, F = friction/nit. IDs continue the
series (run 7 closed at B9/F16).

Two numbering notes on the task's expected list, verified against the log:
the undo fix is **#249** (`44ddf7e`, the task calls it #254) and the patcher
`remove_link` fix is **#254** (`e31e26b`, the task calls it #261) — #254 is
serve-facing (it lands through `POST /api/item/<ref>/edit`) and is in scope.
Commit `8c647e7`'s truncated title reads `(#260)`; it is PR **#264**
(`gh pr view 264` confirms; #260 is the sealed-upload PR).

---

## 0. Headline summary

All eight fixes landed as advertised. Every server-side half was reproduced
live over HTTP on a fresh project and behaves as the PR claims, with the
diagnostics quoted verbatim below: #265's writes apply under `-c` (edit,
create, *and* the poller reloads on the custom config), #256's preview
narrows by workspace and create lands where the preview promised (ghost
workspace: 422 naming the registry), #260's three sealed upload refusals
carry one core row shape (live-probed on all three branches + the mixed
referrer set), #254's comment guard refuses the flow-entry delete that used
to eat `# keep me` — and also covers the block-sequence spelling the PR
didn't list. The three JS-only seams (#267 picker, #264 preview sequence
counter, #249 undo-cancel) ship in the served modules, the repo's node
harnesses drive the real files and pass (17/17 scoped, plus 50 task-pane),
the full suite is green at `f33efa4` (3947 passed, 2 skipped) — but the
click-throughs themselves are CAN'T VERIFY IN A BROWSER.

No new bugs. Three rows for the table: **F17** (low) — `POST /api/items/create`
with a *registered* workspace that has no item files lands the item in
*another* workspace's file inheriting its id prefix, the form's Workspace
select silently unkept by the "empty set falls back" rule; **F18** (nit) —
#260's refusals are unreachable on the plain hardware@3 vocabulary (its `log`
is `sealing: history`), the whole sealed-upload surface is opt-in; **F19**
(nit) — every editor save writes composite `ID@key` link text to disk
(design, but the first surprise an author gets).

---

## 1. The delta, swept as an author

All HTTP against live `refdes serve` (ports 8751/8752/8754/8755, PIDs
recorded, killed by PID; token files per launch, none reproduced here).
Probe project `proj`: `refdes init` (hardware@3) + `boards: power` +
`workspaces: platform/product-a/product-b` + REQ-PWR-001/002, LOG-PWR-001/002
(one with a multiline flow `blocked_by: [REQ-PWR-002  # keep me]`).

### 1.1 #267 — empty `target_types` offers all candidates, as the server accepts

`GET /api/item/LOG-PWR-002` reports the standard's own unrestricted verb
exactly as the PR's live proof describes:
`"blocked_by": {"editable": true, "target_types": [], "targets": ["REQ-PWR-002"]}`,
and the server accepts anything for it: `POST .../edit add_link blocked_by
LOG-PWR-001` (log→log) → 200 applied. Served `links.js` carries the fix:
`PICKER_LIMIT = 5000` used on **every** picker query
(`/api/items?limit=${PICKER_LIMIT}`, per-type queries keep their filters),
empty list → `[base]` unfiltered fetch, `isSelf` exclusion, and the honest
capped notice `showing the first ${offered} of ${pickable} targets -- the
filter searches only these`. Server bound matches the constant:
`?limit=5000` → 200, `?limit=5001` → 400 `limit must be between 1 and 5000`.
Second run on the same verb: duplicate `add_link` → 422 `item LOG-PWR-002
already links REQ-PWR-002@thsds32zs1t`. The picker rendering itself is
CAN'T VERIFY IN A BROWSER; `tests/test_editor_empty_link_target_types.py`
drives the real served modules and passes.

### 1.2 #265 — editor writes honor the `-c` custom config path

`proj-c` = proj with the config renamed `custom-project.yaml`;
`refdes -c custom-project.yaml check` exit 0; server launched the same way
(port 8754). The pre-fix shape was every write a 422 `FileNotFoundError`;
live now: `POST /api/item/REQ-PWR-001/edit set_field` → 200
`kind:"applied"`, the title change on disk; `POST /api/items/create` → 200
`created: REQ-PWR-003` (disk confirmed). Pushing on the *watcher* half of
the PR: a semantic edit appended to `custom-project.yaml` (a new registry
entry) is picked up by the poller — `/api/create/schema` shows it ~4 s later,
so the loaded config is in the watched set. The threading is visible at
`api.py:546` (`config_path=app.state.config_path`). Adjacent spelling —
the default-marker path is the untouched control (every write in §2 ran on
the plain project at 8751).

### 1.3 #264 — a superseded create-preview response never writes the form

JS-only seam; no server surface to break. The served `create.js` carries the
form-scoped counter (`let previewSeq = 0; const seq = ++previewSeq;` and
`if (seq !== previewSeq) return;` on **both** the success and the catch
continuation). The preview route itself is healthy under hammering: the
`?type/&board/&workspace/&id` previews in §1.4 all answered 200 in sequence.
Red/green evidence is the PR's own deferred-resolver harness
(`tests/test_editor_create_preview_sequence.py`, green here). Stale badge /
banner race: CAN'T VERIFY IN A BROWSER.

### 1.4 #256 — the create form picks a workspace, end to end

Server half on `proj-ws` (`item_layout: workspace`, `items/<ws>/power/…`,
port 8752): `/api/create/schema` publishes
`workspaces: ["platform","product-a","product-b"]`;
`?type=requirement&workspace=product-a` → `{"id":"REQ-PA-002",
"destination":"items/product-a/power/requirements.yaml"}` (the *board*
file, `items/power/requirements.yaml`, is the unsugared pick — the parameter
genuinely narrows, and the id follows the narrowed file's prefix);
`board=power&workspace=product-a` → same (intersection); ghost workspace in
preview → 200 with the fallback destination (preview only *suggests*);
`POST /api/items/create` with `fields.workspace: "product-a"` → 200, the
`workspace: product-a` line lands in the previewed file (disk checked);
`workspace: "ghost-x"` → 422 `workspace: 'ghost-x' is not declared in
refdes-project.yaml's workspaces: registry`. The form half ships in
`create.js` (Workspace select from the registry, `(file default)` option with
an explicit `''` value — the pre-existing `"(file default)"` create-killer
this PR also fixed). First attempt on a flat-layout project showed *no*
narrowing — correct, not a regression: with the default `flat` layout no
item carries a path-derived workspace, so every workspace filter is the
empty-set fallback (`docs/workspaces.md` table). **F17** below is the one
author surprise in the fallback.

### 1.5 #260 — the three sealed upload refusals expose one details shape

`proj-rel` — sealed the way hardware@3 allows (F18): overlay
`refdes-schema.yaml` with `types: {log: {sealing: build}}` (the shape
`cli.py:193` documents as the opt-back-in), `release rel1/rel2`, and
`refdes build` (the command with `seal_write=True`, `cli.py:498`) writes
`.refdes/log-seal-power.yaml`. Item view then: `sealed: true`, body
`editable: false` ("a sealed entry is append-only…"). All three refusals
live on `POST /api/assets` (raw bytes, `Content-Type: application/octet-stream`):

- **target** (`?item=<sealed>&name=`) → 422, `refusal: "sealed"`, one row
  `{item, source_file, srcs: [], sealed, why}`;
- **replace** (differs bytes on a referenced file) → 422 naming
  LOG-DBG-001, row `{item, source_file, srcs: ["state.png"], sealed, why}`;
- **capture** (new file where a sealed entry's `missing.png` resolves to
  nothing) → 422, row `{item, source_file, src, srcs, resolves_to: null,
  why, sealed}` — the core with `src`/`resolves_to` **on top**, as the
  contract in `upload.py:170-178` states.

Push — mixed referrer set (sealed LOG-DBG-001 + unsealed REQ-PWR-001 both
reference `state.png`): the refusal discloses **both** rows, every row
carrying the five core keys with `sealed: true/false` doing the branching.
Controls: identical bytes → 200 `identical bytes already at the destination;
nothing was written` (the §5 no-op the PR preserves; hit it by accident
first, my "different" bytes were signature-equal). Served `images.js` reads
`refusal === 'sealed'` and renders `message` only (the PR's consumer
inspection is current). No dialog to click: CAN'T VERIFY IN A BROWSER.

### 1.6 #249 — undo of a pending link op cancels it, it does not flip sides

JS seam: `drafts.js` exports `draftLinkCancel` (`:291`), `links.js` imports
it and routes **both** pending-line undo buttons (`:140`, `:153`) and the
Add-on-a-pending-removed case (`:197`) through it — no flip side exists in
the served code. The server-side half of the PR's story (the sticky bogus
op) reproduced as its control: `POST remove_link satisfies REQ-PWR-001` on
an item with no such link → 422 `item LOG-PWR-001 has no 'satisfies' links
to remove`, tree unchanged — which is exactly why the flip needed to die in
the draft layer. Undo-click sequencing: CAN'T VERIFY IN A BROWSER;
`tests/test_editor_link_undo.py` (node, real served modules) passes.

### 1.7 #254 — `remove_link` refuses to delete a comment inside a multiline flow entry

Live on the flow spelling, as the author writes it: `LOG-PWR-002`'s
`blocked_by: [\n REQ-PWR-002  # keep me\n]` — removing the **last** target
→ 422 `a comment sits on the 'blocked_by' entry of item LOG-PWR-002;
deleting the entry with its last link would destroy it`, bytes untouched.
Controls both directions: the *non-last* target inside the same commented
flow entry removes cleanly (200, comment survives — visible in §2's disk
sequence), and a comment-free flow entry's last target removes the entry
(200). Push — the PR's guard names the flow shape; the **block-sequence**
spelling is the same author mistake:

```yaml
    satisfies:
      - REQ-PWR-001
      - REQ-PWR-002  # keep block me
```

`remove REQ-PWR-002` → 422 `a comment sits on the line holding REQ-PWR-002
in item LOG-PWR-003; removing the entry would destroy it`. Covered. (An
`add_link` into the commented flow entry also preserves the comment — §2.)

### 1.8 #248 — workbench nits (pane-model key set, `.mono` scale, posture count)

`task_pane.pane_for` returns exactly `{ref, forked, tabs, derived,
derived_heading}` — no `viewing` key (`task_pane.py:118-124`); the shipped
`taskpane.css` carries `.refdes-taskpane .mono { font-size: inherit; }`
with the specificity comment; the posture count comment in `threads.py`
reads "three". `tests/test_task_pane.py` + `tests/test_serve_preview_task_pane.py`:
50 passed. How the pane *looks* (mono sizes, posture rendering): CAN'T
VERIFY IN A BROWSER.

---

## 2. Author pass through the API

Create → link → field edit → body edit → save, checking the file after each
step (proj, 8751):

1. `POST /api/items/create` (requirement, `fields.title/rationale`) → 200,
   created in the suggested file. Vocabulary check on a mistake:
   `fields: {body: …}` → 422 `requirement does not declare a field 'body';
   it declares last_reviewed, note, owner, rationale, source, status, tags,
   title` — names the declared set, good author-facing refusal.
2. `POST .../edit add_link satisfies REQ-PWR-002` → 200; disk shows the new
   link written **scalar** (`satisfies: REQ-PWR-002@thsds32zs1t`) next to
   the untouched multiline flow `blocked_by` entry — the comment inside it
   survived (F19 for the `@key` text), insertion appended after the item's
   existing keys, which is what the patcher is for.
3. `POST .../edit set_field title` → 200, one-line change on disk, no
   reflow of the file.
4. `POST .../edit set_body` → 200; disk shows
   `body: "Topology notes: …"` written as a quoted YAML scalar.
5. `POST .../edit remove_link satisfies REQ-PWR-001` against the stored
   composite `REQ-PWR-001@g996w5k7fng` using the **plain display id** →
   200 — the patcher resolves display-id requests against composite text,
   an author never sees the key.
6. The save response's diagnostics stay live after each write (the new
   `blocked_by` link immediately showed up in REQ-PWR-002's coverage
   diagnostic), and the stale-revision guard answers 409/422 shapes per
   §1.6's probe. Nothing surprising beyond F19.

---

## 3. Findings summary

| # | Severity | Finding |
|---|---|---|
| F17 | low | `POST /api/items/create` with a declared workspace that has no item files yet lands the new item in *another* workspace's most-populated file, inheriting that file's id prefix — created `REQ-PA-003` (a "PA" id) for `workspace: product-b`, `path: items/product-a/power/requirements.yaml`. The "empty set → fallback" rule the preview documents is applied silently: the form's Workspace select is honored in the written `workspace:` field but steers the file not at all. Same code path as the board-only fallback (parity, not a regression); surprising for the author who believes the select picked the destination. §1.4 |
| F18 | nit | #260's sealed-upload refusals are unreachable on the plain hardware@3 vocabulary: `log` ships `sealing: history` (`v3/base.yaml:290`) → `is_sealed` is always False (seal.py:417-419), and no other base type is `append_only`. Every §10 refusal needs the opt-in overlay `types: {log: {sealing: build}}` (the shape `cli.py:193` documents). The PR's contract is verified live *with* the overlay; the surface is opt-in. §1.5 |
| F19 | nit | First author surprise on the editor's disk writes: saved links land as composite `REQ-PWR-002@thsds32zs1t` text (surrogate-key design, per `docs/design/keys.md` — plain-id reads/removes resolve against it transparently, §2.5). Not a defect; recorded because it is the first thing a new author asks about. §2 |

No B-row findings: nothing in this delta is broken on the surfaces tested.

---

## Appendix — reproduction

Projects under `.scratch/run8b/` (all `refdes init`, hardware@3):
`proj` (flat, boards `power`, workspaces registry, REQ-PWR-001/002,
LOG-PWR-001/002/003 — the multiline `blocked_by` with `# keep me` and the
block-sequence probe), `proj-ws` (`item_layout: workspace`,
`items/{platform,product-a}/power/requirements.yaml`), `proj-c` (config
renamed, served via `-c`), `proj-rel` (overlay `sealing: build`,
`release rel1`/`rel2`, photo entries referencing `state.png`/`missing.png`).
Servers: `PYTHONPATH=<worktree>/src <author-venv>/bin/python -m refdes.cli
[-c …] serve --no-open --port <p> --token-file <f>`, launched with `setsid`
(a plain backgrounded server shares the shell's process group — the harness's
timeout SIGTERMs it, and a clean SIGTERM deletes the token file: the
observed shape of serve's own documented contract), PIDs recorded and killed
by PID, token contents not reproduced. Writes carried
`X-Refdes-Token: <launch token>` + `Origin: http://127.0.0.1:<p>`.
`refdes release` gates the probe projects once (uncovered_requirements) —
the scratch project's `release_gate:` disables that rule, the documented
knob. Gates run at f33efa4: full suite 3947 passed / 2 skipped (exit 0, no
flake re-run needed), `ruff check --select E9,F src tests` clean,
`docs-site/gen_examples.py --check` up to date.
