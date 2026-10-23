# User-simulation release gate, run 13

Acting as a hardware-author user of the shipped docs on branch
`user-sim-run13` (base `899ab91`). The in-scope source commits:

- `c3073c6` feat(release): release_gate.inline_calc_results fails a release on stale inline-calc results (#345)
- `475467b` fix(patcher): insertion keeps a same-line trailing comment on its own line (EDIT-02) (#354)
- `2358410` fix(serve): editor save accepts the surrogate-key handle its own list hands out (EDIT-01) (#355)
- `0342f79` fix(check): --board no longer shows other boards' id-less item diagnostics (CHK-ATTR-003) (#357)
- `bc89657` fix(check): page-block diagnostics report the file line, not the body-relative line (CHK-ATTR-001) (#360)
- `899ab91` fix(serve): the edit route resolves retired ids like the read route (EDIT-03) (#358)

#361 (imported items' diagnostics naming `NAME:upstream/file:line`) is **not
in main** — `git log --oneline -40` has no such commit — so the imported-item
attribution sweep was skipped; noted in section 7.

Judged against `docs/lifecycle.md` (the gate rules table and prose),
`docs/math.md` (Inline calc, incl. the gate paragraphs), `docs/blocks.md`
(page-block failure modes), `docs/cli-reference.md` (`release`, `check`,
`serve`, `history capture`), `docs/multi-board.md`, `docs/pages.md`, and the
changelog fragments for the six commits. Findings are reported, not fixed.

## 0. Headline

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| F13-1 | Medium | release gate | fail-closed on an unreadable history store does not name the store — both `docs/math.md` and `docs/lifecycle.md` promise it does |
| F13-2 | High | editor save | the write route still refuses the keyless item's handle (`~file:line`) — the third spelling of "the handle its own list hands out" that #355 did not fix; every browser-editor save in a keys-never-minted project 422s |
| F13-3 | Low | editor save | 409/422 response `message` fields embed the server's absolute paths while `path` is project-relative |
| F13-4 | Low | check/build | the page `invalid page front-matter` warning prints twice per run, and (unlike every other page diagnostic) carries no file line |

## 1. Harness

- `refdes` 0.5.0 from this worktree (`PYTHONPATH=<worktree>/src`, venv
  python), standard `hardware@3`, Python 3.13.
- One helper `.scratch/rr <proj> <args...>`; all projects under
  `.scratch/run13/`. No git commands in sweep dirs except dedicated throwaway
  `git init` repos.
- `refdes serve` runs with `--no-open --port 8731 --token-file tok13`
  (PID recorded, killed at the end, no `pkill -f`); token lives under
  `.scratch/run13/`, never `/tmp`.

## 2. Sweep 1 -- release_gate.inline_calc_results (#345)

Fixture project `g1` (git-init'ed throwaway repo): stale editable span
(CMP-001, component — no coverage/status noise), correct span (CMP-002),
three spans with one stale (CMP-003), stale span inside a ```` ```text ````
fence (CMP-004), captured-unedited stale (LOG-001), captured-then-edited
stale (LOG-002), list-file `body:` stale (LOG-003 in
`items/pwrl/entries.yaml`), id-less continuation with a stale span
(LOG-004.md's second section). Sealed-build shape lives in `g2` (custom
`note` type, `append_only: true`, engine-default `sealing: build`); the
exemption-follows-captured-text shape in `g7` (fence reads
`REQ-100.V_in`, span over the local name, captured clean, then upstream
moved).

### 2.1 Verified-correct core (no finding)

- Stale editable span fails the gate, exit 1, with the documented naming:
  `FAIL     inline_calc_results  CMP-001: inline calc Vout (items/CMP-001.md:8), CMP-003: inline calc A3 (items/CMP-003.md:7), LOG-002: inline calc Vn (items/LOG-002.md:9), LOG-003: inline calc Vr (items/pwrl/entries.yaml:2), LOG-005: inline calc Vc (items/LOG-004.md:17)`.
  Item display id, span name, span's file line — the fix is clickable, as
  `docs/lifecycle.md:161-166` promises.
- The multi-span item names only the stale span (CMP-003: A3 only).
- List-file `body:` offender names the item id and the entry's file:line
  (`items/pwrl/entries.yaml:2`, the entry line, not the `body:` key line),
  matching "falling back to the item's entry line for a list-file `body:`
  key".
- `check` agrees with `release`: the identical stale facts appear as
  warnings at the same file:line, `check` exits 0, `release` exits 1. The
  gate rule is the readiness fact on top of the same warning, as documented.
- Correct span: no warning, rule passes. Stale span inside a fence: fully
  inert (no warning, no gate).
- Sealed exemption: `g2`'s stale span was sealed by `refdes build`;
  `refdes release` stamps ("all gates passed") while `build`'s stale warning
  stays visible. Editing a sealed entry afterward is a floor-level ERROR
  (`append-only and has been modified since it was sealed`), so the
  sealed-stale shape is necessarily "sealed while stale" — matches the
  docs' "its warning stays visible, the gate stays silent".
- Capture exemption: LOG-001 (captured, unedited) keeps its warning and is
  absent from the offender list. LOG-002 (captured, then its span's input
  edited) blocks — editing restores editable prose, per docs.
- Exemption follows the captured text: in `g7` the captured span computes
  10 V against a stored `4 V` only because the *upstream* moved after
  capture; the live text is unchanged — `check` warns, `release` shows
  `pass     inline_calc_results`. Exactly the documented
  "the exemption follows the captured text, not the upstream values that
  move later".
- `refdes revision rev-a` stamps with six stale spans in play —
  unaffected, per docs. `--no-write release rel-d` prints the gate table
  and writes no baseline. There is no `--dry-run`:
  `refdes: error: unrecognized arguments: --dry-run`, exit 2 — the CLI help
  and `docs/cli-reference.md:333` both say so; verified.
- Config shapes: `inline_calc_results: "true"` / `1` / `[release, true]` →
  `configuration error: refdes-project.yaml: release_gate.inline_calc_results
  must be a mapping with 'release' and/or 'revision' keys, got 'true'`
  (exit 2, names the key and shows the received value). `null` behaves as
  `{}` — the overlay-on-defaults, gate stays on. `{release: yes}` loads as
  the YAML bool it is. `{release: false}` → release stamps with six stale
  spans. The key spelled `inline_calc_result` → load-time error naming the
  rule list plus `Did you mean 'inline_calc_results'?`, exit 2 — as
  `docs/lifecycle.md:41-42` promises.
- Offender naming after `refdes id` minted the continuation an id: LOG-005
  named by its display id (see 2.2 for the permanently-id-less clause).

### 2.2 F13-1 (Medium) -- the fail-closed path does not name the unreadable history store

Repro (`g1`, which has captures in `.refdes/history/` and one editable
unsealed stale span):

```console
$ chmod 000 .refdes/history
$ refdes release rel-h2; echo $?
9 items, 0 errors, 6 warnings

release 'rel-h2' blocked -- not stamped:
  pass     draft_items
  ...
  FAIL     inline_calc_results  CMP-001: inline calc Vout (items/CMP-001.md:8),
    CMP-003: ..., LOG-001: inline calc Vm (items/LOG-001.md:9), LOG-002: ...,
    LOG-003: ..., LOG-005: ...
1
```

`docs/math.md` promises: "If an editable, unsealed stale span is in play and
the history store cannot be read, the release gate fails closed **and names
the unreadable store**." `docs/lifecycle.md` repeats the fail-closed
behavior. What the author gets: the gate fails closed (exit 1 — good,
conservative) by *adding the captured-exempt item* (LOG-001) to the offender
list. No line of the output mentions `.refdes/history`, permissions, or the
word history/store at all (verified with `grep -E "history|store"`). The
author sees a previously-exempt item turn offender with zero explanation of
*why the exemption vanished*; the obvious reading is "my capture expired",
which is the opposite of the truth. A `stale inline-calc gate: cannot read
the history store <path> (<error>) -- failing closed` line is what the docs
promise and what the fix would be.

### 2.3 Observations (2.1 follow-ups)

- The rule's "permanently id-less continuation ... named by its surrogate
  key when one has been minted" naming clause is unreachable through
  `release` in this build: an id-less item is a load-time ERROR
  (`item has no id — run 'refdes id' to allocate one`), and the always-on
  floor blocks `release` before the gate table runs. Every project where the
  rule *can* name an id-less item is one where `release` cannot get that
  far. Not filed as a finding — the clause is defensive prose, and the
  floor-first ordering is itself documented.
- The gate table lists `inline_calc_results` last, in `release_gate:` order,
  passes included — matches the lifecycle docs.

## 3. Sweep 2 -- editor write boundary over the documented HTTP surface (#354, #355, #358)

Projects `e1` (4 items: trailing-comment fixtures in Markdown front matter,
a YAML list file, and a CRLF file), `e2` (one item, keys never minted),
`e3` (retired-id fixtures). `refdes serve --no-open --port 873{1,2,3}
--token-file tok13`, token read from the launch file, writes with
`X-Refdes-Token` + the server's own `Origin`; every serve stopped with
`kill $pid` (token files removed on the clean stop, as documented).

The wire shapes are not author-documented beyond `docs/cli-reference.md`'s
serve section and `docs/performance.md`'s `POST /api/item/<ref>/edit
(op: set_body)` line; the op vocabulary (`set_field`/`set_body`/`add_link`/
`remove_link`, `expected_revision` from `edit.file_revision`) was read off
the shipped UI's own client (`serve/static/editor.js:39,234` posts the list
row's `handle` and the `edit.file_revision`) — the JS the browser runs, not
a private API.

### 3.1 EDIT-02 verified -- the comment stays on its line (#354)

Every insert shape lands the new key on its own line with the author's
trailing comment untouched, byte-for-byte (only the inserted line added):

- Front matter, last field `status: active  # keep this too` + `source:
  spec 3.2` → comment row unchanged, new key row after it (a title carrying
  a mid-front-matter `# keep me` is likewise untouched).
- List file, entry whose *last* field is `summary: ... # tail note` +
  `status: accepted` → inserted after, comment intact; the file's
  pre-existing `# list handle` comment on an id row also untouched.
- CRLF file: inserted line ends `source: spec x^M$` (CRLF preserved), the
  `status: active  # crlf note` row unchanged.
- Bare comment line between fields: insertion goes after the last field,
  the standalone `# a note between fields` row unmoved.
- `add_link` of a verb the item does not have: `governed_by:
  REQ-002@8wk9fkkxt17` inserted as its own row below `status: active  #
  link note`; the composite expansion (`@key`) lands as documented for
  keys.

No finding: zero line movement in any shape.

### 3.2 EDIT-01 verified for the fixed spellings (#355)

- Keyed project (`e1` after `refdes check` minted keys): `/api/items` rows
  carry `handle` = surrogate key; `GET /api/item/<key>` and `POST
  /api/item/<key>/edit` both succeed (200, file written) — the exact
  pre-fix EDIT-01 dead end is gone.
- `422` wording for unknown spellings: `refused: no item 'NOSUCH-9' in
  this project` (id) and the same for a bogus 11-char key — clean, no
  Python reprs.
- Stale `expected_revision` → `409` with `expected`/`current_revision`,
  `current_text` and a unified `diff` — actionable, as the fragment
  promises the conflict screen needs.

### 3.3 EDIT-03 verified -- the write route resolves retired ids (#358)

In `e3` (`REQ-007` with `former_ids: [REQ-000]`; `REQ-008`/`REQ-009` both
claiming retired `REQ-005`; `REQ-010` retiring `REQ-011`, which is a live
display id):

- `POST /api/item/REQ-000/edit` → 200; the patch lands on `REQ-007.md` at
  the *current* spelling; the response carries the live `"id": "REQ-007",
  "handle": "REQ-007"` — exactly the documented ref-correction contract.
- Double-claimed retired id: write refuses (422) and names both claimants
  — `refused: former id 'REQ-005' is recorded in the former_ids of
  'REQ-008', 'REQ-009': a retired id must resolve to exactly one item, and
  this write refuses to pick one`; the read route 404s
  (`no item matches 'REQ-005'`). The fragment's read-route change (used to
  answer 200 with the first claimant) holds.
- Retired id that is also a live display id resolves to the live item
  (`REQ-011` saved by its own id, not to `REQ-010`).
- Conflict under a retired id keeps its diff: 409 against
  `path: items/REQ-007.md` (the live file), planned against the live
  spelling — matching the fragment.

### 3.4 F13-2 (High) -- the write route still refuses the keyless item's handle, the one shape of "the handle its own list hands out" that #355 did not fix

Project `e2` is a project `refdes serve` can serve on day one: `init` +
one item, keys never minted (serve writes nothing, so keys mint only after
the first *writable* CLI run). The list hands out the keyless handle, the
read route resolves it, the write route refuses it:

```console
$ curl -H "X-Refdes-Token: $TOK" http://127.0.0.1:8732/api/items | ... # items[0].handle
~items/REQ-001.md:2
$ curl -H "X-Refdes-Token: $TOK" http://127.0.0.1:8732/api/item/'~items/REQ-001.md:2'
# 200 -- resolves, edit.file_revision present
$ curl -X POST ... -d '{"op":"set_field",...,"expected_revision":"<the file_revision from that GET>"}' \
    http://127.0.0.1:8732/api/item/'~items/REQ-001.md:2'/edit
422 {"kind":"refused","ok":false,
 "message":"refused: no item '~items/REQ-001.md:2' in this file (it holds: REQ-001)"}
```

The shipped browser editor posts exactly this handle
(`serve/static/editor.js:234` builds the URL from the list row's `handle`),
so in a keys-never-minted project **every editor save is a 422** —
the EDIT-01 failure mode (the list hands out a handle the write route
cannot resolve, and the 422 "it holds:" list names the id the handle *is*)
survives for the third spelling. The #355 fragment's own contract is
"the item is one identity with two spellings and the file carries both;
the patch boundary must accept both" — `patcher._Item.aliases` gained the
id and the key, and the keyless handle (`~file:line`, the model dict key
for a keyless item, which the shared resolver's "dict key" step resolves on
the read route) is a third spelling the patcher still parses identity lines
for. The CLI is unaffected; the fix belongs at the same patch boundary. The
author-visible flow: fresh project → `refdes serve` → Editor → change one
field → red 422 on every save, on an item the editor just opened fine.

### 3.5 F13-3 (Low) -- write-route response `message` embeds the server's absolute paths

The 409/422 `message` fields carry the machine path
(`conflict: /home/jorb/.paseo/worktrees/.../items/REQ-001.md changed
since this edit was planned`, `applied: md-front-matter REQ-007: insert
source at /home/jorb/.../REQ-007.md:6`), while the sibling `path` field is
project-relative — `api.py`'s `shown()` helper exists precisely because "a
path it cannot read is a path it cannot leak". Cosmetic for a loopback
author, but the response is the documented surface the UI renders; the
relative spelling belongs in `message` too.

## 4. Sweep 3 -- check attribution (#357, #360)

### 4.1 CHK-ATTR-003 verified -- `--board`/`--workspace` attribute id-less diagnostics by path (#357)

Project `b1`: `item_layout: workspace`, boards `power`/`thermal`, workspaces
`prod-a`/`prod-b`, four id-less entries each with an unknown-field warning
(`items/prod-a/power/`, `items/prod-a/thermal/`, `items/prod-b/power/`, and
a stray `items/stray/dir/` naming no registered scope).

- `check` (no scope): all four `[?]` warnings, all four project-level
  `item has no id` errors — unchanged, as the fragment says.
- `check --board power`: power's two `[?]` warnings only; thermal's hidden.
  `--board thermal`: mirror image. Board B's report is no longer padded
  with board A's warnings.
- The stray `items/stray/dir/` warning stays visible under **every**
  `--board`, and every `--board` run keeps all four project-level
  `item has no id` errors — both "stays visible everywhere" classes from
  the fragment.
- `--workspace prod-a` / `--workspace prod-b` filter the same way
  (workspace attribution, not just board).
- `check --board nosuch` →
  `ERROR <project> — --board 'nosuch' is not a board declared in
  refdes-project.yaml's boards: registry.`, exit 1, and the stray warning
  still prints — the unknown-scope shape is a named configuration error,
  not a silent filter-everything.

Zero findings.

### 4.2 CHK-ATTR-001 verified -- page-block diagnostics name the file line (#360)

Project `p1`: one `log` item; pages carrying a bad directive of each of the
five block families under front-matter shapes of 0 (empty fences), 2, 3, 4,
6 lines, no front matter at all, and a CRLF page. Directive file lines
measured with `grep -n`; every diagnostic matches the file line, exactly
the fragment's `:3`-was, `:8`-now shape:

```console
$ ... check | grep pageno | cut -d' ' -f2
pages/idx0.md:4    pages/idx2.md:6    pages/idx4.md:8   pages/idx6.md:10
pages/nofm.md:2    pages/crlf4.md:7
pages/tree3.md:7   pages/cmp3.md:7    pages/calc3.md:7  pages/casc3.md:7
```

(the no-front-matter page is unchanged, as promised; `{{cascade}}` is the
fifth family — the run's task brief says "parts", but no `parts` block
exists; `docs/parts.md` is about the parts *page*, and its example is an
`{{index by="part_number"}}` usage, whose failure modes are index's.)

Wording matches `docs/blocks.md`'s documented failure modes: bad value
names the fix (`type 'log' has no field 'pageno'. Declared fields: ...`),
unknown/missing parameters list the accepted set (`tree accepts: board,
workspace, depth`).

### 4.3 F13-4 (Low) -- the `invalid page front-matter` warning prints twice, and carries no line

A page with unparseable YAML front matter (`title: [unclosed`):

```console
$ .scratch/rr .scratch/run13/p1 check | grep -c "invalid page front-matter"
2
$ .scratch/rr .scratch/run13/p1 build | grep -c "invalid page front-matter"
2
```

The identical warning — twice per run, in both commands, for a single
page. (Precedent: run 12's id-load-error double-print was treated as a bug
and fixed.) And unlike every other page diagnostic, this one has no line
number at all — `pages/badyaml.md —` — so the author who just learned block
diagnostics point at file lines (4.2) finds this one pointing nowhere; the
embedded YAML excerpt speaks in front-matter-relative lines ("line 1,
column 8"), which on a page whose front matter starts at file line 1 reads
like file lines and on a page with a leading blank line lies. The
#360 fragment's closer ("like every other page diagnostic") is true of
block diagnostics and exactly false of this one.

## 5. Sweep 4 -- spot re-check: run-12's inline-calc fixes all hold (#351)

Project `s13`, one `check --no-write` + one `fetch`. All six:

| Run-12 finding | Re-check shape | Result |
|---|---|---|
| F12-1 (span in HTML comment validated) | `` <!-- `hidden := 1 V + 1 V \| V = 2 V` --> `` | no diagnostic — inert, and a stale value inside the comment stays silent too |
| F12-2 (filename `:=` in a code span) | `` `src=a:=b.csv` `` | `inline calc src=a:=b.csv: 'src=a' is not a calc name before `:=`; if this is literal text, use a double-backtick span; if it is a calc, write `name := expression = result`` — flagged by name, both escapes named |
| F12-3 (tight result separator rejected) | `` `a := 2 V * 3|V=6 V` `` | accepted, no diagnostic |
| F12-4 (stale warning displays rounded value) | `` `x := 6.899 V / 2 = 3.5 V` `` | `stored result says 3.5 V, now computes 3.4495 V` — raw value shown |
| F12-5 (cross-item span gap message blames the target) | span `c := REQ-001.V_in` over a fence-defined `V_in` | `REQ-001 has not been evaluated yet -- a reference used only in an inline span creates no evaluation-order edge ... keep this reference in a calc fence` — the fix lives in the message |
| F12-6 (span `source()` advice dead-ends) | cited local CSV, span-only `source("analysis/bud.csv", "k1")`, before and after `fetch --path` | stable both times: `has no locked value -- key discovery reads calc fences only, so a source() used only in an inline span is never pinned; write the line in a calc fence and run 'refdes fetch --path analysis/bud.csv'` — the loop's exit is in the message |

Zero findings.

## 6. Notes

- The `citations:` field on a `requirement` is an unknown field in the
  bundled `hardware@3` (only `component` and the verdict-claiming types
  include the `citations` field group) — a fixture-friction, not a finding
  (the warning is accurate and names the item).
- `refdes check --no-write` is a global flag position
  (`refdes --no-write check`); `check --help`'s prose mentions `--no-write`
  and the flag parses globally — the help's OPTIONS list doesn't show it,
  which briefly reads as "check can't do it". Cosmetic.

## 7. Status and limitations

Finished: sweeps 1-4, report. Not done, deliberately: no browser DOM
interaction (serve exercised over its documented HTTP API, plus the shipped
editor JS read as the wire-contract doc); #361's imported-item attribution
skipped (commit not in main); the permanently-id-less continuation naming
clause in #345's rule text is unreachable through `release` (observation
2.3, not asserted as behavior).

Findings: 4 — 1 High, 1 Medium, 2 Low. Fixes verified: all six scope commits
in their documented shapes; all six run-12 fixes re-verified.
