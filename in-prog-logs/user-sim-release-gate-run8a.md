# User-simulation release gate — run 8a (885e9e6..f33efa4 as an author)

Scope: the non-serve CLI/core fixes in `885e9e6..f33efa4`, exercised the way
an engineer writing design logs would. Tested at HEAD `f33efa4`. Report only —
no code or docs changes. Model: `user-sim-release-gate-run7.md`.

The 18 non-`docs`/serve/editor/workbench commits in the range split into 15
author-facing fixes and 3 with no author CLI surface:

- **In scope (15):** #290 rename mapping shape, #272 history redact rollback,
  #271 store dir-as-file + keys-adopt marker, #270 `on_change fields:` shape,
  #266 directory-citation wording, #254 patcher `remove_link` comment,
  #257 `id` prints load errors once, #259 parse repeat under flow defaults,
  #261 build image src, #258 negative `page_count`, #252 keys restore,
  #242 imports non-UTF-8, #247 textio umask, #238 sealing note once,
  #243 `ls --keys` / `thread --json` key.
- **Out of scope (3):** #246 backlog sweep C (log-only), #251 chore sweep A
  (audit-log/test nits), #263 `schema-valid-009` (render CRLF loss reproduced
  and root-caused, deliberately **left** as design — latent, no CLI surface).

Two numbers in `TASK.txt` were stale against the real git log: the patcher
`remove_link` fix is **#254** (not #261), imports non-UTF-8 is **#242** (not
#262/#212), the textio umask fix is **#247** (not #253); `#261` is the
build-image-src fix (`IMAGE-ASSET-002`). `#239 standard upgrade --dry-run` is
**not in this range** (merged before `885e9e6`; run 7 §1.5/§2.1 covers it), so
the fifteenth author-facing fix is #261, as listed above.

---

## 0. Headline summary

Every one of the 15 author-facing fixes reproduced from its own PR claim with
the documented diagnostic, and each held under a push (an adjacent shape, the
same mistake in a neighbouring command, a second run). **No new bug-class
findings.** The daily-driver pass (4 log entries with links, a calc block, a
bound check, build, read the HTML) is clean.

The 15: #290 (rename sections refused by name), #272 (author path intact;
atomic-restore code landed), #271 (dir-as-store-file named; corrupt keys
marker refused, marker untouched), #270 (`fields:` list → load diagnostic;
undeclared field named — the run-7 B8 traceback is gone, F15 closed), #266
(check and fetch say the one sentence), #254 (`remove_link` refuses to delete
an interior comment), #257 (each load error printed exactly once), #259 (no
false "in this file's defaults" clause for a top-level repeat), #261 (an image
src with `&` builds, publishes, and renders consistently; missing images still
reported), #258 (negative `page_count` refused in check/build/fetch), #252
(a linked pair restores together; the owner is no longer falsely refused), #242
(non-UTF-8 / invalid-JSON / directory import artifact → clean read error), #247
(new files get the kernel umask, not a lone 600), #238 (sealing opt-back-in
note prints once), #243 (`ls --keys` key column; `thread --json`/`--keys` carry
the key).

Three friction notes, all nit-class (no behavioural blocker):
**F1** a read-looking command (`ls`) writes the tree and prints a
"(rewrote N reference(s) while loading)" line (writable-load is by design, so
this is a note, not a defect); **F2** the #243 `ls --keys` zero-width
"no key at all" branch is unreachable through the CLI because key minting
fires on every load; **F3** the #254 `remove_link` fix has no CLI surface —
reachable only through the serve editor, so it was exercised by driving
`patcher.patch_item` exactly as the editor's per-op HTTP call does.

---

## 1. The delta, swept as an author

Each case is a fresh copy of a pristine 8-item project (`.scratch/run8a/
_pristine`: REQ-PWR-001/002, BND-THM-001, LOG-PWR-001..004, TST-PWR-001,
hardware@3) with one edit. `rr <dir> <args…>` =
`PYTHONPATH=<worktree>/src <venv>/bin/refdes` inside the project.

### 1.1 #290 — a malformed rename-mapping section is a named error, not a crash

A scalar, list, or number under any plan section names itself and the section,
exit 2, no traceback (`rename` mapping is positional; the plan is a YAML path):

```console
$ rr cf-fields rename plan.yaml --dry-run      # plan: "fields: 5"
error: plan.yaml: fields: must map a type name to {old_field: new_field},
       e.g. `constraint: {title: text}` -- got a number
$ rr cf-links  rename plan.yaml --dry-run       # plan: "links: [a, b]"
error: plan.yaml: links: must map an old link verb to its new verb,
       e.g. `refines: narrows` -- got a list
$ rr cf-prefixes rename plan.yaml --dry-run     # plan: 'prefixes: "x"'
error: plan.yaml: prefixes: must map an old id prefix to its new prefix,
       e.g. `CON: BND` -- got a string
$ rr cf-ckeys  rename plan.yaml --dry-run       # plan: "citation_keys: 5"
error: plan.yaml: citation_keys: must map an old citation-entry key to its new
       key, e.g. `url: path` -- got a number
```

Every top-level section is covered; each bad shape is refused with the section
name and the expected shape. The valid rename happy path (dry-run + real)
still works. **FIXED.**

### 1.2 #272 — history redact's rollback is atomic (author path intact)

The fault-injection path (ENOSPC mid-rollback) is not author-reproducible, so
the fix was confirmed two ways: the author-visible path is intact
(capture → redact `--confirm` → check stays clean), and the atomic
restore (`_restore_atomically` + `os.replace`) is landed at
`src/refdes/history.py:917`.

```console
$ rr cf272 history capture LOG-PWR-002
$ rr cf272 history redact LOG-PWR-002 --confirm
redacted … (names what was removed by digest/event-id, not content)
$ rr cf272 check
8 items, 0 errors, 1 warnings
```
**FIXED** (author-visible path intact + code landed).

### 1.3 #271 — a directory where a store file is expected; `keys adopt` refuses a corrupt marker

Closes run-7 B9 and F12. A directory named `*.yaml` under `.refdes/baselines/`
is named and refused (was a raw `IsADirectoryError` traceback killing every
command); a corrupt/list/directory `.refdes/keys-adopted.yaml` is refused with
the file named and left byte-identical:

```console
$ mkdir .refdes/baselines/stale.yaml ; rr cf271 check
configuration error: …/.refdes/baselines/stale.yaml: baseline file is a
                    directory, not a file
exit=2
$ printf 'not: [a, mapping]\n' > .refdes/keys-adopted.yaml
$ rr cf271 keys adopt REQ-PWR-001
error: .refdes/keys-adopted.yaml is not a valid adoption marker … (refused)
$ cat .refdes/keys-adopted.yaml
not: [a, mapping]            # byte-identical — not silently overwritten
```
Directory-as-citation-lockfile → `ERROR`; a directory under
`.refdes/history/events/` → a graceful `WARNING` naming the path. `--dry-run`
previews the marker refusal; the happy path writes the marker. **FIXED.**

### 1.4 #270 — `on_change fields:` shape and undeclared names are load diagnostics (closes run-7 B8, F15)

The list-shaped `fields:` that killed every command in run 7 (B8) is now a
load diagnostic with file:line and the expected shape; a `fields:` entry naming
an undeclared field (F15, a silent no-op) is now an error naming the declared
fields:

```console
$ rr cf270a check        # on_change: {fields: [body, summary]}
ERROR  items/log/regulator.md:2 [LOG-PWR-001] — on_change fields: must be a
       mapping of field name to mode, got ['body', 'summary'] -- write it as
       fields: {status: timeline}
exit=1
$ rr cf270b check        # on_change: {fields: {nosuchfield: {mode: warn}}}
ERROR  items/log/regulator.md:2 [LOG-PWR-001] — on_change fields.nosuchfield:
       type 'log' has no field 'nosuchfield' -- declared fields: source, note,
       tags, citations, date, summary, author, status, rationale, options,
       checks, tasks, body
```
The `model.py:674` `AttributeError: 'list' object has no attribute 'get'`
traceback is gone; every command that computes the hash survives. **FIXED.**

### 1.5 #266 — a directory citation gets one sentence from `check` and `fetch`

A local citation whose `path:` is a directory produces the same sentence from
both commands (fetch keeps its `cited by` suffix); an absent path keeps
"does not exist":

```console
$ rr cf266 check        # citations: [{path: cite/adir (a directory)}]
ERROR  items/log/regulator.md:2 [LOG-PWR-001] — cited local file 'cite/adir'
       is a directory, not a file
$ rr cf266 fetch
FAILED  cite/adir  cited local file 'cite/adir' is a directory, not a file
        (cited by LOG-PWR-001)
```
**FIXED.**

### 1.6 #254 — `remove_link` refuses to delete a comment inside a multiline flow entry

No CLI surface (editor-only HTTP); driven through `patch_item(text, ref,
RemoveLink(...))` byte-for-byte as the editor's per-op call. Deleting the last
target of a multiline flow entry that carries an interior comment is refused
(pre-fix it destroyed the file); the plain-flow control applies cleanly:

```console
-- last target + interior comment (pre-fix: destroyed the file)
   Refusal: a comment sits on the 'amends' entry of item LOG-PWR-001; deleting
   the entry with its last target would take the comment with it …
-- two targets, one carries a comment (separator not a plain comma)
   Refusal: the separator around LOG-PWR-002 in item LOG-PWR-001 is not a plain
   comma (a comment or unquoted text) …
-- plain two-target flow list (control: applies cleanly)
   PatchPlan → amends: [LOG-PWR-003]
```
**FIXED.**

### 1.7 #257 — `id` prints each load error once

Four broken files + one pending item: each load-error line appears exactly
once (the post-allocation report no longer re-prints the cumulative
`project.errors`); allocation runs, exit 1:

```console
$ rr cf257 id
occurrences of the load-error line: 4        # four broken files, each once
$ rr cf257 id >/dev/null ; echo $?
1
```
The nothing-pending path prints each once too. **FIXED.**

### 1.8 #259 — a top-level repeat under flow defaults is not "inside defaults"

A flow-style `defaults:` line plus a top-level duplicate id no longer gets the
false "(in this file's defaults)" clause; a genuine duplicate inside an
inline-flow `defaults:` still gets it (structural identity preserved):

```console
$ rr cf259 check      # defaults: {…} on line 1, duplicate id in items: on 7
ERROR  items/log/dup.yaml:7 [LOG-DUP-001] — duplicate id 'LOG-DUP-001'
       (also defined at items/log/dup.yaml:3)
```
No spurious "this file's defaults" text on the top-level repeat. **FIXED.**

### 1.9 #261 — one canonical image src, shared by the hash and render passes

An item body citing an image whose filename contains `&`, beside a real file
in the item's own directory, builds clean and publishes; the render and hash
passes agree. The run-7 class (hash covered `a&b.png`, render said
`a&amp;b.png` "does not exist", no published copy) is gone:

```console
$ rr cf261 build            # body: ![board](a&b.png) ; file items/log/a&b.png
8 items, 0 errors, 1 warnings
$ find _site/assets -name '*a&b*'
_site/assets/items/log/a&b.a7c3b756173296d4.png
$ grep -o '<img[^>]*src="[^"]*"' _site/log-pwr-001.html
<img src="assets/items/log/a&amp;b.a7c3b756173296d4.png"
```
The published leaf carries the raw `&`; the HTML attribute carries the correct
escaped spelling of that same file. A genuinely missing image is still reported
(now with a helpful hint):

```console
$ rr cf261b build           # ![missing](a&b.png) with no such file
ERROR  items/log/regulator.md:2 [LOG-PWR-001] — image src 'a&b.png' does not
       exist (no site.assets directories are declared to search)
```
**FIXED.**

### 1.10 #258 — a negative recorded `page_count` is a lockfile refusal

A citation lockfile recording a negative `page_count` is refused consistently
across `check`, `build`, and `fetch` (was accepted by some paths). Refusal
names the citation and the field. **FIXED.**

### 1.11 #252 — keys restore judges baseline content against the post-restore state

Restoring a **linked pair** together succeeds and resolves the owner's link;
the owner is no longer falsely refused for its (in-batch) keyless target. A
self-contained two-item project (a log `constrained_by:` a bound), keys then
corrupted on disk:

```console
$ rr pair keys restore LOG-PWR-001@bj7wnqr7j2r
refused:
  restored project would still have build errors -- fix them or supply all lost
  keys in one command
  ERROR  items/log/l.yaml:3 [LOG-PWR-001] — constrained_by points at key
         '7ywkmj6rm7k' (labelled BND-IFC-001), which no item declares … run
         `refdes keys restore BND-IFC-001@7ywkmj6rm7k --dry-run` …
$ rr pair keys restore LOG-PWR-001@bj7wnqr7j2r BND-IFC-001@7ywkmj6rm7k
restored LOG-PWR-001: zzzzzzzzzzz -> bj7wnqr7j2r
restored BND-IFC-001: zzzzzzzzzzz -> 7ywkmj6rm7k
changed files: items/log/l.yaml
$ rr pair check
2 items, 0 errors …
```
The owner-alone refusal is the correct "supply all lost keys in one command"
keyless-target guard (not the old bug); the pair restores and post-check is
clean. Owner-alone with a genuinely keyless target outside the batch is still
refused by design. **FIXED.**

### 1.12 #242 — a non-UTF-8 import artifact is a clean read error, not a traceback

Downstream imports an upstream built `items.json`. Corrupting the artifact
gives a clean read error naming the import and the artifact, exit 1, for
non-UTF-8, invalid JSON, and a directory at the artifact path:

```console
$ rr down check     # items: …/up/_site/items.json (leading 0xff 0xfe bytes)
ERROR  <project> — import 'platform': could not read …/items.json: 'utf-8'
       codec can't decode byte 0xff in position 0: invalid start byte
exit=1
$ … items.json = "not json {"
ERROR  <project> — import 'platform': could not read …/items.json: Expecting
       value: line 1 column 1 (char 0)
$ … items.json is a directory
ERROR  refdes-project.yaml — import 'platform': no artifact at …/items.json.
       Build the upstream project first, or fix the path.
```
The sibling `.refdes/` store-decode class (#212 follow-up) is library-gated;
the author-reachable capture of a corrupt object with nothing to write is the
idempotent no-op, which is correctly unaffected (`exit 0`). **FIXED.**

### 1.13 #247 — a file created new by `atomic_write_text` gets the umask default

New files follow the kernel umask (the lone 600 that a group-shared checkout
can't read is gone). New `.refdes/schema.json` under two umasks:

```console
$ (umask 002; rr cf247 check)   →  664 .refdes/schema.json
$ (umask 022; rr cf247 check)   →  644 .refdes/schema.json
```
Existing files keep their mode; only newly created files get the default.
**FIXED.**

### 1.14 #238 — the sealing opt-back-in note prints once, not on every run

A `refdes-schema.yaml` that opts a type back into build sealing prints the note
on the first writable run, then stays silent (state in
`.refdes/sealing-optin.json`); a set change re-prints; a corrupt record
self-heals. A read-only run is silent (it can't record), and the documented
`-v` remedy prints it:

```console
writable run#1: 1     writable run#2: 0
state: {"opted_in": ["log"]}
--no-write (silent): 0     --no-write -v (prints): 1
```
The read-only silence is the documented design (a read-only tree can't write
the opt-in record; `docs/design-log.md` says pass `-v`), not a defect.
**FIXED.**

### 1.15 #243 — `ls --keys` and `thread --json`/`--keys` print the surrogate key

`ls --keys` adds a key column between id and type (plain `ls` is unchanged);
`thread --keys` prints composite ids in the header; `thread --json` puts the
key on every entry:

```console
$ rr cf243 ls --keys
BND-THM-001  279d8npt6bd  bound        Board power density
LOG-PWR-001  kjkhb1pcb1b  log          3V3 rail regulator topology
$ rr cf243 thread LOG-PWR-002 --keys
Thread: LOG-PWR-002@jbd5f2746sw -> LOG-PWR-003@n9jyswzfxyj  (one tip)
$ rr cf243 thread LOG-PWR-002 --json | jq -c '.entries'
[{"entry":"LOG-PWR-002","key":"jbd5f2746sw"},
 {"entry":"LOG-PWR-003","key":"n9jyswzfxyj"}]
```
**FIXED.** (See F2 for the one branch an author can't reach.)

---

## 2. Daily driver

Wrote the 8-item project by hand (3–4 log entries with `satisfies` /
`constrained_by` / `addresses` / `amends` links, a `calc` block, a bound
`check`), built, and read the HTML. The flow is clean end to end.

- `refdes id` → minted keys, rewrote references, allocated REQ ids, exit 0.
- `refdes check` → "1 requirement(s) satisfied but not verified" warning,
  0 errors.
- `refdes build` → green; `log-pwr-001.html` renders the `losses` calc block
  (`P_diss → 0.1224 W`, `P_dens → 0.0972 W/in²`) with a pass badge on `P_dens`
  against `BND-THM-001`; `summary.html` lists it with margin.

The only friction is F1 below: the first read command (`ls`) prints
"(rewrote N reference(s) while loading)" and writes the tree.

---

## 3. Findings summary

| # | Severity | Finding |
|---|---|---|
| F1 | nit | A read-looking command (`ls`) writes the item files (surrogate-key expansion) and prints "(rewrote N reference(s) while loading)" / "(minted N key(s) while loading)". Writable-load is documented design, so this is a note; the surprise is that the side effect is silent-to-plain in the docs' `ls` example. §2 |
| F2 | nit | The #243 `ls --keys` zero-width branch ("no row has a key → no column, byte-identical to plain `ls`") is unreachable through the CLI: key minting fires on every load, so a key-stripped project minted 3 keys on the first `ls --keys`. The rule is code-true; an author can't observe it. §1.15 |
| F3 | nit | The #254 `remove_link` fix has no CLI surface (serve-editor HTTP only). Exercised by driving `patcher.patch_item(text, ref, RemoveLink(…))` — byte-for-byte the editor's per-op call. Method note for future runs, not a product issue. §1.6 |

No B-class (bug) findings. All 15 author-facing fixes in `885e9e6..f33efa4`
are FIXED. Out-of-scope: #246 (log-only), #251 (audit/test nits), #263
(latent render CRLF loss, reproduced and left as design).

---

## Appendix — reproduction

- CLI: `PYTHONPATH=<worktree>/src <venv>/bin/refdes` (the plain venv console
  script resolves to the main checkout; `PYTHONPATH` re-points it at this
  worktree — verified via `refdes.cli.__file__`). Verified on this branch's
  tree, Python 3.13.
- `_pristine` = `refdes init` (hardware@3) + the 8-item set described in §2.
  Sweep cases are fresh copies with one edit each.
- Consolidated repro scripts (author-side, `.scratch/` is gitignored):
  `repro.sh`, `repro2.sh`, `repro3.sh` reproduce §1.1–§1.15 from `_pristine`
  with the same single edits quoted inline in each section. The
  #242/#247/#252/#257/#290/#254 cases also need, respectively: an upstream
  built `items.json` (then corrupted), a chosen `umask` in a subshell, a
  self-contained 2-item project under `git init` (bound status `active`,
  log status `accepted`), four broken item files + one pending item, a bad
  rename-plan section, and a full `items:`-shaped source for
  `patch_item`. The #261 image is a 1×1 PNG.
- The #254 sweep drives `patcher` in-process (no CLI surface); no serve token
  is reproduced anywhere.
