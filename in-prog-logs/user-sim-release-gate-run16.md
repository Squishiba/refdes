# User-simulation release gate, run 16

Run date 2026-11-09. Base `9f15af87` (branch `user-sim-run16`, ff-merged
from `origin/main`, includes #463). In-scope: the merged scope
`d9719a9..origin/main` (~60 commits) — the Navis panel in editor and
preview (W5b surfaces, #410, #418), item rows linking to the item view
(#450), the unsaved-draft revision conflict (#429), the preview task-pane
ticks (#456) and unsaved-tick draft (#463), `POST /api/item/<ref>/continue`
(#453), `refdes fetch`'s pruned-values report (#449), the VS Code tree
claims (docs only), the 0.5.0→current upgrade path (`docs/upgrading.md`
followed verbatim), and the README test command.

Driven as a user: real Chromium (puppeteer-core) and real Firefox
(playwright-core) against `refdes serve --port 8760` (writable) and
`--no-write --port 8761` on a scratch multi-board project (18 items,
forked design-log thread with two tips, keyless/id-less markers, a
calc fence, a CSV citation with `source()` spans); CLI directly; curl for
the documented API shapes; a real `refdes` 0.5.0 wheel (PyPI) + its
`init`-built project for the upgrade. Evidence under
`in-prog-logs/user-sim-run16-evidence/`.

## Findings

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| F16-1 | Medium | navis / docs | navis markers in the body of an item that has no `id:` are invisible to every `refdes navis` verb, the `navis` key of `refdes index`, and both panels — the docs promise the scan reads every body, and the docs' own "write bodies, `refdes id` later" flow lands there. Reproduced identically at base `d9719a9`: **not a regression**, shipped before this scope |
| F16-2 | Medium | task pane / continue endpoint | an id-less thread tip is refused by `/api/item/<ref>/continue` (" carries no artifact key" — note the empty subject) while the pane hands the browser exactly the save context (`data-refdes-tip-key` + revision) for that tip; no shipped doc says a tip needs an `id:` |
| F16-3 | Low (Unconfirmed) | task pane / Firefox | a Firefox "tick double-step" observed mid-run **did not reproduce** on a clean re-run with plain `page.click` on the input: Firefox and Chromium are identical (checked true/false/true/false; mirror `{T:done}/{ }/{T:done}/{ }`, matching the reviewer's numbers). The original observation was self-inflicted: my continuation-endpoint test had appended a new tip that flipped the row's file state open→done between probe phases, and I read the row's static `data-refdes-task-state` attribute (the file state, never updated by a tick) as the live state — re-filed Unconfirmed, evidence kept |
| F16-4 | Low | docs/upgrading.md | the item-level `history:`→`on_change:` hard error (which the docs' own probe class — a v2 entry sealed via item `history: log` — hits on the first current load) is absent from the step-2 quote and no step performs it, so the docs-ordered `calc-rewrite` (step 4) refuses until an off-menu hand-rename; and the design-debate "declare the four types yourself" remedy needs two more renames inside the copied overlay (`on_change: log`→`timeline`, `resolved_by: [decision]`→`[log]`) |
| F16-5 | Cosmetic | navis / task pane CLI-render | id-less items render with an empty id column in `navis ls`/mint announcements and as an empty-text anchor row in the preview Navis panel |
| F16-6 | Cosmetic | docs/cli-reference.md | the serve section still describes the task pane as computing and writing nothing with no control on it; the pane now ships preview-only tick checkboxes, a per-tab draft, Discard, and a leave prompt (only the changelog fragments say so) |

## F16-1 — navis markers in id-less items are invisible

`docs/navis.md` §how-it-works: the scan "reads every body";
`docs/getting-started.md` teaches writing bodies first and running
`refdes id` later. Between those two steps a marker in an id-less item
is silently unlisted: `refdes navis ls`/`all`/`show` never name it,
`refdes index`'s `navis` key omits it, and neither panel shows the row —
while a marker in the *same file's* id-bearing items lists fine. The
mechanism is the load-block: an item with no `id:` is excluded from the
scan set. Minting works (the marker's key is minted when an id-less
item's file is edited by a writable command), so the state is reachable
and permanent until `refdes id` runs.

Verified at base: extracted `d9719a9` via `git archive`, same project,
same silent skip → pre-existing, in-scope only as a docs-promise gap.
The CLI prints a row with an empty id column for id-less items (F16-5),
so the listing *shape* acknowledges them; only the marker scan drops
them.

## F16-2 — continuation refused at an id-less tip; pane gate is key-only

The pane's save-context gate is "a tip with no key … names no context"
(server docstring, `serve/server.py:_pane_save_context`), so an id-less
tip *with* a key gets `data-refdes-tip-key` + `data-refdes-revision`
and the panel reads `viewing LOG-A-005 · tasks as of tip 4jfd3hhpajc`.
The endpoint disagrees:

```
$ curl -X POST -H "X-Refdes-Token: …" -H "Origin: http://127.0.0.1:8760" \
    -d '{"ticks":[["T-open","done"]],"expected_revision":"<current>"}' \
    /api/item/LOG-A-005/continue
422 {"kind":"refused","ok":false,
 "message":"refused:  carries no artifact key, so no DISPLAY-ID@key
 composite can be written for it; naming the tip with a bare id would
 drop the identity the link is for", …}
```

Three things to fix: the subject slot of the message renders empty
(the item has no display id, so the interpolation yields ""); the
pane→endpoint gate pair is inconsistent (pane names a save the endpoint
refuses — the exact "UI lying" the pane's own comment forbids); and
`changelog.d/continue-endpoint.added.md` — the endpoint's only shipped
doc — promises 200 applied for a well-formed body and never lists an
`id:`-bearing tip among the refusals (it lists forked thread, cleared
list, sealed tip in my runs — all of which fired correctly). Adding the
tip's `id:` made the same request apply in one call
(`continuation LOG-A-008 appended … (1 tick)`, composite
`follows: [LOG-A-007@4jfd3hhpajc]`, ticked-up list, 200; stale revision
then 409 with `current_text`), so the fix is the pane gate (key AND id),
the message label, and a doc line.

## F16-3 — Unconfirmed: "Firefox double-step" was a fixture race of mine

Mid-run I recorded Firefox tick clicks behaving like double-steps
(evidence `r16-ff2.json`, `r16-ff3.json`, `r16-ff4.json` — kept). A
clean re-run on request (`r16-rerun.json`, base `9f15af87`; the tick
files are byte-identical between that base and current `origin/main`
per `git diff`): a two-entry thread, id-bearing tip, one open task
(`data-refdes-tick-states="done,dropped"`), plain `page.click` on the
INPUT, four clicks, file untouched between clicks:

- Chromium: checked true/false/true/false; mirror
  `{4jfd3hhpajc:{T-rerun:"done"}}` / `{}` / same / `{}`.
- Firefox: **identical**, same sequence and mirrors — matching the
  reviewer's independent numbers exactly.

What differed in the original run: my continue-endpoint test had
appended a new tip carrying the ticked-up list, so between probe
phases the row's **file state flipped open→done**. From a done row,
click 1 is an untick — `checked=false` with mirror `{T-open:"open"}` —
which I misread as "stays open"; and I was reading the rows' static
`data-refdes-task-state` attribute, which is the file state rendered
once and never updated by a tick, as if it were the live state. The
live state (checked + mirror + counter) was coherent in every
Firefox observation I re-checked. No double-step reproduces; I found
no browser parity gap. Downgraded to Low/Unconfirmed with the
mechanism of the false positive named: a gate report must freeze the
fixture it ticks (the pane ticks a tip's fold — a continuation between
tick probes silently re-bases every row).

## F16-4 — docs/upgrading.md gaps on the v2 seal path

I built the docs' probe with the real 0.5.0 wheel (`init`, hardware@2,
requirement `text:`, bound `limit:`, test `method:`, decision with a
colon-unit calc, `url:`+`vendor:` citation fetched from a local server,
sealed log — sealed by 0.5.0's `refdes build`, `.refdes/log-seal.yaml` —
baseline stamped by `refdes revision probe-base`), then followed the
page verbatim with the current build. Steps 1, 2, 3, 4, 5, 6, 7 all
reproduced **verbatim** — the `refdes.yaml is retired` block (exit 2),
the three ERROR texts, `minted 7 key(s) and rewrote 2 reference(s)
while loading`, the calc-rewrite plan shape, the v2→v3 file list +
`baselines carried forward` + `upgraded to v3.`, the seal follow-up
warning (hash line differs by content), `captured LOG-PWR-001: manual
capture`, the audit's `(legacy seal: recorded hash only; original
content was not captured)` and `Since last revision (post-upgrade, …):
changed 0`, the `drop_in: CMP-PWR-001@…` composite, the anchored
`follows: [DEC-PWR-001@…]`. Two gaps:

1. My probe's item-level `history: log` (the very 0.5.0 mechanism that
   produces the sealed entry the probe is built around) makes the
   current build red with the `history:`→`on_change:` **hard error**,
   which the docs' step-2 quote does not list and no step performs;
   step 4 (`calc-rewrite`) refuses "project has existing build errors"
   until you rename it by hand. The table (line 176) knows the rename;
   the ordered steps never reach it.
2. The table's debate remedy ("declares the four types itself")
   underestimates the work: copying the 0.5.0 preset into
   `refdes-schema.yaml` leaves the upgrade refusing twice more — first
   `on_change: log`→`timeline` inside the copied overlay, then
   `resolved_by` naming the retired `decision` (must become `[log]`
   by hand). Four iterations of refuse-and-read, not the one the
   remedy implies.

## F16-5 / F16-6 — cosmetic pair

`refdes navis ls` prints id-less items with a blank id column
(`4n9h37  (file)`) and mint announcements print `into  (file)` with the
subject slot empty; the preview Navis panel renders the same item as an
anchor with no text. Harmless, one root cause (display id == "" is
rendered as-is). `docs/cli-reference.md`'s serve section keeps calling
the task pane a read-only display that "computes nothing and writes
nothing" — true of the built site, no longer true of the preview page,
which carries tick checkboxes, a per-tab draft, a live counter,
Discard, and a leave prompt (all of which worked, see below).

## What passed (each driven, not read)

- **Navis panel, editor + preview** (Chromium + Firefox): toggle/Escape
  (the Escape "failures" from an earlier slice were DOM-presence
  artifacts — the panel closes), rows with key + source link (editor
  rows link to `#/items/<key>`, verified list + panel), keyless row
  titled "No key yet -- use Mint keys", `Mint keys (N)` pill →
  "Minted 1 key(s)." (editor adds the draft-warning sentence, verbatim
  match), key spliced in place (diff: key line only), Archive → byte-
  identical item file + gzip record at `.refdes/navis/<key>.yaml.gz`,
  Restore reactivates, Show-all disclosure appears only once an
  archived row exists, archived row = snapshot + disabled Restore with
  the docs' "hand-restore" hint after the marker is deleted (my first
  enabled-Restore sighting was a rebuild race, not the product), 403
  lock on `--no-write` servers with every control disabled, unsaved
  editor draft survives Archive with zero reloads. CLI parity:
  ls/all/show/archive/restore, all three selector kinds, exit codes,
  `navis.archived_orphan` warning verbatim.
- **Serve API matrix** (`docs/navis.md` table): archive ok → 200
  `changed:true`; archive-again → 200 `changed:false`; restore of an
  active → 409 `not_archived`; missing/null `navi` → 400 with the full
  selector sentence; unknown selector → 404 naming the ordinal range;
  no token → 403; `--no-write` refusals verbatim for archive/restore
  and mint; GET gated.
- **Editor item rows → item view** (#450): click navigates
  `#/items/<key>`, detail pane loads the body.
- **#429 conflict**: edit in browser → edit the file on disk → Save →
  "The file changed on disk" with the path, both texts side by side,
  `Keep mine` / `Keep theirs` / `Discard draft`; Keep mine writes the
  draft over the disk edit, as documented.
- **#410 Navi button**: inserts `<!--navi: text-->` with `text`
  selected; wraps a selection keeping it selected; leaves a selection
  containing `--` untouched. **#418 fence button**: caret →
  `\n\n```\n\n``` ` own padded paragraph, caret inside; wraps
  selection; wraps a selection containing ``` in a 4-backtick fence.
- **Task pane ticks/draft** (#456/#463, both browsers): checkbox on
  open/done/dropped rows; panel carries tip key + revision; preview
  note verbatim; ticking writes nothing (hashes); the count, Discard,
  per-tab draft (survives reload, fresh tab = file state), and
  beforeunload prompt all behave; cleared thread renders no checkboxes
  and no ticks module; project with no `follows:` publishes no pane;
  built `_site` pages have the toggle + read-only pane, no checkboxes,
  no ticks module; `viewing LOG-A-005 · tasks as of tip …` note on
  older entries including id-less ones.
- **`--no-write` preview datum (requested at review):** on a
  `--no-write` server the preview pages of a thread tip carry **no
  tick checkboxes and no ticks module** — confirmed by inspection of
  the served page. **Undocumented**: `docs/cli-reference.md` §serve
  (line 2349) still promises preview and site show "the *same* thing"
  with no `--no-write` qualification for the pane, the W5b changelog
  fragments never mention `--no-write`, and `docs/navis.md:246+`
  gates only the Navis panel's actions. The behavior is deliberate in
  the code (a write-capable control the server refuses is "the UI
  lying", `serve/server.py`) and test-pinned; no doc states it.
- **`POST /api/item/<ref>/continue`** (#453): 200 applied (appends
  `id:`+`key:`, composite `follows: [ID@key]`, ticked-up task list,
  full diagnostics payload); 409 conflict with `current_revision` +
  `current_text` on a stale `expected_revision`; 422 refusals for
  forked thread, cleared list, unknown task id, state outside the
  vocabulary, unknown ref; 400 malformed JSON and missing field; 403
  missing token; 403 missing Origin; `--no-write` refusal
  "continuations are disabled".
- **#449 fetch**: hand-added `values:` key pruned with
  `source: dropped <path>: <key> (no source() span references it any
  more)` on both plain and `--update`, exit 0, run that prunes nothing
  prints nothing new; record-level junk gets the "not a mapping"
  refusal; cross-item citation authorization error is exemplary.
- **README test command**: `python -m pytest -q -n 4 --dist
  worksteal` → **6250 passed, 2 skipped in 116.00 s** (exit 0).
- **Adversarial**: CRLF item file loads; project under a non-ASCII
  path loads; commands from a subdirectory resolve via marker walk-up;
  read-only tree degrades to the "(read-only tree?)" hint, check stays
  green, `--no-write` silences it; two concurrent `refdes id` runs
  mint safely (both exit 0, ledger green); typo'd refs fail with the
  "looked up by display id, then surrogate key" sentence; hand-broken
  lockfile and hand-duplicated mapping keys get precise errors.
  Duplicate citation ids across items are caught.

## What I could not test

VS Code claims (no VS Code on this box — the `tasksPane` docs section,
tree views, and the context-menu items are recorded as docs-only,
unchecked); the 409 `ambiguous` selector path (needs two keys sharing a
prefix — key algebra, not hand-writable) and the `journal_pending`
conflict (needs an in-flight editor transaction at request time); the
422 sealed-tip refusal (hardware@3 `log` no longer seals at build;
needs a custom sealed type I did not build); Firefox real-mouse
clicks (playwright synthesizes events — the double-step is
event-shape-dependent by construction); the 0.5.0→current citation
**page-count** check (my probe cited a hash-only text file; the `pdf`
extra path went untested); published pages opened from `file://`
(served and on-disk `_site` verified instead); and the full
adversarial matrix against the editor (subdirectory/read-only runs
were CLI-side).
