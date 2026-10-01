# User-simulation release gate — run 4 (the delta, re-tested as a user)

Run 4 of the standing gate, scoped to what landed since run 3's merge
(`e2ca13e`). Seventeen commits: `git log --oneline e2ca13e..HEAD`. Between them
they close run 3's N1, N2, N3, N4 and N6, leave N5 open, and add six new
user-facing surfaces (#124, #126, #127, #129, #130, #132–#138).

**Method, unchanged from runs 1–3:** documented surfaces only — `docs/`,
`--help`, real CLI invocations, real HTTP — and the *original scenario* re-run
rather than the fix read. Reported version is `refdes 0.5.0`. The `refdes` on
`PATH` in this worktree is a broken editable install, so every command went
through a one-line wrapper in `.scratch/refdes`
(`PYTHONPATH=<this worktree>/src python -m refdes.cli …`); a second wrapper
`.scratch/refdes-old` does the same against `e2ca13e`'s `src/`, extracted with
`git archive e2ca13e src | tar -x -C .scratch/old`, for §4. Both are
local-machine artefacts and neither is counted as a product finding.

**Nothing under `src/`, `tests/` or `docs/` was modified** (`git status` shows
only the two files this report adds). Every synthetic project lives under
`.scratch/run4/`, which is gitignored; no `refdes` command was ever run from the
worktree root, and no `git` command took part in any sweep. Read-only scenarios
`chmod -R a-w` a scratch copy and `chmod -R u+w` it afterwards.

Out of scope by instruction, and not re-litigated here: VS Code, Windows,
real-internet `fetch`, real PDFs through the source picker (run 4 of those
exercises — `in-prog-logs/remote-fetch-exercise.md`,
`in-prog-logs/pdf-picker-exercise.md` — already covered them), and identity
recovery.

---

## 0. Headline summary

**Run 3's N1 is genuinely fixed, in all four chmod layouts, and the shape that
shipped is better than the one run 3 asked for.** `build` no longer degrades
silently over unsealed entries: it prints an *error* naming
`.refdes/log-seal.yaml` and saying the entries are **NOT** sealed, renders the
site anyway, and exits `1`. `revision` and `release` refuse with the baseline
path named, exit `2`, and print no "stamped" line. Zero tracebacks across
`build` / `revision` / `release` × {whole tree, `items/` only, `.refdes/` only,
`site.out` elsewhere}.

**N2's sentence is now genuinely one string.** Six distinct refusal lines came
out of a whole-tree sweep and every one carries the identical clause
`could not write this file (read-only tree?)`; only the file name's position
differs. The CI-filter claim at `docs/cli-reference.md:56-97` holds as written,
and the one documented exception (`build`'s site directory, which reports the
OS's own reason) is real.

**But the fix did not sweep the whole command list, and the doc now claims it
did.** Two commands still print a raw `PermissionError` traceback when the
destination is not writable — `stub-tests` and `revise apply` — and `stub-tests`
additionally leaves a **half-finished write on disk with no summary line at
all**. `docs/cli-reference.md:41-42` says flatly that "no command in that state
prints a Python traceback", and the changelog fragment for #132 says "no
command prints a traceback because a destination isn't writable". Both are
false today. That is **F1** below, and it is the same failure run 3 filed as
N1, one layer down.

**Every other new surface did what it claims**, and several of them did it
better than a first pass would suggest: the duplicate-YAML-key diagnostic names
the file, both line numbers, the key and what was lost, and leaves the file it
reports byte-identical; the corrupt-lockfile diagnostics cover every shape I
could throw at them and `fetch` leaves the file alone; `revise` refuses an
unknown mapping section instead of half-applying the file; the two dangling-link
remedies name the fix; two `serve` instances saving one item conflict instead of
losing an update; and `SIGTERM` now removes the token file.

**Two low findings are worth a newcomer's attention.** The `page:` declaration
error is the only new diagnostic in this delta with **no remedy and no docs
URL** — and it is the one *breaking* change an upgrading project meets (§4,
**F2**). And `getting-started.md` says "four files" and then "add those three
lines" in one sentence (**F4**).

The upgrade path itself is otherwise clean: a project built entirely with
run 3's `refdes` — including a lockfile with no `page_count:`, a stamped
baseline, a seal file and an ID ledger — passes `check`, `build`, `release`,
`audit`, `ls`, `index`, `fetch`, `stub-tests`, `former-ids` and `history
capture` on current `main` with no migration step and no error.

Nothing in this run rose above medium.

---

## 1. Re-test table — every run-3 finding, re-run as a user

Each row is run 3's scenario, reproduced against `HEAD` (`15bfd69`).

| # | Run-3 finding | Verdict | What I ran, and what it printed |
|---|---|---|---|
| N1 | `build` / `revision` / `release` die with a `PermissionError` traceback on a read-only checkout | **fixed** | Four layouts × three commands, on a project that is green but has *never been built here* (so the seal write is a real write, not a no-op — this is the shape that crashed). See the matrix in §1.1. No traceback anywhere; `build` errors and exits 1, `revision`/`release` refuse and exit 2. |
| N1-sweep | *(run 3 §5 asked for the matrix across every command that writes)* | **partly fixed — F1** | Swept 18 command invocations on a whole-tree read-only copy. Two survivors: `stub-tests` and `revise apply`, both raw tracebacks; `stub-tests` also leaves a partial write. Everything else degrades or refuses. |
| N2 | the same read-only condition announced in two different sentences | **fixed** | Whole-tree sweep of 12 commands → 6 distinct refusal lines, all carrying the byte-identical clause `could not write this file (read-only tree?)`. The *sentence* is one string, exactly as `model.read_only_refusal()` claims. Only the file name's position differs (`WARNING <path> — could not…` vs `could not… -- <path>`), which is inherent to the two shapes `docs/cli-reference.md:62-79` documents. |
| CI-filter | "grep a read-only run's output for `(read-only tree?)`" | **claim holds** | Whole-tree sweep output captured to one file: 14 lines carry `(read-only tree?)`, **0** `Traceback`, **0** occurrences of `docs/cli-reference.md` anywhere in it — so the repo-relative-path leak run 3 noted once is not present in this family of messages. The longer string `could not write this file (read-only tree?)` catches the load-time shapes; the destination-naming refusals carry only the short form, as `docs/cli-reference.md:86-89` says. |
| N3 | `getting-started.md`'s sample blocks no longer match the commands | **fixed** | §2's `refdes id` block and §5's `refdes build` block are now byte-identical to a literal run in a fresh git repo (diffed, per stream). §1's generated `refdes-project.yaml` is byte-identical to a fresh `init`. Every other block on the page reproduces too — §6's coverage claim, §7's append-only refusal, the `check_severity` overlay, and the `does not cover status 'proposed'` refusal. |
| N4 | `--token-file` survives a `SIGTERM` | **fixed** | `kill $PID` → process exits `0`, token file gone. Also confirmed `SIGINT` removes it (but **only** with `set -m` in the driving shell — see §5), and `kill -9` leaves it, which is what `docs/cli-reference.md:1534` promises. |
| N5 | `ls` has no workspace column | **still open** | Not in this delta. A project declaring `workspaces: {product-a: {}, platform: {}}` still prints six rows of id / type / title with no workspace anywhere; `ls --workspace product-a` returns the one item and `--workspace platform` returns `no items match`; `index --compact` still carries `workspace` per item. Unchanged, not regressed. |
| N6 | `[unboarded]` placeholder and a bare `key` line in `audit`'s reseal section | **fixed** | Now `LOG-001 <ts> edit` / `item key z87bd2m9jq2`, plus one parenthetical explaining that the key survives a rename where the id above is the label as it stood. The internal placeholder never reaches the seal file either — the seal file itself carries only `action / id / key / new_hash / old_hash / occurred_at`. |

### 1.1 The read-only matrix run 3 §5 asked for

Whole tree / `items/` only / `.refdes/` only / `site.out` elsewhere, against
`build`, `revision`, `release`. Verbatim, abridged to the refusal lines.

```
### tree: refdes build
ERROR   .refdes/log-seal.yaml — could not write this file (read-only tree?) -- the entries in it are NOT sealed, so they have no append-only protection until a build can write this file; run with --no-write to silence this
error: cannot write the site to …/_site (Permission denied) -- nothing was rendered. Point -o/--out at a writable directory, or make this one writable.
WARNING .refdes/schema.json — could not write this file (read-only tree?); run with --no-write to silence this
6 items, 1 errors, 2 warnings
[exit=2]

### items: refdes build          (items/ and refdes-project.yaml read-only)
6 items, 0 errors, 1 warnings
site written to …/_site
[exit=0]

### refdesdir: refdes build      (.refdes/ and items/ read-only, site writable)
ERROR   .refdes/log-seal.yaml — could not write this file (read-only tree?) -- … NOT sealed …
build completed with errors (use --keep-going to exit 0)
site written to …/_site
[exit=1]

### site: refdes build           (site.out elsewhere and writable)
ERROR   .refdes/log-seal.yaml — could not write this file (read-only tree?) -- … NOT sealed …
site written to …/run4/site-elsewhere
[exit=1]

### tree: refdes revision r1
error: cannot write .refdes/baselines/r1.yaml (read-only tree?) -- revision 'r1' was not stamped. Make the tree writable and run it again, or run it with --no-write to see what it would stamp.
[exit=2]

### tree: refdes release rel-a
error: cannot write .refdes/baselines/rel-a.yaml (read-only tree?) -- release 'rel-a' was not stamped. Make the tree writable and run it again, or run it with --no-write to see what it would stamp.
[exit=2]
```

`revision`/`release` behave identically in the `refdesdir` and `site` layouts.
Two things worth naming:

- **The wording that shipped is better than the wording run 3 proposed.** Run 3
  suggested `WARNING … could not record append-only seals`. What shipped is an
  error that says the entries are not sealed and exits `1` — which is the
  honest answer, because the entries really are unprotected.
- **The `site.out`-elsewhere shape survives.** This was run 3's third N1
  variant and the one it called out as "the shape a CI job actually has". It now
  renders the site to the writable directory and still exits `1` for the seal.

---

## 2. The new surfaces, as a user meets them

| # | Surface | Verdict | What I did |
|---|---|---|---|
| #130 | duplicate YAML key in one mapping | **works**, one residue (**F3**) | Built the realistic shape: a three-item list file whose third entry opens with `  - key: <key>`, then deleted exactly that one line — the merge run 3's report described. Three hard errors, each naming the file, both line numbers, the key, and what was lost; exit `1`. The reporting file is left **byte-identical** (`find │ sha256sum` before and after). Markdown front matter covered too. |
| #129a | `revise` refusing an unknown mapping section, and the `ids:` pointer | **works** | `ids:` → exit `2`, names the file, the section, all five accepted sections, and adds the single-item-rename pointer. `--dry-run` refuses identically. A typo'd `type:` gets the accepted list and *no* `ids:` pointer. A mixed file (valid `prefixes:` + `mystery:`) refuses instead of half-applying. A valid `prefixes:` rename still changes 3 files and reports `REQ-PWR-001 -> NEED-PWR-001`. I followed the pointer's own advice (hand-edit one `id:` after a writable `check`) and it worked: `(rewrote 1 reference(s) while loading)`, exit `0`. |
| #129b | the dangling bare `checks: against:` remedy | **works** | Composite-expanded `against:`, reverted to bare, renamed the bound by hand → `check against 'BND-THM-001', which does not exist -- a typo, a deleted item, or an item renamed while this `against:` was still bare, and a bare `against:` cannot follow a rename: write the item's new id here.` Writing `BND-THM-404` there recovers: exit `0`, and the next load expands it to `BND-THM-404@wsps9e3wrap`. |
| #126 | the dangling bare-link remedy + the `checks:` twin | **works** | Same scenario on `satisfies:` → the parallel sentence, same URL, same severity. |
| #126 | `troubleshooting.md`'s hand-rename advice | **works** (one sample line missing, **F5**) | Followed the page's four-step trace literally in a two-item project. Step 2 expanded `refines: [REQ-001]` to `[REQ-001@nkpsxj4rxww]`, the hand-edit of the target's `id:` was followed on the next load (`REQ-009@nkpsxj4rxww`, key unchanged), and the page's sample count line `2 items, 0 errors, 1 warnings` matches. I also checked the page's claim that `former_ids:` does **not** reach a structured link: with a bare reference plus `former_ids: [REQ-001]` recorded, the error is unchanged. True. |
| #137 | `page:` validation | **works**, friction (**F2**) | Both halves. *Declaration* (no file needed): `"0"`, `"-1"`, `"eight"`, `"xiv"`, `"1.5"`, `"2-4"`, `"p. 4"`, `"iv"` all refused with the same sentence, exit `1`. *Range*: `page: "99"` on an 8-page PDF is silent at `check` (no count in the lockfile yet), `refdes fetch` records `page_count: 8` next to the sha256 and warns `docs/manual.pdf: page 99 is not in this document -- it has 8 page(s) (cited by DEC-PWR-001)`, every later `check` and `build` repeats it, and `build --require-citations` escalates it to an error with exit `1`. |
| #138 | a corrupt `.refdes/citations.yaml` | **works** | Built the realistic shape — a `citations:` block that is a *list* plus an unresolved `<<<<<<< HEAD` conflict, which is what merging two branches that both ran `fetch` gives you. `fetch` refuses with exit `1` and **leaves the file byte-identical** (`sha256sum` before/after equal). `check`, `build` and `audit` all name it (`audit` exits `1` rather than silently omitting the section). Eight further shapes tried — `citations:` as a list, a repeated pin, a non-hex `sha256`, a mistyped `fetched`, both `page_count:` and `page_count_error:`, plain invalid YAML, a whole-file string — and every one produced a named diagnostic with a remedy. |
| #133 / #136 | `init`'s `.gitignore` | **works** | Fresh repo at the root: `git check-ignore -v` **one path per call** (the shape the fix's own test switched to) matches all four patterns and leaves `.refdes/ids.yaml` and `.refdes/log-seal.yaml` alone. Project nested at `hw/power-board/` inside a bigger repo: all four still match, from the repo root, with no leading slash. `git status` after `init` stages only `.gitignore` and `refdes-project.yaml`. A pre-existing `.gitignore` already covering `.refdes/copies/` gets three lines added, not four, and the file is not otherwise disturbed. |
| #127 | `serve`'s `SIGTERM` token-file cleanup | **works** | See §1. Also: the launch file is still `0600`, still atomic, and the token still authenticates only through `X-Refdes-Token` (no `Authorization`, no `?token=`, no cookie — all `403`), which is what `docs/cli-reference.md:1547-1549` says. |
| #134 | two `serve` instances saving the same item | **works** | Three trials, a fresh project each. Both instances read the same `edit.file_revision`; A's `POST /api/item/REQ-PWR-001/edit` returns `200 {"kind": "applied"}`; B's, from the now-stale base, returns `409 {"kind": "conflict"}` with a unified diff and does not write. On disk afterwards: A's value; `refdes --no-write check` is `6 items, 0 errors, 1 warnings`. The `.refdes/serve-write.lock` file appears on the first save and not at startup, which is what `docs/cli-reference.md`'s new bullet claims. |
| #124 | a prose former-id link's text | **not exercised** | Identity recovery is out of scope by instruction. Not claimed as regressed. |

### 2.1 One API gotcha worth recording, because it costs a real 409

`POST /api/item/<ref>/edit` wants `expected_revision` to be **the item's
`edit.file_revision`**, not `/api/revision`'s project-wide `revision`. Sending
the project revision is refused with a `409` whose message *reads* like a
genuine concurrent-edit conflict:

```
409 {"kind": "conflict", "ok": false, "message": "conflict: …/items/requirements/power.yaml
  changed since this edit was planned (expected dd45af184bb2, found 00d785e45dc4)", …}
```

which is technically true (the file is not at that digest) and practically
misleading — a first-time driver reads it as "someone else is editing". Omitting
the field gives the good diagnostic:

```
400 {"error": "expected_revision is required: the file_revision from GET /api/item/<ref>"}
```

`docs/design/editor-vscode-adapter.md:286` names the parameter but not which
value belongs in it. Not filed as a finding — the 400 is clean and the 409
carries both digests, which is enough to work it out — but run 5 should know it
is the first thing anyone scripting the editor trips over.

---

## 3. `docs/getting-started.md`, followed literally

Run in a fresh git repo, in the page's order, diffing every fenced block
against real output per stream.

| § | Block | Result |
|---|---|---|
| 1 | generated `refdes-project.yaml` (`getting-started.md:43-55`) | **byte-identical** to a fresh `refdes init` |
| 1 | folder listing (`:90-94`) | matches at the point the page shows it (`init` has not created `.refdes/` yet) |
| 2 | `refdes id` (`:130-133`) | **byte-identical**, including the `(minted 2 key(s) while loading)` line #125 added |
| 3 | bound file | loads; `limit: "<= 0.15 W/in^2"` parses as a quantity, as claimed |
| 4 | `refdes new decision` → the page's file | loads |
| 5 | `refdes build` (`:235-240`) | **byte-identical** apart from the `/path/to/my-board/_site` placeholder the page itself uses; the page calls out the stream interleaving at `:243-244` and that is what I saw |
| 6 | coverage claim | true — `REQ-PWR-001` renders **verified**, `REQ-PWR-002` **satisfied** and not verified |
| 7 | append-only claim | true — editing `LOG-001` after a build fails the check with the `--reseal` pointer |
| 7 | "superseding the decision will not [turn it green]" | true — wrote a passing `DEC-PWR-002` with `supersedes: [DEC-PWR-001]`, set `DEC-PWR-001` to `superseded`, and `check` still reports the old failure |
| 7 | the `check_severity` overlay | true, verbatim: `7 items, 0 errors, 1 warnings`, exit `0`, and the demoted failure lands in `check -v` as `INFO … [DEC-PWR-001] — P_dens violates …` exactly where the page says |
| 7 | "omit `default:` and the project refuses to load" | true, including exit `2` |

One block drifts, and it is a count, not an output (**F4**).

---

## 4. Upgrade path: a run-3-era project on current `main`

Built entirely with `e2ca13e`'s `src/` — `init`, `id`, `fetch`, `build`,
`revision` — then handed to current `main`. The old lockfile has no
`page_count:`; there is a stamped baseline, a seal file, an ID ledger and
composite references throughout.

**Exactly one thing that passed before now fails:**

```
$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — citations[0]: page: '2-4' is not a page number -- page: must be a positive integer, counted from 1
WARNING <project> — 1 requirement(s) satisfied but not verified — see coverage.html
6 items, 1 errors, 1 warnings
[exit=1]
```

That is the documented breaking change (`changelog.d/citation-page-checked.breaking.md`,
`CHANGELOG.md` `[Unreleased] → Breaking`), and it reproduces exactly the case
that fragment names. It is also the *only* new failure, and it is well enough
explained to fix without reading the source — see **F2** for the one thing
missing from that explanation.

Everything else upgraded silently, with no migration step:

- The old lockfile (no `page_count:`) is **accepted and left alone**.
  `refdes fetch` says `skipped  docs/manual.pdf  sha256=8f5443a56224...  hash-only`,
  exit `0` — it does not error, and it does not pretend to have checked the
  pages. `audit` still reports `ok  hash-only  cited by DEC-PWR-001`.
- `check`, `build`, `release rel-a`, `audit`, `ls`, `index`, `fetch`,
  `stub-tests --dry-run`, `former-ids propose`, `history capture` — all exit `0`
  or their documented code, with no configuration error and no advice to run
  anything.
- The baseline, the seal file and the ID ledger written by the old `refdes` are
  all read without complaint; `build` seals nothing new and `history capture`
  says `DEC-PWR-001 is already captured; nothing was written`.
- The upgrading project's `.gitignore` is **not** migrated (correct — `init` is
  the only writer), and after `build` + `check` + `fetch` a
  `git check-ignore -v` shows `.refdes/schema.json` and `.refdes/copies/` still
  untracked-and-not-ignored. That is the documented manual step
  (`docs/cli-reference.md:1707`), and nothing in the tool's output mentions it.

---

## 5. New findings

### F1 — `stub-tests` and `revise apply` still print a raw `PermissionError` traceback, and `stub-tests` leaves half a write behind

**Severity: medium.** This is run 3's N1 residue, one layer further down, and it
directly falsifies a claim the delta makes twice.

Whole tree read-only (or just `items/`), on an otherwise-green project:

```
$ chmod -R a-w items
$ refdes stub-tests
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  ...
  File ".../src/refdes/cli.py", line 1510, in cmd_stub_tests
    written = stub_tests_mod.generate(project, verifier_type=args.type, dry_run=args.dry_run)
  File ".../src/refdes/stub_tests.py", line 169, in generate
    with open(target, "ab") as fh:
         ~~~~^^^^^^^^^^^^^^
PermissionError: [Errno 13] Permission denied: '.../items/stub-tests.md'
[exit=1]
```

`revise apply` fails the same way (`src/refdes/revise.py:1422` →
`write_rewrites` → `textio.write_text`), on both an all-read-only tree and the
`items/`-read-only shape.

Three things make `stub-tests` the sharper of the two:

1. **It writes in a loop, so the refusal lands mid-run and the earlier files
   stay.** A three-board project with `items/gamma/` read-only and the other two
   writable:

   ```
   $ refdes stub-tests
   PermissionError: [Errno 13] Permission denied: '.../items/gamma/stub-tests.md'
   [exit=1]
   $ find items -name stub-tests.md
   items/alpha/stub-tests.md
   items/beta/stub-tests.md
   items/stub-tests.md
   ```

   Two of three files were created and the third was not, and **the summary
   line never printed** — `wrote 4 stub test(s) across 3 file(s)` is absent, so
   the only account of what happened is the traceback. A user who re-runs after
   `chmod` gets a *different* set of stubs than the first run created, because
   the deduplication is by declared link and two of the three already exist.

2. **`--dry-run` is clean**, so the tool knows exactly which writes it is about
   to make and reports them correctly:

   ```
   $ refdes stub-tests --dry-run
   would write 2 stub(s) to items/stub-tests.md: BND-THM-001, REQ-PWR-002
   would write 2 stub test(s) across 2 file(s)
   [exit=0]
   ```

   The refusal is a two-line fix in the same shape `revise._refuse_unwritable`
   already uses, and the rollback question (what to do about the two files that
   did land) is the only design work in it.

3. **The docs contradict themselves about it.** `docs/cli-reference.md:41-42`
   says "no command in that state prints a Python traceback — each either
   degrades and says what it could not write, or refuses", and the table below
   it does not list `stub-tests`. `changelog.d/readonly-seal-baseline-writes.fixed.md:4`
   says "no command prints a traceback because a destination isn't writable".
   Meanwhile `docs/design/keys.md:463` has a row reading "any other explicit
   write (`keys adopt`, `keys restore`) | raises, as before", which reads as the
   complete list of raising commands — and `stub-tests`, `revise apply` and
   `calc-rewrite` all raise and are not in it. Ironically
   `docs/cli-reference.md:78-79` already knows about `stub-tests` in this exact
   neighbourhood, but only as the command that "prints both" read-only *shapes*,
   not as one that prints a third thing.

`keys adopt` / `keys restore` raising is deliberate and documented; it is worth
one sentence saying so in the same place, since the sentence right above them
now over-claims.

**What I would want:** either the same `refused:` shape the other explicit
writes got (naming the file, exit `1`, and either rolling the loop back or
saying how many files were written before the refusal), or the blanket claim
narrowed to the commands the table actually lists.

### F2 — the one breaking diagnostic in this delta is the only one with no remedy and no documentation pointer

**Severity: low.** The upgrade in §4 turns on a single error, and it is the only
new message in the whole delta that stops at naming the rule:

```
ERROR  items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — citations[0]: page: '2-4' is not a page number -- page: must be a positive integer, counted from 1
```

Every other new diagnostic in this delta ends the same way — a remedy plus
`https://squishiba.github.io/refdes/troubleshooting.html#…`:
`duplicate key 'id' in one mapping … put the '- ' back on its own line. Otherwise delete one of the two lines. See …`,
`… write the item's new id here. See …`,
`unknown top-level section 'ids'. … To rename a single item, edit its id: by hand instead … see …`.
This one says what is wrong and stops. The question a user actually has — *I
cited pages 2 to 4, what do I write instead?* — is answered nowhere either:

- `docs/markdown.md:402-404` lists `2-4` among the refused shapes and explains
  why, but never says a range has no representation.
- The answer, which I found by trying it, is that **two citation entries for one
  path are accepted** (`page: "2"` and `page: "4"` on separate entries for
  `docs/manual.pdf` → `6 items, 0 errors, 1 warnings`). That is the useful,
  obvious remedy, and it is documented nowhere.

This matters more than a usual missing-remedy nit because it is the *only*
behaviour change between `e2ca13e` and `HEAD` that a passing project meets, so
it is the first thing an upgrading user sees from this delta. Two options, both
cheap: name the two-entry shape in the message, or append the same
troubleshooting pointer the rest of the delta's messages carry.

### F3 — the duplicate-key diagnostic protects the file that reports the merge, but not the files whose references it repoints

**Severity: low.** #130's withholding works exactly as claimed for the file that
carries the duplicate. The residual is one layer out, and it is permanent.

Reproduced with run 3's shape: a three-item list file whose third entry opens
with `  - key: <key>`, and that one line deleted. The merged mapping keeps
`REQ-PWR-002`'s key (`9gs5y7g1prg`) and takes `REQ-PWR-003`'s `id`, so the item
that survives is `REQ-PWR-003` carrying the vanished item's key. Then:

```
$ refdes check
ERROR   items/requirements/power.yaml:19 [REQ-PWR-003] — duplicate key 'id' in one mapping (lines 14 and 19) -- …
ERROR   items/requirements/power.yaml:20 [REQ-PWR-003] — duplicate key 'body' in one mapping (lines 16 and 20) -- …
ERROR   items/requirements/power.yaml:21 [REQ-PWR-003] — duplicate key 'source' in one mapping (lines 17 and 21) -- …
(rewrote 1 reference(s) while loading)
6 items, 3 errors, 1 warnings
[exit=1]
```

`items/requirements/power.yaml` is byte-identical afterwards (verified by
hash) — that part is right. But `(rewrote 1 reference(s) while loading)` means
`items/decisions/dec-pwr-001-regulator.md` had its `satisfies:` rewritten from
`REQ-PWR-002@9gs5y7g1prg` to `REQ-PWR-003@9gs5y7g1prg`, with **no warning**.
The label-refresh rule does not fire its warning because `REQ-PWR-002` is not a
*live* item at that moment, so it is not "a different live item".

The safety net does exist — once the user repairs the file, the next check says
so loudly:

```
ERROR   … key 'kqx78cwj59z' on REQ-PWR-003 … is already used by DEC-PWR-001 … `git log -S'key: kqx78cwj59z' --oneline --reverse` names the oldest commit that wrote it …
WARNING … satisfies references 'REQ-PWR-003@9gs5y7g1prg', but that key is REQ-PWR-002 and REQ-PWR-003 is a different live item. Refusing to refresh the label until you confirm which was meant.
```

…but by then the decision has been recorded as satisfying the wrong requirement,
and the "restore it from git" advice for a *different* key now points at a key
that is not the one that moved. The gap is narrow — one run, one file, and the
tool catches it on the next — so low is the right severity. The cheapest
improvement is one sentence in the duplicate-key message: *a reference in
another file may have been repointed at the surviving item while this was
broken.*

### F4 — `getting-started.md` says "four files" and then "add those three lines"

**Severity: low.** `docs/getting-started.md:74-85`, one sentence:

> …a `.gitignore` to keep **four files** out of your commits: that settings file
> — … — plus `.refdes/copies/` …, `.refdes/schema.json` …, and
> `.refdes/serve-write.lock` (…). If your project already existed, `init` is not
> what wrote that `.gitignore`: add those **three lines** yourself.

Both numbers are individually defensible — `docs/cli-reference.md:1707` also
says three, and means the three `.refdes/` paths — but in *this* sentence the
antecedent of "those three lines" is the list of four, and a newcomer cannot
tell whether the settings file is in scope. This is the page run 3's N3 was
filed against, and the same pass that fixed the sample blocks (#125) and the
same PR that made the count three (#136) left the mismatch standing.

### F5 — `troubleshooting.md`'s hand-rename sample block omits a line a literal run prints

**Severity: trivial.** `docs/troubleshooting.md:300-304`:

```
$ refdes check
(rewrote 1 reference(s) while loading)
2 items, 0 errors, 1 warnings
```

Run literally, in the two-item project the block's own YAML trace describes:

```
$ refdes check
(rewrote 1 reference(s) while loading)
WARNING <project> — 2 item(s) with no coverage — see coverage.html
2 items, 0 errors, 1 warnings
```

The count line matches character for character, which is the property that
matters; one `WARNING` line is missing. Same class as run 3's N3 and the same
one-line fix, in a page #126 and #129 both edited this series.

### Noted once, not per message

A duplicate mapping key in **`refdes-project.yaml`** is still resolved silently
by YAML: a second `site:` block replaces the first, `refdes check` exits `0`,
and the surviving `out:` is the second one's. This is deliberate and stated as
such in `changelog.d/duplicate-mapping-key.breaking.md` ("`refdes-project.yaml`
and `refdes-schema.yaml` are untouched by this change, deliberately"), and
`#130`'s scoping reason — a config duplicate cannot yet name a line — is
reasonable. But no *user-facing* doc says it, and the reason a project config is
exempt from the rule that now protects item files is exactly the sort of thing
that reads as an oversight. Recording once, as run 3 did, and not counting it.

---

## 6. What worked cleanly

- **The read-only reporting is now one sentence, everywhere.** Twelve commands,
  six distinct refusal lines, one byte-identical clause. This is the property
  `docs/cli-reference.md:56-97` asks a CI author to rely on, and it is true.
  The filter claim survives being grepped rather than read: 14 hits for
  `(read-only tree?)`, 0 tracebacks, 0 repo-relative doc paths.
- **`build`'s refusal is the right refusal.** Erroring rather than warning on an
  unsealed entry, exiting `1`, and still rendering the site, is exactly the
  asymmetry run 3 argued for and it is what shipped. Run 3's own suggested
  wording was worse.
- **`--no-write` really is unaffected.** On a fully read-only tree,
  `--no-write check` and `--no-write build` both print
  `6 items, 0 errors, 1 warnings`, exit `0`, no refusal noise at all — the
  flag's contract is that it never reaches a write.
- **The steady state is quiet.** Second `refdes check` on a fully-keyed project:
  `6 items, 0 errors, 1 warnings`, and `--no-write check` the same. A notice
  that fired every run would have been worse than the bug it fixed.
- **The duplicate-key diagnostic is the best message in the delta.** It names
  the file, **both** line numbers, the key, what YAML did with it, *why an `id:`
  is worse than a field*, the specific edit that causes it, the fallback fix, and
  a published URL — and it withholds the write-back for the file it reports.
  The same for the front-matter variant, `twice on line N`, and the
  identical-values case.
- **The corrupt-lockfile family is thorough and honest.** Eight shapes, eight
  precise diagnostics, each with the remedy and the consequence of taking it
  (`re-pinning it downloads every cited document again`), `fetch` leaving the
  file byte-identical, and `audit` exiting `1` rather than quietly omitting the
  section it cannot produce.
- **`revise` refusing rather than half-applying** is the right call and covers
  both front doors: a mapping file with a valid `prefixes:` *and* an unknown
  `mystery:` used to rename everything and drop the rest in silence. The `ids:`
  pointer is conditional, which is the detail that makes it good — a typo'd
  section gets the accepted list and nothing else.
- **The dangling-reference remedies close the dead end.** Both the structured
  link and its `checks: against:` twin now say the same three explanations, name
  the remedy, and point at the published docs. I followed both remedies and both
  recovered to exit `0`.
- **The concurrency fix holds under repetition.** 3/3 trials, fresh project
  each: one save wins, the other gets a `409` with a diff, no lost update, no
  corruption, `check` clean. And `.refdes/serve-write.lock` really does appear
  on the first save rather than at startup, which is what the docs newly claim.
- **`init`'s `.gitignore` is right in both layouts and honest about itself.**
  `git check-ignore -v` one path per call, in a repo root and nested three deep;
  `.refdes/ids.yaml` and `.refdes/log-seal.yaml` correctly left alone; a
  pre-existing file appended to and not disturbed; a path an existing pattern
  already covers gets no second line; and `init` names what it added.
- **`serve` is still exactly as careful as it claims.** `SIGTERM` and `SIGINT`
  both remove the credential and exit `0`; `kill -9` leaves it (documented);
  mode `0600`; token accepted only through `X-Refdes-Token`.
- **The upgrade path needs no migration.** An `e2ca13e`-built project —
  old lockfile, baseline, seal, ledger, composites — runs clean on `main`
  across twelve commands, and the lockfile `fetch` wrote without a
  `page_count:` is accepted, skipped rather than rewritten, and reported as
  `ok  hash-only` rather than as a checked page.
- **`getting-started.md` is now trustworthy again.** Every fenced block on the
  page reproduces, including the two #125 fixed, and every prose claim I tested
  (coverage stages, append-only, superseding, the overlay, the `default:`
  refusal) is true.

---

## 7. What wasn't covered

- **The remaining read-only survivors were not chased to ground.** I found two
  tracebacks (F1) and stopped there; a third (`calc-rewrite` with a real
  old-spelling calc line and a read-only `items/`) is plausible and untested.
- **The documented `refused:` carry-forward shape for `revise` was not
  reproduced**, in three attempts. A `prefixes:` rename of an id recorded in a
  stamped baseline does not rewrite the baseline label in the writable case
  either, so there is nothing to carry forward; renaming a sealed log prefix
  hits the build-error rollback first. Recorded as *not confirmed*, not as a
  defect — I could not construct the shape the table at
  `docs/cli-reference.md:51` describes.
- **`pypdf` was available, so the `page:` range half was exercised for real**,
  but only against synthetic blank-page PDFs built with the fixture helper in
  `tests/test_citation_pages.py` (`pdf_bytes`). Real vendor datasheets,
  outlines and text layers were covered by `in-prog-logs/pdf-picker-exercise.md`.
- **`fetch --update` re-pinning** was not driven against a real remote; the
  local-file path was used throughout so nothing here depends on egress.
- **Windows, macOS, VS Code, real-internet fetch, identity recovery** — out of
  scope by instruction.
- **Two `serve` trials I ran first were my own harness's fault**, not the
  product's: I put the token file inside the project tree (which
  `docs/cli-reference.md:1591` explicitly warns against) and omitted the
  `Origin` header, which cost two `403`s that read like an auth bug. The
  `X-Refdes-Token`-only finding in §6 is the corrected result. Worth recording
  because a run-5 harness will hit the same two — `docs/cli-reference.md:1591`
  warns about the first and `:1548` about the second.

---

## 8. Suggested shape for run 5

1. **Sweep the read-only matrix as a *list*, not as a report's findings.** F1
   is the second time a read-only gap has been found by widening the command
   list rather than by re-reading one. `docs/cli-reference.md`'s table has seven
   rows and there are nineteen subcommands; a run that enumerates
   *(command × which-of-its-writes-it-is-about-to-make)* from `--help` rather
   than from the last report would find the whole class at once, including
   `calc-rewrite`'s.
2. **Then make the claim true, or narrow it.** `docs/cli-reference.md:41` and
   the #132 fragment both currently over-claim. Either the sweep finds nothing
   left and the sentence becomes checkable, or the sentence gets the same
   "the tolerance belongs to writes nobody asked for" carve-out `keys.md` has.
3. **Re-run `stub-tests`, `revise apply`, `calc-rewrite`, `fetch --item`,
   `standard add-preset` and `keys adopt` against every *partial* read-only
   shape** — writable root with a read-only subdirectory, one read-only board of
   several — not just whole-tree. The partial-write residue in F1 only appeared
   because I went looking for it.
4. **The upgrade path deserves its own standing pass now that there are three
   breaking fragments in `[Unreleased]`** (`citation-page-checked`,
   `duplicate-mapping-key`, `citation-path`, `sets-rename`,
   `config-split-two-files`, `scalar-for-list-field`,
   `calc-colon-units-retired`, `hardware-v3-drop-in`,
   `scalar-field-typo-error`, `citation-vendor-keep-copy`). Two questions worth
   answering every time: does a *new* error carry a remedy, and is there any
   in-product way to learn a breaking change exists without reading
   `CHANGELOG.md`? Right now the answer to the second is no, and
   `refdes --version` prints only `refdes 0.5.0`.
5. **The two areas three runs have now left**, in the order run 3 ranked them
   and unchanged by this delta: real-internet `fetch` (redirects, `rev:`
   inference, a 404 on a pinned citation), a real PDF with a real outline
   through the source picker, VS Code under a real instance, Windows, and
   multi-root VS Code. Run 4 of the first two already exists; the remaining
   three do not.
6. **Process note carried forward, plus one of my own.** Run 3's warning —
   never run `refdes` from the worktree root, `cp -r` a pristine per command,
   `find │ sha256sum` before and after, no `git` in a sweep — held, and I would
   add: **when you drive `serve` from a shell, put `--token-file` outside the
   project and send `Origin`** (run 3's own appendix script does the first and
   not the second), and **note that `kill -INT` on a background `serve` is a
   no-op unless the driving shell has job control** (`set -m`). Both cost me
   real time and both would cost run 5 the same.

---

## Appendix — how to reproduce this run

Everything below ran inside `.scratch/` in this worktree; nothing outside it was
written, and no `refdes` command ran from the worktree root.

```bash
# the two wrappers (the refdes on PATH is a broken editable install)
.scratch/refdes      # PYTHONPATH=<worktree>/src        python -m refdes.cli "$@"
.scratch/refdes-old  # PYTHONPATH=.scratch/old/src      python -m refdes.cli "$@"
                     # .scratch/old/src from: git archive e2ca13e src | tar -x -C .scratch/old

# a fresh copy per scenario, and a hash with no git involved
.scratch/mkpristine.sh .scratch/run4/fresh .scratch/run4/<name>
.scratch/hash.sh <projectdir>          # find | LC_ALL=C sort | xargs sha256sum

# the read-only matrix: .scratch/ro.sh <tree|items|refdesdir|site> -- <cmd...>
#   makes a copy, applies the chmod layout, runs the command, prints output and
#   exit, flags a traceback, and chmod -R u+w the copy back

# two serve instances racing one item: .scratch/concurrent_save.py <dir> <trials>
#   free port each, --token-file under .scratch/run4/toks (outside the project),
#   X-Refdes-Token + Origin on every call, expected_revision taken from the
#   item's own edit.file_revision, SIGTERM to stop by recorded PID

# a synthetic PDF for the citation exercises: .scratch/mkpdf.py <path> <pages>
#   the same blank-page construction tests/test_citation_pages.py uses
```

Project inventory, all under `.scratch/run4/`: `pristine` (the literal
getting-started walkthrough), `green` (`pristine` with the bound loosened to
`<= 0.95 W/in^2`), `fresh` (`green` minus `_site`, the seal file and the ID
ledger — green, but never built here, so the seal write is a real write), plus
`dup`/`dup2`/`dupfm` (duplicate keys), `cfgdup` (duplicate config key),
`rev`/`rev2`/`against`/`dangle` (revise and the dangling-reference remedies),
`handrename`/`handrename2` (troubleshooting.md's trace), `pg`/`page2` (`page:`),
`lock` (corrupt citations.yaml), `init1`/`init2`/`init3` (`.gitignore`),
`serve`/`serve2`–`serve5` (SIGTERM/SIGINT/SIGKILL), `conc_t1`–`conc_t3` (the
save race), `gs/my-board` (the getting-started walkthrough, in its own git
repo), `upgrade` (built with `e2ca13e`'s `src/`, tagged `old-era`) and
`upgrade-main` (the same project on current `main`).
