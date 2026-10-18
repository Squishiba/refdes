# User-simulation release gate — run 11 (12bbf6b..main as an author)

Report-only: no code/docs/test changes. All claims produced by running this
branch's code (`PYTHONPATH=<worktree>/src … python -m refdes.cli`, refdes
0.5.0, Python 3.13) in fresh projects under `.scratch/run11/`, each from
`refdes init` (hardware@3). One harness: `.scratch/rr <proj> <args…>` (cd's
inside the script); `RR_SRC=.scratch/old12bbf6b/src` repoints it at the
pre-delta src from `git archive 12bbf6b src | tar -x -C .scratch/old12bbf6b`
(§3).

Delta src commits (`git log --oneline 12bbf6b..main -- src/`): 39d4b26
(#331), 55d3a87 (#253), 1942740 (#332), 944afbb (#330), e95ac39 (#328),
0ba1c45 (#244), 84ceaa9 (#326), 6d104be (#323, run 10), 037d263 (#324,
docs), 18c5d75 (#322, run 10). Run 10 covered #322/#323; this run re-sweeps
#332 (which extends #322) and #330 (which fixes #323's upgrade case), and
goes deep on #331, #328, #326/#329, and the serve lane (#244, #253).

## 0. Headline summary

Run 10's findings all came back as fixes, and every one of them holds as
documented. Four new findings, none a blocker: the fence work (#331/#332)
leaves one authored escape hatch; init's honesty about git has two edges;
the preview scope gate stopped one parameter short of its sibling.

| Fix | Verdict | Section |
|---|---|---|
| #331 `---` inside a fence no longer splits | holds — every fenced shape agrees across `check`/`build`/`ls`/`index`, byte-stable round-trips; R11-F1 is the one escape hatch | §1 |
| #328 `init` asks git about `.gitignore` | core holds — an author's negation stops the append; R11-F2 and R11-F3 are honesty gaps at the edges | §2 |
| #330 pre-#323 labelled capture reads clean | fixed exactly as scoped — upgrade direction silent, real edits loud; the downgrade direction unchanged (expected) | §3 |
| #332 inert-fence warning widened | all four run-10 gaps closed; ~30 spellings fired and stayed silent exactly as claimed, remedy verified end-to-end | §4 |
| #326/#329 `create/preview` workspace gate | every claim in both changelog fragments matched the live serve, message byte-for-byte; R11-F4 is the sibling parameter | §5 |
| #244 create rollback | refusal names the cause; destination sha256 identical, no id burned — both append shapes | §6 |
| #253 citations accept pair | happy/refused/sequence/accept-then-edit all leave `check` consistent; refusals byte-intact; stale revision a loud 409 | §6 |

- **R11-F1 (moderate)** — a fenced example whose *closing* fence line carries
  an info string (` ```yaml` … ` ``` yaml`) is unclosed markdown, so the
  `---` inside it splits: the inner front matter silently becomes a live
  phantom item, and `refdes id` mints a key *into the fenced example*. Same
  family as the fixed bug, one spelling left open; `check` reports
  `0 errors, 0 warnings`.
- **R11-F2 (low)** — `refdes init` prints "wrote .vscode/settings.json
  (gitignored ...)" when a git negation (`.vscode/*` + `!.vscode/*`) means
  the file is *not* ignored; `git status` shows it as untracked.
- **R11-F3 (low)** — creating a *new* project `.gitignore` skips the git
  coverage check, so a project nested inside a repo whose root already
  ignores `.refdes/` gets redundant lines written.
- **R11-F4 (low)** — the #326 gate covers `workspace` only:
  `create/preview?workspace=product-a&board=nosuchboard` answers 200 and
  points a scripted caller at `items/product-a/requirements.md` — run 9's
  R9-F3, one parameter over, while `/api/items` gates `board` strictly.

---

## 1. #331 — a `---` inside a fenced code block does not split the item

Base project: `REQ-PWR-001` list file; the swept file is a log whose body
pastes a front-matter example. Verdict column = what `refdes check` +
`refdes ls` + `refdes build` + `refdes index` agree on (all four agree in
every case below; `ls` prints no warnings, as before; `index`'s
`diagnostics` carries the new warning with file+line).

| Shape (authoring.md §"Several items in one file") | Result |
|---|---|
| ```` ```yaml ```` pasted front-matter example, inner id == the item's own id (R10-X1 shape) | 3 items (no phantom), `WARNING …md:12 — front matter inside a fenced code block is treated as example text; no action is needed if this is an example; if a real item was meant here, check for an unclosed earlier code fence.` exit 0; fenced `satisfies:` inert in `index` (`links: {}`) and renders as a `language-yaml` code block |
| `~~~yaml` fence, same content | silent split prevented, warning at the inner `---` line |
| Same fence in a **component** body and a **bound** body (`.md`) | warning fires in both, one per file, at the right line |
| Fence indented 2 spaces inside a list item; fence indented 4 spaces (markdown indented code block) | no split, no warning — nothing to warn about: an indented `---` never split (column-0 rule), so no phantom in either |
| Fence inside a blockquote (`> ```yaml`, `> ---`) | inert as a fence; the `---` lines are `> `-prefixed so they split nothing; 0 warnings (matches R10-F3's posture for #322) |
| Literal horizontal rule: `---` then prose | stays body text, 1 item, 0 warnings |
| `---` then a key-shaped line | splits into a real second item, 0 warnings (documented) |
| Unclosed fence, single-item file (`---` + keys inside, no closer) | splits as documented ("an unclosed opener protects nothing"): the fenced block parses as an item with no `type` → `ERROR …:13 — item has no 'type'` — loud |
| Unclosed fence in item 1, item 2's `---` pair protected by pairing with item 2's body-fence closer | item 2 is swallowed into item 1's body **with** the warning at item 2's opening `---` line — the "a vanished item is never silent" promise holds; the advice ("check for an unclosed earlier code fence") is exactly right for this case |
| Two items per file, no fences | 2 items, 0 warnings |
| List file `body: |` carrying ` ```yaml ` fences and `---` lines | unaffected (list files are YAML; the splitter does not apply), 0 warnings |
| Longer closer: `````markdown` wrapping a ` ```yaml ` example (inner closer inside) | the 3-backtick line does not close the 4-backtick fence; warning at the inner `---`, no phantom |
| Opener ` ```yaml `, closer ` ```` ` (longer run), then a real `---`+keys item | fence closes at the longer run; the real second item splits (3 items); warning for the fenced one |
| Fenced `---` followed by non-key prose (`this is prose, not a key`) | no warning, no split — the warning is keyed on a key-shaped line after, as stated |
| Closer with trailing space (` ``` ` + space) and `~~~ ` | treated as closing (2 items, warning at the fenced `---`) — **more lenient than authoring.md:107 "…with nothing after it"**, and in the safe direction |
| Closer with an info string (` ```yaml ` … ` ``` yaml `) | **R11-F1** |

Round-trip: the swept file in the canonical case is **byte-identical**
(md5) across `check`, `id`, `build`, `revision rev-a`, `keys adopt`,
`history capture LOG-PWR-001`, `calc-rewrite`, `stub-tests` — nine hashes,
one value. (The serve-editor save round-trip is in §6.)

**R11-F1 (moderate): a fenced example whose closing fence line carries an
info string is unclosed, so the pasted front matter becomes a live item —
silently, and with a `key:` written into the example.**

```console
$ cat items/pwr/LOG-PWR-001.md      # body: ```yaml … --- id: LOG-PWR-021 … --- prose ``` yaml
$ refdes check && refdes ls
3 items, 0 errors, 0 warnings
LOG-PWR-001  log          fenced example
LOG-PWR-021  log          phantom?          # from inside the fence
REQ-PWR-001  requirement  …
```

Expected: R10-X1's symptom (a pasted example minting a live item, listed by
`refdes ls`) is exactly what #331 exists to stop; a fence whose closer is
typed ` ```yaml ` (a real typo — the author mirrors the opener) is unclosed,
splits, and the fix is silent in this direction. Saw: a phantom item with a
fresh id is minted with **zero** diagnostics, and key minting writes
`key: 1ey7qpw96rj` **into the fenced example** (file lines 10-17 after
`check`):

```markdown
```yaml
---
key: 1ey7qpw96rj
id: LOG-PWR-021
```

The promise the commit makes is "a swallowed item can never be silent" —
the swallow direction is covered; the promote direction (R10-X1 proper)
gets no warning whenever the example's ids don't collide.

---

## 2. #328 — `refdes init` asks git about `.gitignore`

Ground truth for every case: `git check-ignore -v --no-index -- <path>` run
by hand, compared with what init appended (`wrote .gitignore (<list>)`) and
with `git status --porcelain`.

| `.gitignore` / environment | git verdict (hand-run) | init appended `.vscode/settings.json`? |
|---|---|---|
| `.vscode/*` + `!.vscode/*` (the DOC-REMEDY-018 shape) | negation wins → **not ignored** (status shows `?? .vscode/`) | **no** — the fix holds |
| `.vscode/` | ignored | no |
| `/.vscode` | ignored (dir → contents) | no |
| `**/.vscode/settings.json` | ignored | no |
| global excludesFile (`core.excludesFile`) naming `.vscode/settings.json` | check-ignore names the global file → ignored | no — git consulted for the global file too |
| bare `!.vscode/settings.json` | not ignored | no |
| all five init lines present | ignored | no line at all: init prints no `wrote .gitignore` (idempotent) |
| no git repo at all | n/a | yes (literal set, as documented) |
| CRLF `.gitignore` | ignored (via the entry init appended) | appended **in CRLF**, no LF island |

Re-init is idempotent in every case (0 `wrote .gitignore` lines on the
second run). Refusals are clean and pre-flight — the project marker, the
settings file and `.gitignore` all stay untouched, exit 2:

- read-only `.gitignore` (mode 444): `configuration error: cannot append to
  <abs>/.gitignore: file is not writable -- make .gitignore writable, or
  remove it, and run init again`
- unreadable (mode 000): `cannot read …: Permission denied -- make
  .gitignore readable, …`
- binary bytes: `… not valid UTF-8 text at byte 0 (invalid start byte) --
  .gitignore must be plain text; …`
- a **directory** named `.gitignore`: `… exists but is not a regular file
  -- refdes init refuses to start rather than write a project around it`

Two message/write-side gaps found:

**R11-F2 (low): the `wrote .vscode/settings.json (gitignored -- …)` line is
false exactly in #328's own cases.**

```console
$ printf '.vscode/*\n!.vscode/*\n' > .gitignore && refdes init
wrote refdes-project.yaml
wrote .vscode/settings.json (gitignored -- the yaml.schemas path in it names one checkout)
wrote .gitignore (.refdes/copies/, …)      # the vscode entry correctly NOT appended
$ git status --porcelain | grep vscode
?? .vscode/                                 # tracked-able: gitignored is false
```

Same in the bare-negation case. Expected: the note track the verdict init
just asked git for (init consulted git for exactly this entry —
`_gitignore_addresses`), e.g. "…(gitignored …)" only when git says ignored,
and something like "…(you chose to track it)" otherwise. Saw: the paren-
claim is hardcoded in the print (src/refdes/cli.py:2074-2078 — it keys on
"init wrote the file", never on the coverage answer), so the author who
deliberately tracks `.vscode/` is told their machine-specific absolute
schema path is gitignored when it is about to be committed.

**R11-F3 (low): creating a NEW `.gitignore` skips the coverage question, so
init writes lines git reports as already covered.** Repro (project is a
subdirectory of a repo; the repo-root `.gitignore` has `.refdes/`):

```console
$ mkdir proj && printf '.refdes/\n' > .gitignore
$ cd proj && refdes init | sed -n 3p
wrote .gitignore (.vscode/settings.json, .refdes/copies/, .refdes/schema.json, .refdes/sealing-optin.json, .refdes-write.lock -- not yours to commit)
$ git check-ignore -v --no-index -- .refdes/copies/      # from the repo root
.gitignore:1:.refdes/	proj/.refdes/copies/             # already covered
```

Expected per docs/cli-reference.md's "skipped for a path an existing
pattern already covers" + #328's "inside a repository git is the judge":
the four `.refdes/*` entries (and, with a root `.vscode/`, the vscode one)
are not needed. Saw: all five written. Cause: `_ensure_gitignore_entries`
append/asks git only on the existing-file path (src/refdes/scaffold.py:462
— `if not os.path.isfile(path): write_text(all entries)`). Benign for git
(the lines agree with the verdict), so: noise in the file and in the
printed list, not a behavior break.

---

## 3. #330 — a pre-#323 capture of a labelled fence no longer reads as edited

Old code from `git archive 12bbf6b src | tar -x -C .scratch/old12bbf6b`,
driven through the same harness with `RR_SRC=.scratch/old12bbf6b/src`. Item:
a log with prose + a ` ```calc id="log-e1" ` fence (three rows).

R10-F5 (the run-10 release blocker) is fixed, and the fix is exactly as
scoped in its changelog fragment:

| Step (capture done by the **pre-#323** code, checked by main) | check / audit |
|---|---|
| capture, edit nothing | `2 items, 0 errors, 0 warnings`; audit: `Entries edited after captured: (none)` — **the false warning is gone** |
| prose edit (add a word) | fires the `edited after captured` warning (1 match) |
| calc row edit (`p_in = 5.0 W` → `5.1 W`) | fires — rows are content |
| label rename `id="log-e1"` → `id="losses"` | silent |
| label removed (` ```calc `) | silent |
| label added back | silent |
| a **second** item captured by main's code in the same store (mixed events) | `3 items, 0 errors, 0 warnings`, audit `(none)` — mixing an old event and a new one in one store is clean |
| `refdes history redact LOG-E1 --confirm` | redaction event written (digest+id only, plus the Git-caveat note); check quiet afterwards, audit `(none)` |

An **unlabelled** fence captured by the old code stays byte-for-byte silent
under main (2 items, 0 warnings) — the pre-#330 digest guarantee is
undisturbed, matching run 10's forward-upgrade case.

The **reverse** split is unchanged, as expected for a downgrade: an item
captured by **main** warns under the **old** code's check with nobody
having edited it (1 warning), and a label edit under old code of a
main-captured item also keeps that warning. The pre-#323 code cannot know
the new digest; #330's fragment claims only the upgrade direction, so this
is noted, not a finding.

 With a colliding
id the author does get the pre-existing `duplicate id` error, which is why
the docs/checks.md paste (same id as the host item) is loud and a paste of
a *sample* item (`id: LOG-XYZ-001`) is not.

## 4. #332 — the inert-fence warning covers link verbs, `id`/`type`, blockquotes, escapes

All cases are one `log` item in the sweep-1 base project (two requirements
present). `check`/`build`/`index` were run on every case and agree; the
warning line names the fence's own opener in the file as written.

| Case (fixture under `.scratch/run11/`) | body shape | `check` |
|---|---|---|
| v1 | `satisfies:` link verb of the item's own type | fires, named `'satisfies' -- a link of type 'log'` |
| v2 | `id:` + `type:` keys | fires, `'id', 'type' -- keys only the front matter reads` |
| v3 | field + verb in one fence | one warning naming both, "nothing in the fence takes effect" |
| v4 | `checks:` field (the run-9 R9-F1 shape) | fires — #322 not regressed |
| v5 | fence escaped inside an outer ` ```text ` fence | **silent** (R10-F4 fixed) |
| v6 | fence inside an HTML comment | fires — and `build` escapes the comment (`&lt;!--`) so the fence *renders*, making the warning true |
| v7 | `satisfies:` fence on a `requirement` (not its verb) | silent — a real example, not the trap |
| v8, w6 | fence indented in a bullet / numbered list item | fires, opener line correct |
| v9 | `> ```yaml` blockquote fence | fires at the right line (R10-F3 fixed) |
| v10, v12, v13 | fence inside `~~~markdown`, an unterminated outer fence, after an unclosed fence | silent — the outer-fence rule, as markdown renders it |
| v14 | verb inside a list-file `body: |` | fires at the item's source line |
| v15 | `limit:` fence on a `bound` | fires — the warning generalizes past `log` |
| v16 | fence with `type: component` on a `log` | fires for `type` only, never for `component`'s fields |
| v17 | `verifies:` fence on a `log` (verb of `test`) | silent — a doc example |
| v18 | `> ```yaml` inside a list item | fires |
| w1 | whole file CRLF | fires — no off-by-one |
| w2 | ` ```yaml-session ` | silent (a tag running into a word char is not yaml) |
| w3, x2 | ` ```Yml `, ` ```YAML ` | fire (case-insensitive) |
| w4 | `>> ```yaml` nested quote markers | fires |
| w5 | `satisfies:` nested under a top-level key | silent (top-level keys only) |
| x1 | two yaml fences | two warnings, each naming its own opener |
| x2 | scalar fence, list fence, `status: [unclosed` | silent (must parse as a mapping) |

The remedy claim holds end-to-end: with the link in front matter and the log
accepted, the coverage page moves `REQ-PWR-001` off `open` and onto
`satisfied, unverified` (`open 1 -> 0`); with the same link left in a body
fence the page stays `open 1` and inert. `refdes index` carries the identical
diagnostic (file, line, item), so the VS Code path sees it too.

Residual gap, by construction, not a finding: the scanner matches only
`yaml`/`yml` tags (`src/refdes/build.py:304`), so a ` ``` ` fence with no info
string declaring `checks:` (case `s4-v11`) is the same silent trap with no
warning. `docs/checks.md:127-128` documents the trap generically, not the
tag-narrowness of the warning; an author warned about one spelling gets no
signal for the plain-fence spelling.

## 5. #326/#329 — `create/preview` refuses an unregistered workspace

Live serve on the `s5-p1` fixture: `item_layout: workspace`, registry
`product-a`/`product-b`, boards `board-a`/`board-b`, one requirements file
per workspace. Driven over real HTTP with the launch token in
`X-Refdes-Token` (all via `GET /api/create/preview`, type pinned to
`requirement`); ledger/file md5s taken before and after.

| `GET /api/create/preview?...` | result |
|---|---|
| `workspace=product-a` / `product-b` | 200, destination inside that workspace's tree |
| `workspace=nosuchws` | 400 `workspace: no such workspace 'nosuchws' in this project; known workspaces: product-a, product-b` — the exact message #326's fragment quotes |
| `workspace=platform` (a name no item carries, not registered) | 400, same shape |
| `workspace=` (empty) / param absent | 200, unscoped suggestion — unchanged surface, as claimed |
| `workspace=nosuchws&destination=<real file>` | 400 — the #329-pinned pairing; **nothing reserved**: item files, ledger and `.refdes/` md5s byte-identical after the whole probe batch |
| `workspace=product-a&destination=<product-b file>` | 200, the named destination wins, scope's own suggestion ignored — unchanged, as claimed |
| `workspace=product-a&board=board-b` | 200 — known combos unchanged |
| `GET /api/items?workspace=nosuchws` | 400, byte-identical message to preview's — the parity claim holds |
| `refdes ls --workspace nosuchws` | `no items match`, exit 0 — the unchanged CLI surface |

The fragment's parenthetical ("an item counts by its *resolved* workspace...
on a built snapshot the accepted set is the registry's") checks out from the
load side: giving one item `workspace: ghost` is a build **error**
(`workspace: 'ghost' is not declared in ... workspaces: registry`), so an
item carrying a workspace the registry lacks never reaches a built snapshot.

Every claim in the #326 fragment and its #329 follow-up matched the live
behavior; the changelog text is honest.

R11-F4 (low) — the gate covers `workspace` and stops there. `board` is the
sibling scope parameter, `GET /api/items?board=nosuchboard` refuses it with
the parallel 400 (`board: no such board ... known boards: ...`), but
`GET /api/create/preview?workspace=product-a&board=nosuchboard` answers
**200** with destination `items/product-a/requirements.md` — a *new file at
the workspace root* — and `?board=nosuchboard` alone answers 200 with
product-a's suggestion. This is run 9's R9-F3 for the other parameter: a
scripted caller with a typo'd board is pointed at a file tree nothing said
about, and (unlike R9-F3) the suggestion invites creating a file the
workspace layout does not use. The fragment's "unchanged" list covers known
workspaces with board, so nothing documented is broken — the finding is that
the fixed class of bug remains open on the parameter right next to the one
that was fixed.

## 6. #244/#253 — the serve write lane as an author (create, citations accept pair)

Live `refdes serve` on `s6-a` (base + a `log` item citing
`analysis/power-budget.csv` with two `source()` calc lines), driven over
real HTTP with `X-Refdes-Token` + `Origin`. Serve started with
`--no-open --port --token-file`; stopped by recorded PID, and the token
file disappeared on the clean `SIGTERM`, as `docs/cli-reference.md:2095`
promises.

### #244 — create, all shapes, and a failed id reservation

| `POST /api/items/create` | result |
|---|---|
| log, no destination (suggested) | 200 created at the suggested `items/pwr/logs.md`, id + key returned |
| requirement `fields:{}` | 200 — `requirement` has no required scalar; lands at `items/requirements.md` |
| explicit `id` then same `id` again | 200, then 422 `duplicate id 'REQ-PWR-777' (also defined at items/requirements.md:9)` |
| `links: {satisfies: [REQ-NOPE-001]}` | 422 `no item 'REQ-NOPE-001' ... to link to with 'satisfies'` |
| `destination: ../../outside/reqs.yaml` | 422 `is not a safe relative path` |
| `destination: /etc/passwd` | 422 `a destination must live under items/` |
| `destination: items/pwr/req-new.yaml` (absent) | 422 `creating a new YAML list file is not a v1 destination -- start one with 'refdes new --list'` |
| `destination: <existing list file>` | 200 created, appended into the list |

The reservation-failure path (the #244 fix) was reproduced author-side by
`chmod 500 .refdes` (the documented ledger location) mid-create. Both append
shapes answer a refusal naming the cause and the repair — `refused: the id
ledger could not be written (directory is read-only: ...); items/pwr/
requirements.yaml was rolled back and REQ-003 was not reserved` — and in
both shapes the sha256 of the destination taken before and after the
refusal is identical (the .md shape and the yaml-list shape, checked
separately). No id is burned: the ledger never gains the refused id. On the
pre-fix code the same refusal truncated the destination to 0 bytes; the
byte-identical restore across every refused request in the lane is the
fix holding.

### #253 — the citations accept pair (body line + lockfile pin as one operation)

`GET /api/item/<ref>/sources/propose?path=&key=&unit=&name=` returned the
calc line for a fresh csv key. `POST /api/item/<ref>/edit` with
`op: set_body` + `pin: {path, key, unit, name}` then:

- **happy**: 200 `applied`; body and `.refdes/citations.yaml` both move,
  and `refdes check` is clean (0 warnings) — no unpinned pair, no pin for a
  body line that never landed.
- **refused**: a pin naming a key the csv lacks is 422 (`no row has the
  key ... the keys come from the file`), and item file + lockfile + ledger
  sha256s are byte-identical after; `check` stays clean. A pin against a
  changed-and-unaccepted file is refused (`the file has changed since it
  was pinned`), the loud gate docs/math.md documents, with the same
  byte-intact result.
- **sequence**: a second accept onto the first's landed body applies;
  `check` clean.
- **accept-then-edit**: dropping the accepted source line with a plain
  `set_body` applies (200) and the pin stays in the lockfile; `check`
  reports clean. A pin naming a body line the author deleted is inert
  provenance the build ignores (the lockfile is read only for keys the
  body cites) — nothing documents it as a dangling-pin error, so this is
  reported as observed, not a finding.

The `expected_revision` gate is the author-visible half of #253's window
removal: every POST after a landed write with a stale revision is a 409
carrying the current text, and no refused POST left a byte.
