# User-simulation release gate — run 6a (run 5's carry-forward + the upgrade path)

Run 6a of the standing gate, scoped per `.scratch/TASK.txt`: re-test every
run-5 finding on current main (`374a4aa`) by re-running run 5's *original
scenario*, answer B1's general question as a list from `refdes schema`, and
run the upgrade path from `3010883` (run 5's tree) to main. Run 5 was at
`3010883`; the delta is `git log --oneline 3010883..374a4aa`.

**Method, unchanged:** documented surfaces only — `docs/`, `--help`, real CLI
invocations, real HTTP — and the original scenario re-run rather than the fix
read. Reported version: `refdes 0.5.0` (`refdes --version`, on both `3010883`
and `374a4aa` — §3).

Harness: `.scratch/rr <projectdir> <args…>` cd's into the project and runs
`PYTHONPATH=<worktree>/src <venv python> -m refdes.cli "$@"`, with
`/home/jorb/work/venv-refdes/bin/python`; `.scratch/rr-old` is the same against
`.scratch/old/src` from `git archive 3010883 src`. Every synthetic project is
under `.scratch/run6a/`, one copy per sweep, all content synthetic. No git
commands inside a sweep directory, nothing outside the worktree, no recursive
deletes, `serve` stopped by PID. Nothing under `src/`, `tests/`, `docs/` or
`items/` was modified.

Out of scope by instruction: the living-notes / task-pane surfaces (run 6b),
VS Code as an application, real vendor PDFs.

---

## 0. Headline summary

**Run 5's findings: all closed on `374a4aa`.** B1–B5 and F1–F8 were each
re-tested by re-running run 5's *original scenario* (§1), not by reading the
fix — every one reproduces as fixed, with the original command and the exact
output line recorded. B1's open question is answered as a list in §2 (34
list-shaped fields, element-by-element): the four mapping-shaped fields and
`list_file.items` validate their elements, so the B1 class is closed, and no
field shows a `check`-clean / `build`-traceback divergence any more. Run 5's
B3 (append-only protection lost silently) closed in the upgrade scenario it was
about: the edit is now warned with hash, seal file and remedy (§1, §3).

**The upgrade path from `3010883` is loud by design** (§3): both vocabulary
renames are exit-2 configuration errors that name the new spelling and the file
(`history:` → `on_change:`, `log` → `timeline`); the `standard upgrade` chain
refuses an ill-formed project with a clean rollback and an exact remedy, and
carries a v2-pinned project's decisions into `log` with baselines, seals and
citation page counts intact; the verb/reserved-key collision is a config error
naming verb and key; the seal-era edit warning and `history migrate-seals` exist
and work.

**New findings, five:** B6 — `tags`/`refdes` accept a list element that is a
mapping silently (`check` clean, site renders a Python dict repr, `ls --tag`
matches); F9 — the link-verb version of the same element is caught, but as a
dangling-reference message quoting a loader dict with `'__line__'` in it;
**B7** — threads-4a's retired `decision` type strands the *default* `3010883`
project shape (v3 pin): a bare `unknown type 'decision'.` with no pointer to
the merge, and `standard upgrade --to 3` refuses the project by definition;
F10 — the sealing opt-back-in note prints on every load, not once;
F11 — `standard upgrade` is the only multi-file mutating command with no
`--dry-run`. Run 4's F3 (the duplicate-key diagnostic repointing references in
*other* files with no warning) is **still open**, reproduced (§4).

---

## 1. Re-test of run 5's findings on `374a4aa`

| # | Run-5 finding | Still reproduces? | Evidence (command + output line) | Fixed by |
|---|---|---|---|---|
| **B1** | `check` clean, `build` Jinja traceback on `options:` as a list of strings | **fixed** | log entry with `options:` as a list of strings: `refdes check` → `ERROR … options[0]: 'TPS62130 buck' is not an option -- an option is a mapping with a 'name' and, optionally, a 'verdict' and a 'because' …` exit 1; `refdes build` prints the same two errors, `build completed with errors (use --keep-going to exit 0)`, exit 1, **no traceback**, and the written site renders neither string (panel skips the bad entry). Run 5's other half — a half-written `_site/` with no summary — is gone: the summary line prints | #161 (`6251ab5`), fragment `decision-options-list-of-strings.fixed.md` |
| **B2** | `revise` on a tree with **one** read-only item file reports a structured link as a prose mention and exits 0 | **fixed** | stamped `r1`, `prefixes: {REQ-PWR: NEED-PWR}`, `chmod a-w items/log/regulator.md` (its `satisfies:` is a composite link): `refdes rename rename.yaml` → `refused: cannot write items/log/regulator.md (read-only tree?) -- no item file was rewritten and no hash was carried forward, so the tree is exactly as it was found. …` + `rolled back.`, **exit 1**, and `items/requirements/power.yaml` still reads `REQ-PWR-001`. The legitimate prose-only case is unchanged (mentions named, exit 0) | #163 (`3ade380`), fragments `revise-readonly-reference-file.fixed.md`, `revise-refresh-refusal-rollback.fixed.md` |
| **B4** | `key deleted since baseline` printed twice, once ERROR once WARNING, byte-identical | **fixed** | stamped `r1`, deleted `key: nvaeqzs6g9a` from `items/bounds/thermal.yaml`: `refdes check` prints `ERROR … key deleted since baseline 'r1': was 'nvaeqzs6g9a', now no key is declared.` **once**, then two *distinct* consequential dangling-link errors naming the files that reference it — one finding, one line | #165 (`086dcc2`), fragment `deleted-key-double-count.fixed.md` |
| **B5** | retired id does not resolve in `/api/item/<ref>` (hover data source) | **fixed** | `refdes serve --no-open --port 8733`, item `REQ-PWR-002` with `former_ids: [REQ-PWR-007]`: `curl -H "X-Refdes-Token: $T" … /api/item/REQ-PWR-007` → `{'id': 'REQ-PWR-002', 'former_ids': ['REQ-PWR-007'], 'key': 'q432vshabxe'}` (run 5: `{"error": "no item matches 'REQ-PWR-007'"}`). Serve stopped by PID. Case: lowercase matches nothing for live ids too, so the API's case rule is unchanged — no new nit | #165 (`086dcc2`), fragment `retired-id-serve-lookup.fixed.md` |
| **F1** | `audit` prints `ok hash-only` identically for pages-verified, over-threshold, and unreadable-as-PDF | **fixed** | same project, three citations over a local origin. Lockfile `page_count_error:` → `pages unchecked hash-only cited by CMP-001` **plus** the indented reason (`the pages could not be counted, so no cited page number was checked: counting a document's pages failed: pypdf could not read the PDF: …`); `page_count: 8` → `ok hash-only`; the 101 MB over-threshold fetch → `ok hash-only`. The three shapes are no longer one line. Residual nit, not run 5's F1: a `page:` the lockfile knows is out of range (`page 99 … has 8 page(s)`, a `check` WARNING) is not echoed in audit's citation block | `audit-pages-unchecked.fixed.md`, `audit-uncomparable.fixed.md`, `audit-unpinned-not-hash-only.fixed.md` |
| **F2** | pypdf's bare `EOF marker not found` on stderr with no context | **fixed** | `refdes fetch --update --path http://127.0.0.1:8811/bad.pdf` with stderr redirected to a file: **one** line (`wc -l` = 1), `grep -c "^EOF marker not found"` = **0**; the reason is inside refdes's own warning — `… counting a document's pages failed: pypdf could not read the PDF: Stream has ended unexpectedly (EOF marker not found). The page numbers cited for … are not checked: confirm that … really is a complete PDF … then run 'refdes fetch --update --path …' to count its pages` — reason, cause and command, all in one place | `pypdf-bare-stderr-line.fixed.md` |
| **F3** | the opt-back-in `sealing: build` overlay changes append-only semantics and reports nothing | **fixed** | `refdes-schema.yaml` with `types: log: sealing: build`, first `refdes check` → `note: refdes-schema.yaml opts the 'log' type back into build sealing -- an edit to a sealed entry is a build error again, not the history-backed 'edited after captured' warning`; semantics confirmed (`build` writes `.refdes/log-seal.yaml`, a real content edit to the sealed entry is the original `append-only … modified since it was sealed` ERROR at exit 1). Nit: the note prints on **every** load, not once (see §4) | #175 (`8ff0cc8`), fragment `sealing-optin-overlay-note.added.md` |
| **F4** | `edited after captured` carries no remedy and no docs URL | **fixed** | `history capture LOG-PWR-001`, rewrite the `summary:`, `refdes check` → `WARNING … LOG-PWR-001: edited after captured -- current semantic content differs from the snapshot in captured event 460d9466-…. If the edit was a correction, revert it and append a new entry with `amends: [LOG-PWR-001]` instead; otherwise there is nothing to do. See https://squishiba.github.io/refdes/troubleshooting.html#the-design-log.` — remedy restored, URL added | `edited-after-captured-remedy.fixed.md`, `edited-after-captured-remedy-scope.fixed.md`, `append-only-reseal-hint.fixed.md` |
| **F5** | `check --help` asserts "an entry that has never been built has no append-only protection at all", false for the history-backed `hardware@3` log | **fixed** | `refdes check --help` now splits the sentence: "a `sealing: build` type is sealed only once 'build' has run over the entry, so an entry that has never been built has none … while a `sealing: history` type -- the bundled hardware@3 `log` -- is never sealed at all, and is protected instead by the snapshot 'refdes history capture' writes into '.refdes/history/'" | #175 (`8ff0cc8`), fragments `check-help-sealing-split.fixed.md`, `check-help-unsealed-no-protection.fixed.md` |
| **F6** | `check --refresh --allow-unreachable` prints the `could not refresh <url>` line twice | **fixed** | origin stopped, two citations of `http://127.0.0.1:8811/manual.pdf`, `refdes check --refresh --allow-unreachable` with stderr redirected: the "could not refresh" line appears **once** (`grep -c` = 1), merged with the flag advice — `could not refresh http://127.0.0.1:8811/manual.pdf: <urlopen error [Errno 111] Connection refused> -- upstream drift was NOT verified for it -- drop --allow-unreachable to fail the run on this instead` — and the count-only summary is the second line | `refresh-unreachable-said-once.fixed.md` |
| **F7** | an unknown key **inside** a `checks:` entry is accepted with no diagnostic | **fixed** | `exrta: typo of extra` added to a `checks:` entry → `WARNING items/log/regulator.md:14 [LOG-PWR-001] — unknown key 'exrta' in a checks: entry -- it holds only 'value' and 'against', and this one is ignored. …` from `check` and `build`, `5 items, 0 errors, 3 warnings` | #168 (`d10ff69`), fragments `checks-entry-unknown-key.fixed.md`, `config-unknown-keys.fixed.md` |
| **F8** | three wordings of the unknown-key diagnostic; the keyless-live-item variant omits `refdes keys restore …` | **fixed** | same repro as B4: the keyless-live-item variant now reads `… A live item labelled BND-THM-001 declares no key. … If it is the same item, run `refdes keys restore BND-THM-001@nvaeqzs6g9a --dry-run`, then repeat without --dry-run …` — one wording, command included | #169 (`75e8782`), fragment `unknown-key-one-wording.fixed.md` |
| **B3** | upgrade removes append-only log protection silently | **fixed** (in the upgrade scenario it was about) | a `3010883`-built tree carrying `.refdes/log-seal.yaml` (the §3 project), edit the sealed log entry, `refdes check` on main → `WARNING … LOG-PWR-001: edited while uncaptured -- the current content no longer matches the hash 77becdd96d01cc5f recorded in .refdes/log-seal.yaml, and nothing in .refdes/history/ holds a snapshot of this entry, so the edit leaves no trace. Run `refdes history capture LOG-PWR-001` to record the current text; …` (full text §3); capture clears it; `history migrate-seals` writes the marker events idempotently. Scope note: a warning, not a gate — release still stamps unless `release_gate:` is configured, with the `captured_edits` gate item available. On a tree with **no** seal record at all (never built under sealing), editing stays silent, as documented | #166 (`f12fa95`), fragment `uncaptured-log-edit-warning.added.md` |
| run-4 **F3** | the duplicate-key diagnostic repoints references in other files with no warning | **still open** — see §4 | composite reference silently repointed at the surviving item | — |

---


## 2. B1's general question: every list-shaped field

Run 5 §11.1 asked: *for every list field, is a list of scalars validated the
way a scalar is?* Answered as a list, built from the emitted schema, not from
one finding.

`.scratch/rr <base> schema --json` on a `hardware@3` project yields 34
list-shaped `(type, field)` pairs. De-duplicated by field kind:

| shape | fields |
|---|---|
| list of **mappings** | `checks` (log, component), `citations` (log, component), `options` (log), `tasks` (log) |
| list of **strings** | `tags` (all 6 types), `refdes` (component), and the link verbs: `addresses`, `amends`, `alternate`, `blocked_by`, `constrained_by`, `derives_from`, `drop_in`, `follows`, `governed_by`, `part_of`, `refines`, `satisfies`, `selects`, `supersedes`, `verifies` |
| special | `list_file.items` (bulk list file: a list of mappings) |

Method (`.scratch/run6a/drive_listfields.py`, `.scratch/run6a/drive_scalarform.py`
— each case is a fresh `cp` of a `refdes init` skeleton with one item file, then
`rr <case> check` and `rr <case> build`):

| field shape | bad element | `check` | `build` | verdict |
|---|---|---|---|---|
| `checks` (log, component) | list of strings | `ERROR … each checks: entry needs 'value' and 'against'`, exit 1 | same errors, exit 1, no traceback | validated |
| `citations` (log, component) | list of strings | `ERROR … citations[0]: each citation needs a 'path' or 'item'`, exit 1 | same, exit 1 | validated |
| `options` (log) | list of strings | `ERROR … options[0]: 'plain string' is not an option -- an option is a mapping with a 'name' …`, exit 1 | same, exit 1 | **validated — B1 closed** |
| `tasks` (log) | list of strings | `ERROR … tasks[0]: 'plain string' is not a task -- a task is a mapping with an 'id', a 'text', and a 'state' …`, exit 1 | same, exit 1 | validated |
| `list_file.items` | scalar entry in `items:` | `ERROR items/one.yaml:1 — list entry must be a mapping, got str`, exit 1 | same, exit 1 | validated |
| link verbs (15) | list containing a mapping | `ERROR … satisfies points at "{'name': 'not-a-string', 'verdict': 'x', '__line__': 6}", which does not exist …`, exit 1 | same, exit 1 | caught, **by the dangling-reference rule, and the message leaks a Python repr incl. `'__line__'`** (F9) |
| `tags` (all 6 types) | list containing a mapping | `1 items, 0 errors, 0 warnings`, **exit 0** | `1 items, 0 errors, 0 warnings`, **exit 0**, site written | **not validated** (B6) |
| `refdes` (component) | list containing a mapping | `1 items, 0 errors, 0 warnings`, **exit 0** | exit 0 | **not validated** (B6) |

For contrast, the scalar form *is* refused everywhere, which is the asymmetry
the question was about: `tags: one plain string` → `ERROR … field 'tags' is a
list field, but it was given a string … write it as a list`, exit 1, on every
type; and `options: TPS62130 buck` → the `field 'options' is a options field …`
error, exit 1. So: a scalar for a list is refused by name on every list field;
a **wrong-typed element inside** a list is refused on the four mapping-shaped
fields and on `list_file.items`, and silently accepted on the string-shaped
fields.

**No field on `hardware@3` shows the B1 divergence any more** — I found no
field where `check` is clean and `build` tracebacks, and no field where the two
disagree. Both B6 and F9 below are silent-accept / message-quality findings,
not `check`-vs-`build` divergences.

---


## 3. Upgrade path: a `3010883` project on `374a4aa`

Method: `.scratch/old/src` from `git archive 3010883 src`, driven by
`.scratch/rr-old`. Built the project **entirely with `3010883`**
(`.scratch/run6a/upg2`): `refdes init` (which at `3010883` writes
`standard: version: 3`; pinned down to `version: 2` for the v2 vocabulary),
requirements/bounds/tests in v2 spelling (`text:`, `title:`, `limit: "<= 125
degC"`), a `decision` with `title:`/`status: accepted`/`options:`/`satisfies:`,
a component with a `datasheets:` citation carrying `page: "4"` over a real local
PDF, a `log` entry with `records: [DEC-PWR-001]`, the **old** project setting
`history: {default: log}`. Then `refdes id`, `fetch --update`, `build`,
`revision r1` — all on the old tree: 7 items, `.refdes/log-seal.yaml`,
`.refdes/baselines/r1.yaml`, `.refdes/citations.yaml` with a `page_count`.
`refdes --version` prints `refdes 0.5.0` on **both** trees — the delta is
invisible in the version string (run 5's nit, unchanged).

Current main (`rr`) over the same tree, one change at a time:

| Breaking change (fragment) | First run on `374a4aa` | In-product signal / remedy |
|---|---|---|
| `history:` → `on_change:` (history-config-on-change) | every command — `check`, `ls`, `audit`, `build`, `release` — exits 2 with `configuration error: refdes-project.yaml: history: was renamed to on_change: -- it set the default on_change mode, not the history store; rename it in refdes-project.yaml` | loud hard stop naming the new key and the file, exit 2 (`$?` verified); no docs URL in the line |
| on_change mode `log` → `timeline` (vocab-p9-log-to-timeline) | on the **v2 pin** the value `log` is accepted unchanged (`check` clean). `refdes standard upgrade --to 3` refuses: `v2 -> v3: refused: rewritten project no longer loads: refdes-project.yaml: on_change.default: on_change mode 'log' was renamed to 'timeline' -- the mode marks a change for the future field-level timeline, not the \`log\` item type; rename it` — and the refusal is **clean**: config, items, baselines all byte-identical afterwards. Hand-rename the one line (`timeline` is accepted on the v2 pin too) and re-run: `v2 -> v3: changed 5 file(s): … baselines carried forward: r1 … seals carried forward: (base) … upgraded to v3.` | the migration names the exact key, value, old and new spelling; the two hand-renames (`history:`→`on_change:`, `log`→`timeline`) both precede the chain, each named by a hard error. Friction, not a bug — recorded so the release notes lead with it |
| `decision` merged into `log` (threads-4a-decision-merge) | after the chain: `DEC-PWR-001` is `type: log` with `title:` → `summary:`; the log entry's `records: [DEC-PWR-001]` was rewritten to `follows: [DEC-PWR-001@csh7sbekzgr]` (key-expanded, matching P4 anchoring); `check` clean; `revision r2` stamps; `release v1.1` runs the gate list (incl. `skipped captured_edits` — the opt-in B3 gate); `fetch` → `skipped docs/manual.pdf sha256=8f5443a56224… hash-only` (page_count carried). **The v3 pin is the gap — B7, §4** | for v2 pins: the chain carries it, cleanly. For v3 pins: none |
| verb named a reserved key (verb-named-reserved-key) | project schema `link_types: {id: {inverse: id_of, …}}` loads clean at `3010883` (`0 items, 0 errors, 0 warnings`, the verb unwritable on items); on main every command exits 2: `configuration error: link_types.id: the link verb 'id' collides with the engine's reserved front-matter key 'id' -- items spell id: for the engine's own reading, so this verb could never be written on an item; rename the verb` | exactly as the fragment claims: names the verb, the key it collides with, why, and the fix. No bundled standard verb collides, so only a project that declared one sees it |
| seal → history (the B3 pair) | the `3010883` build left `.refdes/log-seal.yaml`; on main, editing the sealed log entry and running `refdes check` prints `WARNING items/log/log-001.md:2 [LOG-PWR-001] — LOG-PWR-001: edited while uncaptured -- the current content no longer matches the hash 77becdd96d01cc5f recorded in .refdes/log-seal.yaml, and nothing in .refdes/history/ holds a snapshot of this entry, so the edit leaves no trace. Run \`refdes history capture LOG-PWR-001\` to record the current text; an edit after that is reported as edited after captured.` `refdes history capture LOG-PWR-001` clears it (grep count 0 after); `refdes history migrate-seals` → `legacy-seal marker for LOG-PWR-001 (.refdes/log-seal.yaml)` + `1 legacy-seal marker(s) written, 0 already present`, idempotent, seal file untouched | **run 5's B3 closed**: the silent rewrite is warned with hash, seal file and command, and the migration command exists |
| `revise` → `rename` (rename-replaces-revise) | `refdes revise --dry-run <mapping>` runs with identical behaviour; first stderr line: ``refdes revise` is now `refdes rename`; `revise` will be removed in the next minor release` | as claimed; the verb list in `refdes --help` shows `rename`, no `revise` |
| `freeze` → `anchor` (follows-freeze-to-anchor) | `refdes keys adopt --dry-run` → `would anchor 0 follows reference(s) at their thread tips` — the word `freeze` is gone from the adoption report | as claimed; nothing on disk to change |
| thread derived block (thread-derived-grouping) | `refdes thread LOG-PWR-001` → `Derived (auto clears when fixed):` with a `Coverage:` heading and rows `REQ-PWR-002  unverified` — kind column gone | as claimed |
| `index` help (index-help-names-its-payload) | `refdes index --help`: "Print the resolved project as one JSON document on stdout, rendering no HTML: the machine-readable payload the VS Code extension and other editor tooling read… Always present: title, version, coverage, types, items (with their fields, links, backlinks, calcs, checks, content hash and source file:line), next_ids and diagnostics; boards and workspaces when the project declares those registries, threads when it has…" | as claimed |

Overall: every breaking change in the range is a hard, named stop for a `3010883`
project — the two vocabulary renames (exit 2, naming new spelling + file), the
migration chain (refuse-with-clean-rollback + exact remedy), the seal→history
warning (hash + file + command), the verb collision (names verb + key). The one
silent-ish path is B7 below.

---

## 4. Findings in full

### B7 — a v3-pinned project with `decision` items has no in-product migration path (new, upgrade pass)

`3010883`'s `refdes init` writes `standard: version: 3` **by default** (observed
in the `rr-old` init above), and hardware@3 **at `3010883`** shipped `decision`
(its v3 `base.yaml` has `records: [decision]`). So the default project created
at `3010883` and pinned to v3 is exactly the shape threads-4a retires — and it
is the one shape the migration chain cannot reach:

```console
$ printf -- '---\nid: DEC-PWR-001\ntype: decision\ntitle: Regulator choice\nstatus: accepted\n---\nBody.\n' > items/d.md   # v3-pinned project
$ rr <project> check
ERROR   items/d.md:2 — unknown type 'decision'.
0 items, 1 errors, 0 warnings
$ rr <project> standard upgrade --to 3
configuration error: project is already at hardware@3, not below the requested --to 3
```

The load error is a bare `unknown type 'decision'.` — it does not name the
merge, the `title:`→`summary:` field move, the `records:`→`follows:` link
rewrite, `standard upgrade --to 3` (which refuses this project by definition),
or the docs. For a v2-pinned project the chain carries all of it (§3); for the
v3 pin the repair is docs-only. Expected: the error names the merge and points
at the docs page (and, if feasible, a hand-migration recipe), the way the
`on_change`/`timeline` renames name their fix inline.

### B6 — `tags` and `refdes` accept a list element that is a mapping

```console
$ cat > items/one.md <<'EOF'
---
id: CMP-001
type: component
title: TPS62130
part_number: TPS62130DRRT
tags:
  - power
  - name: not-a-string
    verdict: x
refdes:
  - U1
  - name: also-not-a-string
    verdict: y
---

Body.
EOF
$ rr <case> check    # first load also prints (minted 1 key(s) while loading)
1 items, 0 errors, 0 warnings          # exit 0
$ rr <case> build
1 items, 0 errors, 0 warnings          # exit 0, site written
$ rr <case> ls --tag x
CMP-001  component  TPS62130
```

(A bulk list file takes the same items under a top-level `items:` key; a bare
YAML list is refused — `ERROR items/one.yaml:1 — list file must be a mapping
with an 'items:' key` — so the front-matter form above is the repro.)

The built page renders the tags row as a Python dict repr —
`{&#39;name&#39;: &#39;not-a-string&#39;, &#39;verdict&#39;: &#39;x&#39;}`
(HTML-escaped), and `refdes ls --tag x` **matches** the item. Expected, mirroring
the four mapping-shaped fields: `tags[0]: is not a string — a tag is a plain
string` at exit 1 from `check` and `build`. `refdes` (component) behaves the same.
The scalar-form asymmetry is the proof the rule exists and is not applied:
`tags: one plain string` → `field 'tags' is a list field, … write it as a list`,
exit 1, on every type.

### F9 — a link verb given a mapping element is reported as a Python dict repr, `'__line__'` included

```console
$ # same case shape, but on a link verb:
$ sed -i 's/^tags:/satisfies:/' items/one.md    # both list elements stay
$ rr <case> check
ERROR   items/one.md:2 [CMP-001] — satisfies points at 'power', which does not exist -- …
ERROR   items/one.md:2 [CMP-001] — satisfies points at "{'name': 'not-a-string', 'verdict': 'x', '__line__': 8}", which does not exist -- …
1 items, 2 errors, 0 warnings                    # exit 1
```

The first error is the converted plain `power` tag — an honest dangling ref;
the finding is the second line.

The element *is* caught (exit 1, `check` and `build` agree), but as a
dangling-reference message quoting an internal loader dict with its `'__line__'`
key. Expected: name the element (`satisfies[0]`) and say it must be a string —
the way `citations[0]: each citation needs a 'path' or 'item'` already does for
the mapping-shaped fields.

### F10 — the sealing opt-back-in note prints on every load, not once

F3's fix is real (see §1) and prints `note: refdes-schema.yaml opts the 'log'
type back into build sealing -- …` — on **every** `refdes check`/`build` of a
project carrying the overlay (two consecutive runs, both print it), permanently.
Expected: print on first write, like the `.refdes/schema.json … refreshed` note
which appears exactly once. A permanent one-liner in every CI check log trains
people to skim notes.

### F11 — `standard upgrade` is the one multi-file mutating command with no `--dry-run`

```console
$ rr <project> standard upgrade --to 3 --dry-run
refdes: error: unrecognized arguments: --dry-run      # argparse exit 2
```

`standard upgrade` rewrites every item file, bumps `standard.version:` and
relabels baseline/seal records in place (its own help: "rewrites item files …
carries content hashes forward in every stamped baseline and seal"). `keys
adopt`, `keys restore`, `rename`, `calc-rewrite` — the sibling mutating
commands — all have `--dry-run`; this one does not, so previewing a multi-file
rewrite on a stamped tree means `cp -r` by hand. Expected: `--dry-run` printing
the per-file change plan and exiting 0, like `keys adopt --dry-run`.

### run-4 F3 — the duplicate-key diagnostic repoints references in other files with no warning (still open)

```console
$ # items/requirements/power.yaml: REQ-PWR-002's entry gains a second `id:` line
$ sed -i 's/^    body: The 3V3 rail shall supply 1.2 A continuous.$/    id: REQ-PWR-004\n    body: …/' items/requirements/power.yaml
$ rr <case> check
ERROR   items/requirements/power.yaml:16 [REQ-PWR-004] — duplicate key 'id' in one mapping (lines 14 and 16) -- YAML keeps the last, so 'REQ-PWR-002' is dropped for 'REQ-PWR-004'; …
(rewrote 1 reference(s) while loading)
$ grep -n satisfies items/log/regulator.md
8:satisfies: [REQ-PWR-004@q432vshabxe]     # was REQ-PWR-002@q432vshabxe — repointed at the surviving item
```

The composite reference in a **different file** is silently repointed at the
item that won the duplicate-key collision, on disk, on a plain `check`, and the
diagnostic's remedy ("put the '- ' back on its own line") protects only the
reporting file. Grepping the check output for the repointed file
(`grep -c 'regulator.md'`) yields **0** matches — the repointed file is never
named. Expected: the duplicate-key error (or an added warning) names the
file(s) whose references were repointed and says the rewrite
already happened on disk.


---

## Appendix — how to reproduce this run

Harness, once per worktree (all paths under the worktree; nothing in `/tmp`):

```console
$ V=/home/jorb/work/venv-refdes/bin/python; W=<worktree>
$ cat > .scratch/rr      # PYTHONPATH=$W/src  $V -m refdes.cli "$@"   (in $1)
$ cat > .scratch/rr-old  # same, PYTHONPATH=$W/.scratch/old/src
$ mkdir -p .scratch/old && git archive 3010883 src | tar -x -C .scratch/old
```

Per sweep: `cp -r .scratch/run6a/_pristine <case>` (pristine = a
`hardware@3` base project carrying REQ-PWR-001/002, BND-THM-001, LOG-PWR-001
(history-backed), CMP-PWR-001 with three PDF citations, TST-PWR-001), then
`$W/.scratch/rr $PWD/.scratch/run6a/<case> <cmd> …`. The base: `refdes init` →
`refdes new` five items → `refdes build` → `refdes revision r1`.

Local origin for the citation sweeps (§1 F1/F2/F6):

```console
$ python .scratch/run6a/mkpdf.py .scratch/run6a/origin      # manual.pdf, bad.pdf, noeof.pdf
$ (cd .scratch/run6a/origin && python -m http.server 8811 --bind 127.0.0.1) &  # note the PID
```

`§2` is `.scratch/run6a/drive_listfields.py` / `drive_scalarform.py` (fresh
`refdes init` skeleton + one item file per case). `§3` is `.scratch/run6a/upg2`:
`rr-old` init (v2 pin) → v2-spelling items + `history: {default: log}` → `id`
→ `fetch --update` → `build` → `revision r1`, then the same commands through
`rr`, plus `standard upgrade --to 3` before/after renaming the one mode line,
and `history capture LOG-PWR-001` / `history migrate-seals` /
`keys adopt --dry-run` / `thread LOG-PWR-001` / `release v1.1` on the result.

`refdes serve` was run as `rr <case> serve --no-open --port <p> --token-file <f>`
with the PID recorded and killed by PID (`§1 B5`), never `pkill`.
