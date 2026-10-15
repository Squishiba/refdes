# User-simulation release gate — run 7 (374a4aa..885e9e6 as an author)

Scope per `.scratch/task/TASK.txt`: the delta `git log --oneline 374a4aa..885e9e6`
(27 commits), exercised as a user, plus a carry-forward re-check of every
run-6a/6b finding marked open. HEAD tested: `885e9e6` (main for this run).
Open PRs **not** on main and therefore not tested: #238, #242, #243.

**Method, unchanged:** documented surfaces only — `docs/`, `--help`, real CLI
invocations, real HTTP — reporting friction and bugs, fixing nothing. Reported
version: `refdes 0.5.0` (`refdes --version`).

Harness (per `.scratch/COMMON.txt`): `.scratch/rr <projectdir> <args…>` cd's
into the project inside the script and runs
`PYTHONPATH=<worktree>/src /home/jorb/work/venv-refdes/bin/python -m refdes.cli`.
Every project under `.scratch/run7/`, made with `refdes init` + a synthetic
five-item set (REQ-PWR-001/002, BND-THM-001, LOG-PWR-001, CMP-PWR-001 with a
citation over a locally generated 8-page PDF, TST-PWR-001), built and stamped
`r1`, copied one-per-sweep as `.scratch/run7/_pristine`. No git commands
inside a sweep directory, nothing outside the worktree, no recursive deletes,
`serve` stopped by PID. Nothing under `src/`, `tests/`, `docs/` or `items/`
of the repo was modified.

Severity levels as in run 6a: B = bug, F = friction/nit.

---

## 0. Headline summary

The delta's 17 user-facing behaviours all landed as advertised: every CLI
fix (#216, #217, #219, #223, #229, #230, #231, #232, #233, #234, #236, #239,
plus #215, #220, #214/#224) reproduced from its fragment's own claims with
the exact diagnostics, the citation-picker HTTP surface held on all the
corrupt-input shapes (#218, #225), and #227/#221 shipped in the served JS.
Carry-forward closed five more (6a B6/B7/F9/F11, 6b B2/F3, run-4 F3); F10 is
still open, B1 stays Jared's design question, F2 waits on #243.

Two new findings, both the raw-traceback class this project keeps hunting:
**B8** — an `on_change:` mapping with `fields:` as a list kills every command
with an `AttributeError`; **B9** — a directory named `*.yaml` under
`.refdes/baselines/` kills every command with an `IsADirectoryError`
(adjacent to open PR #242). One friction (**F12**): a YAML-corrupt
`keys-adopted.yaml` is silently overwritten by `keys adopt`, contrary to its
fragment's "refuses with the file named" claim. Two nits (F14, F15) and one
residual context (F13, 6a F1 family). Nothing in this run blocks a release on
behavioural grounds; B8/B9 are the ones to take.

---

## 1. Carry-forward: run 6a/6b findings re-tested on `885e9e6`

| # | Finding | Status on `885e9e6` | Evidence |
|---|---|---|---|
| 6a **B6** | `tags`/`refdes` accept a mapping list element (check+build exit 0) | **fixed** | §1.1 |
| 6a **B7** | v3-pinned `decision` item: bare `unknown type`, no pointer | **fixed** | §1.2 |
| 6a **F9** | link-verb mapping element reported as loader dict repr with `'__line__'` | **fixed** | §1.3 |
| 6a **F10** | sealing opt-back-in note prints on every load | **still open** | §1.4 |
| 6a **F11** | `standard upgrade` has no `--dry-run` | **fixed** | §1.5 |
| run-4 **F3** | duplicate-key repoint names no file | **fixed** | §1.6 |
| 6b **B1** | bare `follows:` tip-anchor eats a fork (design question for Jared) | **behaviour unchanged** (confirmed, not re-filed) | §1.7 |
| 6b **B2** | `on_change:` mapping interior modes unvalidated | **fixed** | §1.8 |
| 6b **F1** | tip-anchor rule not in `design-log.md` | **partly fixed** | §1.9 |
| 6b **F2** | no key in any human-facing output (`ls`) | **open** (#243 on that, not on main) | §1.9 |
| 6b **F3** | `schema-reference.md` `on_change` § omits the item-mapping shape | **fixed** | §1.9 |

### 1.1 6a B6 — fixed (#235)

`items/one.md` component with `tags: [power, {name: not-a-string, verdict: x}]`
and the same shape under `refdes:`:

```console
$ rr cf-b6 check
ERROR   items/one.md:2 [CMP-001] — tags[1]: {'name': 'not-a-string', 'verdict': 'x'} is not a string -- a tags entry is a plain string, one per line, as in tags: [first, second]
ERROR   items/one.md:2 [CMP-001] — refdes[1]: {'name': 'also-not-a-string', 'verdict': 'y'} is not a string -- a refdes entry is a plain string, one per line, as in refdes: [first, second]
7 items, 2 errors, 3 warnings          # exit 1
$ rr cf-b6 build   # same two errors, exit 1
```

Run 6a's B6 (exit 0, silent) is closed. Residual (new F, §3): `refdes ls --tag x`
still matches the item (substring over the stringified dict) and the erroring
build writes the site with the dict repr in the tags row (`_site/cmp-001.html`
contains `{&#39;name&#39;: &#39;not-a-string&#39;, ...}`) — build exits 1, so
this is post-error noise, not a silent pass.

### 1.2 6a B7 — fixed (#235)

v3-pinned project, add `type: decision` item:

```console
$ rr cf-b7 check
ERROR   items/d.md:2 — unknown type 'decision' -- it merged into 'log' at hardware@3 (threads phase 4a): write type: log, rename title: to summary:, and rewrite records: as follows: -- status/rationale/options/checks and the satisfies/constrained_by/selects/supersedes/blocked_by links all live on log now, and legacy_prefixes: [DEC] keeps a migrated DEC id warning-free. 'refdes standard upgrade --to 3' carries a project pinned at hardware@2 across and refuses this one (it is already at hardware@3), so these items move by hand. See https://squishiba.github.io/refdes/standard-library.html#versioning-and-pinning.
```

Names the merge, the field moves, the link rewrite, why the chain refuses this
project, and the docs page — exactly what 6a asked for.

### 1.3 6a F9 — fixed (#235)

`satisfies:` with a mapping element:

```console
ERROR   items/one.md:2 [CMP-001] — satisfies[1]: {'name': 'not-a-string', 'verdict': 'x'} is not a string -- a link target is one item id per entry, as in satisfies: [ID-001, ID-002]
```

Element named, shape stated, `'__line__'` gone. (The dict repr is still quoted
in the message, which is fine — it's the author's own YAML.)

### 1.4 6a F10 — still open

`refdes-schema.yaml` with `types: log: sealing: build`; two consecutive
`refdes check` runs both print
`note: refdes-schema.yaml opts the 'log' type back into build sealing -- …`.
Unchanged from run 6a; no fragment in the range claims it.

### 1.5 6a F11 — fixed (#239)

On a v2-pinned project (`standard: version: 2`, v2-spelled items, stamped
`v2s`):

```console
$ rr cf-v2 standard upgrade --to 3 --dry-run
v2 -> v3:
would change 3 file(s):
  items/bounds/thermal.md
  items/d.md
  items/requirements/power.yaml
baselines would be carried forward: v2s
baselines skipped (no recorded standard to migrate from): r1
  standard.version: 2 -> 3 (would be bumped)

dry run -- nothing written; the real run would upgrade to v3.   # exit 0
```

`diff -rq` of the project before/after: **nothing written**. The real run
prints the identical plan with `would` removed and ends `upgraded to v3.`;
`check` clean after. The honest baseline line (`skipped … no recorded standard
to migrate from: r1`) names the one pre-pin baseline the chain can't rewrite.
`--dry-run` on a refusing project prints the refusal under `would refuse:` and
exits 1 (seen below in §2.1) — plan, refusal and writes all previewed.

### 1.6 run-4 F3 — fixed (#237)

Duplicate `id:` line in a list-file entry; the composite reference in
`items/components/pwr.md` gets repointed on a plain `check`, and the load now
says:

```console
WARNING items/components/pwr.md:2 [CMP-PWR-001] — 1 reference naming 'REQ-PWR-002@16n52vgh9bh' in items/components/pwr.md was repointed to 'REQ-PWR-004@16n52vgh9bh' on disk by this load: the duplicate key 'id' in items/requirements/power.yaml drops 'REQ-PWR-002' for 'REQ-PWR-004', and the lost id's key resolves to the surviving item, so the label follows it. The rewrite has already happened -- fix the duplicate 'id' line in items/requirements/power.yaml, then restore the reference text (back to REQ-PWR-002@16n52vgh9bh) if the lost item was the one meant.
```

The repointed file, the old text, the new text, the cause and the undo are all
in the line. Closed.

### 1.7 6b B1 — behaviour unchanged (confirmed, per instruction)

Re-ran run 6b's §1 repro verbatim (four entries in one file: chain, fork of
the root, merge — all bare): the capture lines print as before
(`captured LOG-A-002: LOG-A-003 now follows it`), the merge lands as the
duplicated self-edge `follows: [LOG-A-003@f17y8kc4v8y, LOG-A-003]`, and
`refdes thread LOG-A-004` is the linear chain. No new signal added; recorded
as a confirmation for Jared's design question, not filed again.

### 1.8 6b B2 — fixed (#228)

Item `on_change: {mode: timeine}` and `{fields: {status: timeine, …}, extra_key: x}`:

```console
ERROR   items/requirements/power.yaml:2 [REQ-PWR-001] — on_change mode: 'timeine' must be one of invalidate, timeline, ignore
ERROR   items/requirements/power.yaml:2 [REQ-PWR-001] — on_change fields.status: 'timeine' must be one of invalidate, timeline, ignore
ERROR   items/requirements/power.yaml:2 [REQ-PWR-001] — on_change: unknown key 'extra_key' -- must be one of fields, mode, reason
```

exit 1, matching the sentence docs/schema-reference.md:163-165 now states. The
silent `changed 0 → changed 1` flip run 6b measured is no longer reachable.
Nit kept open as F15: a `fields:` entry naming a field the type does not
declare (`bogusfield: invalidate`) loads clean and does nothing.

### 1.9 6b F1/F2/F3

- **F3 fixed**: schema-reference.md §`on_change` now carries the item-level
  mapping shape (`mode:`, per-field `fields:`, `reason:`, lines 150-161) and
  the history-backed `timeline` exception (lines 142-148) — the exact two
  gaps 6b named. Enforcement matches (#228).
- **F1 partly fixed**: the tip-anchor rule is documented at
  `docs/links.md:64-68` ("the first writable load anchors it to the thread's
  current tip"), which 6b's repro pointed at as absent. `docs/design-log.md:47`
  still glosses `follows` as "the earlier log entry this one continues" with
  no pointer to the anchor rule, and no doc tells an author that a **fork**
  requires composite pins (the topology `cli-reference.md:525-534` prints).
- **F2 open**: `refdes ls --help` has no key column/flag; `thread --json`'s
  projection carries no per-entry key. #243 (`ls --keys`) is the fix, merged?
  — not on main (task lists it as open). Confirmed still open on `885e9e6`.

---

## 2. The delta, swept as an author

### 2.1 #239 — `standard upgrade --dry-run` previews everything, refusals included

Happy path verified in §1.5 (dry plan == real plan, nothing written). The
refusal preview, on a v2 project whose chain cannot carry it (a v2
`decision` item, baseline `v2s`):

```console
$ rr cf-v2r standard upgrade --to 3 --dry-run     # exit 1
v2 -> v3:
would refuse:
  project has existing build errors -- fix those first, so a hash change caused by this rename can't hide behind one already-broken build
  ERROR   items/d.md:2 [DEC-PWR-001] — key deleted since baseline 'v2s': was 'nnx8hvybrn0', ...
```

Plan, refusal and the errors behind it all previewed, exit 1, nothing written.

### 2.2 #216 — a scalar default on a collection-shaped field dies at load

`refdes-schema.yaml`: `tags: {type: list, default: sponsored}`:

```console
$ rr cf-t16 check      # exit 2
configuration error: types.requirement.fields.tags.default on the list field 'tags' must be a list, got 'sponsored' -- write it as default: [first, second]. A scalar default is never split: every item that omits the field stores it as one entry.
```

`default: [sponsored]` loads clean. (Run 6a's B6 sibling: the load-side rule now
exists before any item is ever checked.)

### 2.3 #228 — `on_change:` mapping validated, but the list-shaped `fields:` crashes (B8)

The mapping-form validation is verified in §1.8. The one shape it does not
cover: `fields:` written as a list, which `docs/schema-reference.md` never
spells (the documented item shape is a mapping, schema-reference.md:150-165):

```console
$ rr cf-t1 check       # exit 1, full traceback to stderr
Traceback (most recent call last):
  ...
  File ".../src/refdes/build.py", line 1890, in _hash_payload
    mode = item.on_change_for(fname, spec, project.default_on_change)
  File ".../src/refdes/model.py", line 674, in on_change_for
    override = (self.on_change_override or {}).get("fields", {}).get(field_name)
AttributeError: 'list' object has no attribute 'get'
```

`check`, `ls` — every command that computes the content hash — dies with the
raw traceback. Filed as **B8**.

### 2.4 #217 — a surrogate-shaped type name loads instead of crashing

`refdes-schema.yaml` with `types: {12345678901: {fields: {body: …}}}` (YAML
reads the all-digit key as the int 12345678901): `refdes check` is clean
(6 items, 0 errors), `refdes new 12345678901` scaffolds the type, and
`schema --json` carries the name spelled as written
(`$defs['12345678901__bare']`). The 6a-era `TypeError` traceback is gone.
The first overlay attempt that used `title:`/`kind:` got clean config errors
naming the allowed key sets — no crash path found.

### 2.5 #219 — preset writes are atomic and survive a symlinked config

`refdes-project.yaml` replaced by a symlink to `real.yaml`:
`refdes standard add-preset hardware-3` succeeds, `refdes-project.yaml` is
still a symlink (`ls -l`), the presets line landed inside `real.yaml`, and
`remove-preset` takes it back the same way. ENOSPC mid-write is not
headlessly reproducible; the atomic path is shared with the id ledger
(temp+fsync+rename+unlink-on-failure, `write_atomic`) and pinned by
`tests/` per the fragment.

### 2.6 #231 — `init` refuses an unusable `.gitignore` before creating anything

`.gitignore` as a directory:

```console
$ refdes init          # in cwd, exit 2
configuration error: .../t31x/.gitignore exists but is not a regular file -- refdes init refuses to start rather than write a project around it; remove or rename it and run init again
```

`.gitignore` a 444-mode file:

```console
configuration error: cannot append to .../t31y/.gitignore: file is not writable -- make .gitignore writable, or remove it, and run init again
```

Both leave the directory with nothing created (`ls -a` shows only
`.gitignore`). Refusal exit 2, matching the fragment.

### 2.7 #229 — new seal/baseline files get the umask, reseals keep the mode

Under `umask 0002`: `revision r2` → `.refdes/baselines/r2.yaml` is `664`
(not the temp file's 0600); with `site: types log sealing: build`, the first
build writes `.refdes/log-seal.yaml` at `664`; after `chmod 666` an edit +
rebuild reseals and the file is **still 666** — the mode is preserved, not
reset. Fragment's claims all reproduced.

### 2.8 #232 — `site.assets:` is confined to the project root

```console
$ rr cf-t32 check      # assets: ['../outside'], exit 2
configuration error: refdes-project.yaml: site.assets entry '../outside' escapes the project root; declare a directory under it
$ # assets: ['/etc']
configuration error: refdes-project.yaml: site.assets entry '/etc' is absolute; asset directories must be relative to the project root
```

`assets: [figures]` with a file on the search path: bare-filename `![x](img.png)`
in an item resolves against `figures/`, builds, and the copy lands hashed
under `_site/assets/`. (Unreferenced files in an assets dir are not copied —
by design; the list is a search path, docs/markdown.md:126-150.)

### 2.9 #230 — the read-only marker stays only where a read-only tree fits

Ledger `chmod 444` inside `.refdes` (555 dir), `refdes id` mints on an
id-less item: `ERROR <project> — cannot write .refdes/ids.yaml (read-only
tree?) -- …` — the byte-identical read-only posture, as the fragment promises
(its ENOSPC half, `(No space left on device)`, is pinned by
`tests/test_readonly_explicit_writes.py` injection tests and is not
headlessly producible). Nit: `refdes revision <name>`'s own refusal line
(cli.py:587) hardcodes `(read-only tree?)` unconditionally — same class of
line, outside #230's scope (F14).

### 2.10 #215 — one calc anchor per page; `calcblock` refuses `block=""`

Two items with a block each named `losses`, rendered by two `{{calcblock}}`
directives on one page: the page gets `id="calc-losses"` and
`id="calc-losses-2"`; the merged `document.html` the same. Each owner's own
page carries the bare `#calc-losses`. `[[LOG-CAL-001#calc:losses]]` in prose
resolves to `href="log-cal-001.html#calc-losses"`. `block=""`:

```console
ERROR   pages/overview.md:11 — {{calcblock item="LOG-CAL-001" block=""}} — block="" is not a calc block name -- calcblock renders a named ```calc block. LOG-CAL-001 names: losses.
```

(User error found en route: an inline directive renders literally — the
must-sit-alone-on-its-line rule is documented, blocks.md:3,23.)

### 2.11 #223 — a bare key in `against:` gets the link diagnostic

One component, `checks:` entries `against: k7f3m2q9x4a` (key-shaped,
undeclared), `against: Zy4bas7hkr8` (one upper-case char), `against:
BND-THM-999` (plain display id), plus the same three under `constrained_by:`:

- key-shaped undeclared → `check against key 'k7f3m2q9x4a', which no item
  declares. … run `refdes keys restore DISPLAY-ID@k7f3m2q9x4a --dry-run` …`
  — the same remedy text as the link side, verbatim;
- upper-case-corrupted → `key 'Zy4bas7hkr8' in check against target is
  malformed: contains a character outside the key alphabet. … restore it from
  git`; no longer the typo message;
- plain display id `BND-THM-999` → keeps the old typo remedy (`write the
  item's new id here`), as promised ("it never had a key").

### 2.12 #214/#224 — the malformed-row note rides both `thread` and `work`

Thread of two logs, tip's task list: one valid row, one `- text: Missing an
id.`, one `- 42`:

```console
$ rr cf-t14 thread LOG-PWR-002
Tasks at tip: (1 malformed row(s) not shown)
  1. [ ] T-recheck  Recheck margins.  (open since LOG-PWR-002, 2026-09-03)
  2. [?] ?  Missing an id.
$ rr cf-t14 work          # same heading line, same note
Tasks at tip: (1 malformed row(s) not shown)
  1. [ ] T-recheck  Recheck margins.  (open since LOG-PWR-002, 2026-09-03)
```

The count is `build.validate_items`'s (its `tasks[2]: 42 is not a task` error
prints on `check`). Null id/text rows render as `?` — no `None` anywhere
(G1's pin). `work` shows only open rows by design; the note parity is the fix.

### 2.13 #220 — the image hash sort no longer compares `None` to a digest

Exact fragment repro — item at `items/imgs.md`, `![b](../assets/sub/img.png)`
(resolves to `assets/sub/img.png`, which exists) beside
`![a](assets/sub/img.png)` (whose raw text *is* that resolved path):
`refdes build` exits 1 with the ordinary
`ERROR items/imgs.md:2 [LOG-IMG-001] — image src 'assets/sub/img.png' does not exist`
and **no traceback** (grep Traceback = 0). The crash is gone; the diagnostic
stands.

### 2.14 #212 — corrupt `.refdes/` files name themselves, with two holes

- Corrupt baseline (`baselines/r1.yaml` = `id: [`): every command exits 2 with
  `configuration error: …/baselines/r1.yaml: baseline file does not parse (…)`
  — file named, exit 2. ✓
- Non-UTF-8 `ids.yaml` / non-UTF-8 `keys-adopted.yaml` + `keys adopt`:
  `refused: .refdes/keys-adopted.yaml: adoption marker file is not valid
  UTF-8 (…); repair it by hand or delete it and run again`. ✓
- **Hole 1 (B9)**: a *directory* named `baselines/r9.yaml` — every command
  dies with a raw traceback:
  `IsADirectoryError: [Errno 21] Is a directory: '…/.refdes/baselines/r9.yaml'`
  at `lifecycle.py:189` (`_load_baseline_file`, via `list_baselines`:232).
  The #242 scope ("store decode follow-ups") is adjacent — noted, not
  re-filed against it.
- **Hole 2 (F12)**: `keys-adopted.yaml` = `adopted: [` (valid UTF-8, bad
  YAML): `refdes keys adopt` does **not** refuse — it treats the marker as
  not-adopted, proceeds, and overwrites it with `adopted: true` (exit 0).
  The fragment claims a corrupt marker is "no different: … refuses with the
  file named and says to repair or delete it". Code: `adopt.py:301-313`
  guards only `UnicodeDecodeError`; `keys.py:647` (`is_adopted`) swallows
  `yaml.YAMLError` into the not-adopted posture. The author's marker file is
  silently destroyed.

### 2.15 serve/editor — the citation picker holds (#218, #225, #233, #234, #236)

All against live `refdes serve` (token-file launch, `X-Refdes-Token` header;
writes additionally need `Origin: http://127.0.0.1:<port>` — documented,
cli-reference.md:2035-2039; a write without it is a flat `forbidden`).

- **#218** `POST /api/items/create` with no `id`: `{"kind":"created","ok":true,
  "message":"created: REQ-002 (requirement) in …/power.yaml", …}` — empty id
  read as auto, like the preview. (Payload `fields: {body: …}` → clean refusal
  naming the declared field set — the picker's own vocabulary check.)
- **#225** page route: `page=99999999999999999999` → 422
  `docs/manual.pdf: page 99999999999999999999 is not in this document -- it has
  8 page(s)`; `page=-3` → 400; `page=abc`, `page=2.5` → 400. No dead handler.
- **#233** page count bound to the pinned bytes: lockfile `page_count: 8` with
  `page_count_sha256` pointed at *other* bytes → check:
  `WARNING … — the page numbers cited for docs/manual.pdf are not checked: the
  lockfile's page count is not tied to the pinned sha256 -- run 'refdes fetch
  --path docs/manual.pdf' to recount the pinned bytes`, and the audit
  citation block prints `pages unchecked hash-only` + the indented reason —
  both halves name themselves. Count matched to the pin → range check active
  (`page 99 … has 8 page(s)`). An all-zeros `page_count_sha256` (YAML int 0)
  is a load error naming the record and the shape rule. Swapping the bytes
  under a pin: `local citation … has changed since it was pinned` warning;
  the stale 8-page count is *not* used against the new 3-page file.
- **#234** corrupt lockfile (`citations.yaml` = `{docs/manual.pdf: [`) →
  `GET /api/item/CMP-PWR-001/sources` = 422 naming
  `.refdes/citations.yaml` and the decode reason. No fake unpinned.
- **#236** lockfile `sections: {Intro: nope}` + a citation on `section: Intro`
  → 200 with `open_at: {page: 1, from: "default"}` and
  `cited.detail: "the section 'Intro' … was resolved against different bytes
  than the ones now pinned …"` — detail, not a crash. String-number form
  `Intro: '3'` with `sections_sha256` matching the pin → opens page 3
  (`from: "section"`, empty detail), YAML-string and integer alike;
  `Intro: 99999999999999999999` → the shared page grammar refuses it in
  `detail`, listing survives.
- **#227/#221** are browser-side: the shipped `/edit/static/drafts.js`
  carries the corrupt-mirror path (`refdes.draft.corrupt.v1`, `Discard`) and
  exactly one `dropAppliedOp` call site. The banner click-through itself is
  not headlessly reproducible; recorded as shipped-not-clicked.

### 2.16 daily-driver and a real remote fetch

`ls`, `ls --type log`, `ls power` (free text), `check`, `build`, `new log >
file`, `audit`, `thread`, `work`, `fetch` over a **real** URL
(`citations: - path: https://raw.githubusercontent.com/squishiba/refdes/main/README.md`)
— all clean: `fetched … sha256=ab361625c209… hash-only`, lockfile pin +
audit row, check exit 0. (No `ls --status` flag exists; that was my error,
`--help` answers with the real filter set.) `refdes upgrade` is not a command
(`standard upgrade` is); release-gate behaviour unchanged (blocks on
`uncovered_requirements`, as run 6a).

---

## 3. Findings summary

| # | Severity | Finding |
|---|---|---|
| B8 | moderate | Item `on_change:` mapping with `fields:` written as a **list** → raw `AttributeError: 'list' object has no attribute 'get'` traceback (`model.py:674` via `build.py:1890`); `check`/`ls` exit 1 project-wide. §2.3 |
| B9 | moderate | A **directory** named `*.yaml` under `.refdes/baselines/` → every command crashes with a raw `IsADirectoryError` traceback (`lifecycle.py:189`). Adjacent to open PR #242. §2.14 |
| F12 | low-mid | YAML-corrupt `.refdes/keys-adopted.yaml` (valid UTF-8): `keys adopt` silently overwrites it, exit 0 — the #212 fragment claims a refusal with the file named. `adopt.py:301` guards UTF-8 only; `is_adopted` (`keys.py:647`) swallows `YAMLError`. §2.14 |
| F13 | low | Audit citation block prints `ok hash-only` for a hash-only doc cited by `page:` — pages unchecked, silently (run 6a F1's residual, new `page:` context). §2.14 context: audit rows checked this run |
| F14 | nit | `refdes revision`'s write-refusal line (cli.py:587) hardcodes `(read-only tree?)`; #230 made that marker conditional everywhere it saw the `OSError`. §2.9 |
| F15 | nit | `on_change fields:` entries naming a field the type doesn't declare load clean and do nothing. §1.8 |
| F16 | nit | 6a B6 residual, confirmed persisting: `ls --tag` substring-matches the stringified dict of a mapping-shaped tag, and the (exit-1) build writes the dict repr into `_site` tags rows. §1.1 |

Carry-forward status is in §1; B1/F2/F10 stay open as recorded there.

---

## Appendix — how to reproduce this run

`rr` as in run 6a/6b. `.scratch/run7/pristine` = `refdes init` + the
five-item synthetic set + `refdes fetch` + `build` + `revision r1`; the PDF is
`.scratch/run7/mkpdf.py <path> <pages>` (a hand-written 8-page PDF). Sweep
cases are `cf-*` / `t*` copies of `_pristine` with one edit each. The editor
sweeps ran against `refdes serve --no-open --port 8741 --token-file
.scratch/run7/ed-token.txt` (PID recorded, killed by PID); the cookie jar is
`.scratch/run7/jar2.txt` (the login cookie is `refdes_token_8741=`, set by
`GET /edit/?token=…`). `ed-sweep` carries one leftover probe item (REQ-001,
empty body) from the #218/create probes; `cf-*` projects are not cleaned.
