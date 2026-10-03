# User-simulation release gate — run 5 (the delta, re-tested as a user)

Run 5 of the standing gate, scoped to what landed since run 4's merge
(`b068f96`). Fourteen PRs: `git log --oneline b068f96..3010883` — #145, #146,
#147, #148, #149, #150, #151, #152, #153, #154, #155, #156, #157, #158.

**Method, unchanged from runs 3–4:** documented surfaces only — `docs/`,
`--help`, real CLI invocations, real HTTP, a real local HTTP origin — and the
*original scenario* re-run rather than the fix read. Reported version is
`refdes 0.5.0`.

Setup differs from run 4 only because its wrapper existed for a broken
editable install: `refdes` here is a **real** `pip install -e '.[pdf]'` into
`.scratch/venv`, so every command below is a plain `refdes` with no wrapper at
all. Two scratch helpers are the only non-product machinery:

- `.scratch/rr <projectdir> <args…>` — `cd`s into a copy and runs `refdes`. It
  exists because I got this wrong twice, below.
- `.scratch/refdes-old` — the same against `b068f96`'s `src/`, extracted with
  `git archive b068f96 src | tar -x -C .scratch/old`, for §5.

Every synthetic project lives under `.scratch/run5/`, gitignored, made with
`cp -r` per sweep. **No `git` command ran inside a sweep directory**, no
`refdes` command was intended to run from the worktree root, and nothing under
`src/`, `tests/`, `docs/`, `items/` or a tracked `.refdes/` file was modified —
`git status --short` is empty and the commit below stages one file.

**Two harness slips of my own, recorded because both cost real time and a
run-6 harness will hit them.** (1) A `cd` inside a compound command left the
shell's idea of the working directory stale, so one `refdes check` ran against
**the worktree root** and re-derived this repo's own gitignored
`.refdes/schema.json` (22:46 mtime; content is a pure function of this repo's
unchanged config, and no tracked file or `items/` file changed — verified with
`git status` and by mtime on `items/`). Everything after that used absolute
paths. (2) `pkill -f serve_files.py` matched the *shell command line that
contained that string* and killed my own shell, which is what a 120-second
tool timeout in the middle of that run was. Run 4's process note about driving
`serve` from a shell still stands; this is the same family.

Out of scope by instruction, and not re-litigated: VS Code as an application,
Windows, real-internet `fetch` against vendor sites, real vendor PDFs through
the source picker, identity recovery. Where a claim lives only in the VS Code
extension I verified it against the data path it actually reads
(`refdes index --compact` and the serve API) and said so, rather than
pretending to have driven the editor.

---

## 0. Headline summary

**The two headline surfaces of this delta both work, and one of them has a
serious silent-upgrade hole.**

History-backed `log` sealing (#157, #158) is carefully built and honestly
documented: `history capture` is idempotent, the `edited after captured`
warning fires from both `check` and `build`, legacy seal files are kept and
read as markers, the opt-back-in overlay restores the old lock exactly, and a
deleted legacy-sealed entry gets a warning that names the file and the hash.
It matched `docs/design-log.md` in every shape I could construct — including
the awkward one. **But** on upgrade it removes the log's append-only
protection with **zero output of any kind**: `check`, `build`, `release` and
`audit` are all silent about it, `refdes --version` prints the *same* string
before and after, and `release` will stamp a rewritten entry's new text as the
truth (**B3**, medium). That is the finding a reviewer should look at first.

Citations (#145, #147, #149) and keys (#146, #151) are the strongest work in
this delta. #145's remedy sentence is exactly right and I followed it to
green. #149's `--allow-unreachable` is the clearest flag contract in the tool,
including a note for the useless combination. #151's refusal names the key, the
baseline, both titles, both hashes, and both escapes. #146 turns five
state-file corruption shapes I could throw at it into named diagnostics with
exit 1 and no traceback. **No findings in that group.**

Retired-id resolution (#150) works in `ls`, in the built item page, and in
prose — and **does not** work in the hover's data source, which makes three
specific doc claims false (**B5**, low, ~3 lines to fix).

`#152` closed run 4's F1 completely for `stub-tests`, `keys adopt`, `calc-rewrite`
and `revise`, *including the partial read-only layouts run 4 §8 asked for* —
except one shape it missed, and the shape it misses is the one run 4 said to
go looking for (**B2**, medium).

**And a pre-existing BUG survived four runs of this gate and one release:**
`refdes check` calls a project clean, and `refdes build` then dies with a raw
Jinja traceback, on a decision whose `options:` are a list of plain strings
(**B1**, high).

Nothing in this run is a regression introduced by `b068f96..3010883`. B1, B3's
*mechanism*, B4 and B5 all reproduce on `b068f96`. B2 is a `#152` gap.

---

## 1. Findings table

| # | Sev | Surface | Finding |
|---|---|---|---|
| **B1** | **BUG (high)** | `build` / `options:` | `check` reports a project clean; `build` then dies with a raw `jinja2` traceback. Pre-existing, four runs missed it. Also: `build` renders *past* a correctly-diagnosed `check` error and leaves a half-written `_site/`. |
| **B2** | BUG (medium) | `revise` on a partial read-only tree | A prefix rename that lands in some item files and not others reports `1 prose mention(s) … (a rename never edits prose)` and **exits 0**. The real cause is a read-only file; the doc explicitly promises a rollback. |
| **B3** | BUG (medium) | upgrade → history-backed `log` | Upgrading silently and totally removes append-only protection for the log. Nothing in `check`/`build`/`release`/`audit` says so, the version string does not change, and `release` stamps the rewritten text as truth. |
| **B4** | BUG (low) | `keys` / `check`, `build` | `key deleted since baseline 'r1'` is reported **twice**, once ERROR and once WARNING, with byte-identical text, in every mode. Inflates both counts. |
| **B5** | BUG (low) | `#150` retired ids / hover | A retired id does **not** resolve in `/api/item/<ref>`, and `itemsById()` indexes only `item.id`. Three doc claims about hovering a schematic id are therefore false. |
| **F1** | friction (low) | `audit` / `#147` | `audit` prints `ok hash-only` identically for a PDF whose pages were verified, a 101 MB over-threshold fetch, and a corrupt non-PDF whose `page_count_error:` is recorded in the lockfile. `#147`'s honesty stops one level short. |
| **F2** | friction (low) | `fetch` | pypdf's bare `EOF marker not found` is printed to stderr with no file, no path, no context — it reads as a refdes crash, immediately above refdes's own warning that explains the same failure. |
| **F3** | friction (low) | `check`, `build` / `#158` | The opt-back-in `types: log: sealing: build` overlay changes the project's append-only semantics and reports **nothing**. The only way to confirm it took effect is to edit an entry and see whether the build fails. |
| **F4** | friction (low) | `check`, `build` / `#157` | `edited after captured` carries no remedy and no docs URL — and the `sealing: build` error it replaces *did* say "Append a new entry with `amends: [...]` instead". |
| **F5** | nit | `check --help` / `#157` | `--help` still asserts "an entry that has never been built has no append-only protection at all", which is false for the bundled `hardware@3` log. `build --help` was updated for this delta; `check --help` was not. |
| **F6** | nit | `check --refresh --allow-unreachable` / `#149` | The `could not refresh <url>` line is printed twice — once per citation, once as the summary. |
| **F7** | nit | validation | An unknown key **inside** a `checks:` entry is accepted with no diagnostic, though the emitted JSON Schema says `additionalProperties: false` for that sub-mapping. Top-level unknown fields *are* warned about; the gap is only in list-entry sub-mappings — the same class that produces B1. |
| **F8** | nit | dangling-link message | Three different wordings of the unknown-key diagnostic depending on circumstance; the variant printed when the label names a keyless live item **omits** the `refdes keys restore …` command the other two spell out. |

---

## 2. B1 — `check` says clean, `build` tracebacks

**Severity: high.** `refdes check` is the gate people put in CI. It reported
this project as having nothing wrong with it.

### Minimal reproduction

One decision, nothing else that could be at fault:

```yaml
---
id: DEC-PWR-001
type: decision
title: Use TPS62130 for the 3V3 rail
status: accepted
options:
  - TPS62130 buck
  - MCP1700 LDO
---

Body.
```

```
$ refdes check
WARNING <project> — 3 item(s) with no coverage — see coverage.html
6 items, 0 errors, 1 warnings
[exit=0]

$ refdes build
Traceback (most recent call last):
  File "/…/.scratch/venv/bin/refdes", line 8, in <module>
    sys.exit(main())
  File "/…/src/refdes/cli.py", line 358, in cmd_build
    out_dir = render_mod.render_site(project, draft=args.dry_run)
  File "/…/src/refdes/render.py", line 1065, in render_site
    _write_html(
  File "/…/src/refdes/render.py", line 865, in _write_html
    fh.write(template.render(**context))
  File "/…/src/refdes/templates/item.html.j2", line 145, in block 'content'
    <div class="option option-{{ (opt.get('verdict') or 'considered') | lower }}">
jinja2.exceptions.UndefinedError: 'str object' has no attribute 'get'
[exit=1]
```

Nothing is rendered, and no `site written to` line is printed.

### Why

`refdes schema --json` is unambiguous about the shape:

```json
"options": {
  "type": "array",
  "items": {"type": "object",
            "properties": {"name": …, "verdict": …, "because": …},
            "additionalProperties": false},
  "description": "The alternatives considered, as name / verdict / because entries…"
}
```

`src/refdes/templates/item.html.j2:145` calls `opt.get('verdict')` on every
entry, so a scalar entry crashes. The validator, however, checks that a
**scalar** given for a list field is a scalar (`field 'options' is a options
field, but it was given a string …`) and checks that a **list of scalars** in
`checks:` is wrong — I confirmed `checks: [P_dens <= 1.5 W/in^2]` is caught,
1 error — but never checks that a **list of scalars** in `options:` is wrong.
That gap is the whole bug.

### Second half: `build` renders past a diagnostic `check` already produced

The scalar form *is* diagnosed, cleanly:

```
$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — field 'options' is
        a options field, but it was given a string 'TPS62130 buck' -- write it as a list,
        one entry per value (options: [first, second]). A scalar is never split; it is kept
        as one entry: the build cannot tell whether you meant that one value or several.
6 items, 1 errors, 1 warnings
[exit=1]

$ refdes build
Traceback (most recent call last):
  …
jinja2.exceptions.UndefinedError: 'str object' has no attribute 'get'
[exit=1]
$ ls _site
coverage.html  dec-pwr-001.html  index.html      # a half-written site, no summary line
```

`build` goes straight to `render_site` without surfacing the load-time errors,
so a perfectly good, actionable diagnostic is replaced by a stack trace — and
this time `_site/` is left half-populated with no `site written to` to tell you
the build did not finish.

### Status and shape

**Not a regression.** `PYTHONPATH=.scratch/old/src python -m refdes.cli build`
on the same tree produces the identical traceback at `b068f96`, so this has
been reachable through four runs of this gate and one release.

Two one-line-ish shapes would close it: reject a list of scalars in
`options:` at validation time (the message and remedy already exist, three
lines above in the same code), and/or make `item.html.j2` tolerate a scalar
entry. Neither needs a redesign.

---

## 3. B2 — `revise` calls a read-only refusal "prose", and exits 0

**Severity: medium.** This is run 4's F1 class again, one layout in. `#152`
fixed `stub-tests`, `keys adopt`, `calc-rewrite` and `revise` for whole-tree
and `items/`-read-only. Run 4 §8 recommendation 3 said to sweep *partial*
layouts — writable root with a read-only subdirectory — because "the
partial-write residue in F1 only appeared because I went looking for it." It
did.

### Reproduction

`revise` on a stamped project, `prefixes: {REQ-PWR: NEED-PWR}`, with **one
item file** read-only:

```
$ chmod a-w items/decisions/dec-pwr-001-regulator.md
$ refdes revise rename.yaml
changed 2 file(s):
  items/log/log-001-power-budget.md
  items/power/req.yaml
id changes:
  REQ-PWR-001 -> NEED-PWR-001
  REQ-PWR-002 -> NEED-PWR-002

1 prose mention(s) of a renamed id left behind -- these no longer resolve, and were not
rewritten (a rename never edits prose):
  items/decisions/dec-pwr-001-regulator.md:16  REQ-PWR-001 -> NEED-PWR-001
[exit=0]
```

Line 16 is `satisfies: [REQ-PWR-001@wvtjpbhajfy]` — a **structured link**, not
prose. The fully-writable control proves it:

```
$ refdes revise rename.yaml
changed 3 file(s):
  items/decisions/dec-pwr-001-regulator.md      # <- the file the read-only run skipped
  items/log/log-001-power-budget.md
  items/power/req.yaml
id changes:
  REQ-PWR-001 -> NEED-PWR-001
  REQ-PWR-002 -> NEED-PWR-002
$ sed -n 16p items/decisions/dec-pwr-001-regulator.md
satisfies: [NEED-PWR-001@wvtjpbhajfy]
```

So the writable run *does* rewrite that line; the read-only run could not, and
attributed the omission to the prose rule.

### Why it matters

`docs/cli-reference.md:61` promises the opposite, in the words of the fix's
own premise:

> `refused:` naming the file, **exit 1**, and the whole operation is rolled
> back. … a rename that lands in some item files and not others is not a
> rename.

Both halves are false for this layout: the operation is not rolled back, and
it does land in some item files and not others, at exit **0**.

The tree is not left unrecoverable — the next load refreshes the display half
(`(rewrote 1 reference(s) while loading)`) and `check` is clean — so the
*outcome* is benign. The *report* is the defect: an author reading it will go
looking for prose they need to fix by hand, when the real answer is "make
`dec-pwr-001-regulator.md` writable and re-run", which is exactly the advice
the refusal shape gives everywhere else in this delta.

Reproduced identically with `items/log/log-001-power-budget.md` as the
read-only file instead. The layouts `#152` *does* handle all refuse correctly,
including the subdirectory shape:

```
tree-ro     -> refused: cannot write items/power/req.yaml (read-only tree?) -- no item file
                was rewritten and no hash was carried forward… rolled back.   [exit=1]
items-ro    -> same                                                                    [exit=1]
subdir-ro   -> same                                                                    [exit=1]
```

**One partial layout — a single item file — takes a different path entirely.**

---

## 4. B3 — the upgrade removes append-only protection, silently

**Severity: medium.** This is the delta's headline feature meeting the delta's
most likely real-world entry condition: a project pinned to `hardware@3` on an
older `refdes`, upgrading.

### Before, on `b068f96`

```
$ refdes build            # first build seals the log
6 items, 0 errors, 1 warnings
site written to …/_site
$ ls .refdes
baselines/  boards.yaml  citations.yaml  log-seal.yaml  schema.json

$ # edit LOG-001
$ refdes build
ERROR   items/log/log-001-power-budget.md:2 [LOG-001] — LOG-001 is append-only and has been
        modified since it was sealed. Append a new entry with `amends: [LOG-001]` instead, or
        run with refdes build --reseal if the edit is deliberate.
build completed with errors (use --keep-going to exit 0)
6 items, 1 errors, 1 warnings
[exit=1]
```

### After, on `3010883`, same tree, same edit

```
$ refdes check
WARNING <project> — 3 item(s) with no coverage — see coverage.html
6 items, 0 errors, 1 warnings
[exit=0]

$ refdes build
WARNING <project> — 3 item(s) with no coverage — see coverage.html
6 items, 0 errors, 1 warnings
site written to …/_site
[exit=0]
```

`.refdes/log-seal.yaml` is still on disk, still holding `LOG-001: c58470972020243f`,
and is now inert. Nothing in that output says so. Not `check`, not `build`, not
`ls`, not `audit`:

```
$ refdes audit
Append-only entries edited after sealing:
  LOG-001  (legacy seal: recorded hash only; original content was not captured)
```

That line *is* the only signal anywhere, it appears in `audit` alone, and it
only appears because the hash differs — i.e. **only if you already broke the
rule you are looking for evidence of**.

### And `release` will stamp the rewrite as truth

A project with every gate rule relaxed, a release stamped, then a log entry
rewritten wholesale, then a second release:

```
$ refdes release rel-b
WARNING <project> — 2 item(s) with no coverage — see coverage.html
WARNING <project> — 1 requirement(s) satisfied but not verified — see coverage.html
8 items, 0 errors, 2 warnings

release 'rel-b' stamped: 8 items, all gates passed.
[exit=0]
```

```
$ refdes audit
Append-only entries edited after sealing:
  (none)
Entries edited after captured:
  (none)
Since last release (rel-b, 2026-10-03T03:04:56Z):
  changed   0
  added     0
  removed   0
  relabelled 0
  (8 unchanged)
```

while the two baselines disagree about the entry:

```
rel-a.yaml: LOG-001: {hash: c58470972020243f, …}
rel-b.yaml: LOG-001: {hash: 962ffe5b16030fce, …}
```

The rewritten text is now the recorded truth, both `audit` sections report
`(none)` / `(8 unchanged)`, and the only way to see the rewrite is to diff two
baseline files by hand.

### There is no in-product way to learn this happened

`refdes --version`:

```
$ PYTHONPATH=.scratch/old/src python3 -m refdes.cli --version
refdes 0.5.0
$ .scratch/venv/bin/refdes --version
refdes 0.5.0
```

Same string. Run 4 §8 question 4 asked whether there is any in-product way to
learn a breaking change exists without reading `CHANGELOG.md`; **the answer is
still no**, and this delta makes that worse rather than better, because it
changes behaviour with no string to compare. `CHANGELOG.md` documents it
thoroughly — `[Unreleased]` item 6 spells out the switch, the overlay, and the
one case that turns *stricter* — and `docs/design-log.md`'s
`history-backed types` section states the tradeoff in plain words
("An entry that was never captured has no snapshot to compare against, so
editing it produces **no diagnostic at all**"). The problem is not the
documentation; it is that `hardware@3` is **unreleased**, so the exact
population that gets the silent downgrade is the population that has been
pinned to it during development, where the version string cannot move.

### What I would want

One line, once, on the first `check`/`build` after the switch, something like a
`WARNING <project> — 'log' is history-backed as of this refdes version: entries
are no longer sealed at build. .refdes/log-seal*.yaml (1 record) is kept as a
legacy marker only. Run 'refdes history migrate-seals' to record it, or set
types: log: sealing: build in refdes-schema.yaml to keep the build-time lock.`
It is discoverable, it is one-time, and it is the difference between "I turned
off my append-only log" and "something happened to my log". Failing that, the
`edited after captured` warning's silence for uncaptured entries (F4) is the
part most worth closing: `history capture` is idempotent and cheap, so `audit`
could at least list history-backed append-only types that have **no** capture,
as "never captured — an edit to these leaves no trace".

---

## 5. The rest of the new surfaces, as a user met them

| Surface | Verdict | What I did and saw |
|---|---|---|
| **`log` is history-backed (#158, #157)** | works, exactly as documented | Edit an uncaptured entry → `check`, `build`, `audit` all silent, no seal file created, `6 items, 0 errors, 1 warnings`. Matched `docs/design-log.md` verbatim, including "no diagnostic at all". |
| **`history capture`** | works | `captured LOG-001: manual capture`, exit 0. Second run: `LOG-001 is already captured; nothing was written`. Works on **any** item type, not just append-only ones — `captured REQ-PWR-001: manual capture`, and a later edit of that requirement *does* produce `edited after captured`. Bogus id: `error: no item 'NOPE-001' in this project (looked up by display id, then surrogate key)`, exit 2. `--help` is accurate about "Says 'captured', never 'final'". |
| **`edited after captured` on check *and* build** | works | `WARNING items/log/log-001-power-budget.md:2 [LOG-001] — LOG-001: edited after captured -- current semantic content differs from the snapshot in captured event b2d097c6-…`, exit codes unchanged, on both commands. Message is clear (F4: no remedy, no URL). |
| **`history migrate-seals`** | works | `legacy-seal marker for LOG-001 (.refdes/log-seal.yaml)` / `recorded hash only; original content was not captured; the seal file is left untouched` / `1 legacy-seal marker(s) written, 0 already present`. Matches the docs exactly. |
| **legacy seal file kept as a marker** | works | `build`, `check`, `--reseal` and `revise` left `.refdes/log-seal.yaml` byte-identical through all of it. Deleting a legacy-sealed entry warns exactly as documented: `LOG-001 has a legacy seal record in .refdes/log-seal.yaml but is no longer in the project. The record holds a hash only (c58470972020243f) … restore it from version control if the removal was not deliberate. The record is kept as it is.` |
| **`build --reseal` on a history-backed type** | works | `--reseal: sealing no longer applies to the 'log' type; nothing was rewritten. Its legacy seal records are kept as they are, and an edit to a captured entry is reported as edited after captured instead.` — the best "nothing happened, here's why and here's what does happen instead" sentence in the tool. Same for `--reseal <board>`. Captures nothing, writes no file. |
| **opt-back-in overlay `types: log: sealing: build`** | works, silent (F3) | `refdes-schema.yaml` with exactly that. First build writes `.refdes/log-seal.yaml`; an edit becomes the original build error at both `check` and `build`, exit 1; `--reseal` writes a proper `reseals:` record. A typo'd value is caught: `configuration error: refdes-schema.yaml: types.log.sealing must be one of build, history, got 'builds'`, exit 2. Putting `types:` in the wrong file is caught: `configuration error: refdes-project.yaml: types does not belong here -- the project's own schema overlay lives in refdes-schema.yaml, …`, exit 2. But no output anywhere confirms the overlay *took effect*. |
| **retired calc spelling on switch** | works, with a remedy | A `P_total : W = …` line inside an old-sealed log entry: `b068f96` said `WARNING … the 'name : unit = expression' spelling was retired …`; `3010883` says `ERROR` and exits 1, and `refdes calc-rewrite --dry-run` prints `would rewrite 1 calc line(s) in 1 file(s): items/log/…:15  P_total : W = 3.3 V * 120 mA -> P_total = 3.3 V * 120 mA \| W`. This is the one *stricter* case and it is the best-handled breaking change in the delta: named remedy, named command, and `check` catches it before `build` does. |
| **`ls` retired-id resolution (#150)** | works | `refdes ls REQ-PWR-007` → `REQ-PWR-002  requirement  Ripple on 3V3 shall be under 25 mV (formerly REQ-PWR-007)`. Lowercased works. `refdes ls REQ-PWR-002` prints no marker. A plain `ls` is byte-identical to a project with no `former_ids:`. Reused-id case: the live item is listed and a note says why (`note: REQ-PWR-001 is a live item's id again, so that item is listed above; REQ-PWR-002 still records it as a former id, which 'refdes check' reports as an error`). |
| **item page former ids (#150)** | works | `_site/req-pwr-002.html`: `<p class="small muted">formerly known as <code>REQ-PWR-007</code></p>` directly under the `<h1>`. |
| **prose former-id resolution** | works | Bare `REQ-PWR-007` and explicit `[[REQ-PWR-007]]` in a decision body both render as `<a class="ref ref-former" href="req-pwr-002.html" …>REQ-PWR-002</a><span class="ref-former-marker" title="REQ-PWR-002 was formerly REQ-PWR-007">(formerly REQ-PWR-007)</span>` — visible, not a silent redirect. |
| **hover retired ids (#150)** | **does not work — B5** | See below. |
| **malformed `page:` (#145)** | works, run 4's F2 fixed | `citations[0]: page: '2-4' is not a page number -- page: must be a positive integer, counted from 1. **One entry names one page, so a range is one entry per page for the same path.** See https://squishiba.github.io/refdes/troubleshooting.html#citations.` I followed the remedy (two entries, `page: "2"` and `page: "4"`) and reached `6 items, 0 errors, 1 warnings`. |
| **`page:` shape coverage (#145)** | works, and better than expected | `"0"`, `"-1"`, `"1.5"`, `"p. 4"`, `"1e3"`, `""` → the rule sentence. `"eight"`, `"xiv"`, `"iv"` → the rule sentence **plus** `A printed page number is not a page index: page: counts the PDF's own sheets from 1, the same number the rendered link opens.` — that second sentence is the actual reason, and it is only given for the shapes where it is the real cause. `"2 "` and `"02"` are accepted. All exit 1. |
| **`page:` out of range** | works | `page: "99"` on an 8-page PDF: silent at `check` until a `fetch` records `page_count: 8`, then `WARNING items/…:2 [DEC-PWR-001] — docs/manual.pdf: page 99 is not in this document -- it has 8 page(s)` on every later `check` and `build`, plus the `(cited by DEC-PWR-001)` attribution on the `fetch` line itself. |
| **>100 MB fetch (#147)** | works | A 101 MB citation: `WARNING  http://127.0.0.1:8802/big.pdf: fetched 105907085 bytes (101.0 MB), over the 100.0 MB a fetch is warned at -- pinned anyway, no local copy kept (hash-only)`, `bytes:` and `sha256:` both recorded, exit 0. Honest about the decision it made. |
| **`check --refresh` unreachable (#149)** | works | Two errors, exit 1: the per-citation `could not refresh <url>: <urlopen error [Errno 111] Connection refused> -- upstream drift was NOT verified for this citation (no bytes arrived, so there is nothing to compare the pin against)` and the run-level `1 pinned citation could not be refreshed, so upstream drift was NOT verified for it -- the run cannot claim to have checked it. Fix the network or the urls, or pass --allow-unreachable …`. |
| **`--allow-unreachable` (#149)** | works | Both `could not refresh` lines drop to `WARNING`, the summary changes to `drop --allow-unreachable to fail the run on this instead`, `6 items, 0 errors, 3 warnings`, exit 0. Reachable source + `--refresh` → clean, exit 0. And: `note: --allow-unreachable without --refresh has nothing to allow -- no pinned citation is re-fetched, so none of them can be unreachable.` That is the clearest useless-combination note in the tool. |
| **`keys restore` vs a baseline (#151)** | works, exemplary | `refused:` naming the key, the baseline, **both** titles and **both** hashes, and both escapes: `--force` for the same-item-edited-since case, "give the item a new display id so it is not mistaken for the old one" for the rest. Exit 1. The Layer-3 diagnostic that recommends the command is the one that led me there, and it is precise about what it cannot know. |
| **`keys restore` refuses on a broken project** | works | `would refuse:` / `restored project would still have build errors -- fix them or supply all lost keys in one command`, exit 1. It did not restore the key until I fixed the unrelated `checks:` entry — correct, and the refusal told me which entry. |
| **malformed stored key (#146)** | works | `key '987654321' is malformed: expected exactly 11 characters. A key is written by refdes and never edited by hand, so this line has been corrupted -- restore it from git rather than guessing. If YAML already converted an unquoted key and rewrote this file, its original spelling cannot be recovered here.` — project-relative path, exit 1, **no traceback**, from `check`, `build` *and* `audit` (audit prints it as its first line and exits 1). Reproduced in a `.refdes/baselines/r1.yaml` and in a `.refdes/log-seal.yaml` `reseals:` record. |
| **`ls` workspace column (#148)** | works | With `workspaces:` declared and `item_layout: workspace`, the column sits before the board column; an item in no workspace leaves it blank; the column is dropped entirely when every row is blank (`--file items/board-b/shared.md` → `BND-CAN-001  bound  CAN bitrate`); no `workspaces:` block → no column, byte-identical to before. `--workspace` combines as a plain AND with `--board`. The unregistered-workspace and missing-board warnings name both remedies. Per-workspace `coverage-*.html` / `document-*.html` / `summary-*.html` / `tree-*.html` all written. Board/workspace key collision refused with the exact documented sentence, exit 2. Cross-workspace lint fires on the right pairs and exempts `shared: true`. |
| **run 4 F1 / read-only (`#152`)** | fixed | See §7. |

### B5 — the retired id does not resolve in the hover

`docs/ids.md:261-272`:

> The retired id is what the world outside this project keeps using, so **every
> place that answers "what is REQ-PWR-001?" answers it** … every hover preview
> card for it carries a *formerly known as* row; the VS Code hover says the
> same.

`editors/vscode/README.md:72-75`:

> An item that was renumbered also says *formerly known as …*, so **hovering the
> id you have from a schematic or a commit message tells you which item it is
> now**.

Both are half true. The hover *displays* `formerly known as` when you hover
the **live** id. It does not **resolve** a retired id, in either of the two
layers that would have to do it:

```
$ curl -H "X-Refdes-Token: $T" -H "Origin: http://127.0.0.1:8731" \
       "http://127.0.0.1:8731/api/item/REQ-PWR-007"
{"error": "no item matches 'REQ-PWR-007'"}
$ … /api/item/req-pwr-007
{"error": "no item matches 'req-pwr-007'"}
$ … /api/item/REQ-PWR-002
{"id": "REQ-PWR-002", "former_ids": ["REQ-PWR-007"], "key": "6bbwvs4wymw"}
```

`serve/api.py:89-104` (`_find_item`) tries the `project.items` dict key, then
`project.item_by_ref` — neither reaches `item.former_ids`. And the extension
never gets that far: `editors/vscode/extension.js:198-203`

```js
function itemsById() {
  const map = new Map();
  if (!index) return map;
  for (const item of index.data.items || []) map.set(item.id, item);
  return map;
}
```

…keys the map on `item.id` only, and `provideHover` (`:510-511`) does
`if (!item) return null`. So the hover on a schematic id is silent, and the
live snapshot it would fall back on 404s.

The data needed is already in the index — I checked:

```
$ refdes index --compact | jq '.items[] | select(.former_ids | length > 0)'
{ "id": "REQ-PWR-002", …, "former_ids": ["REQ-PWR-007"] }
```

So the extension-side fix is a second `map.set` per `former_ids` entry (and
marking the row so the hover says which id it matched), and the server-side
fix is consulting `project.former_ids` in `_find_item`. Both small. I did not
drive VS Code — the claim is verified against the two functions the hover reads
from, which is the strongest statement I can make without the editor.

---

## 6. Friction and nits, in full

### F1 — `audit` reports the same line for three different outcomes

`#147`'s stated goal is "stop audit claiming it checked". It does stop claiming
that — the column now says `hash-only` — but it says it identically for
everything, including a document whose pages could not be counted at all:

| what was fetched | lockfile | `audit` says |
|---|---|---|
| 8-page PDF, pages verified, `page: "99"` out of range | `page_count: 8` | `ok  hash-only  cited by DEC-PWR-001` |
| 101 MB file, over the warn threshold, unreadable as a PDF | `page_count_error: 'counting a document''s pages failed…'` | `ok  hash-only  cited by DEC-PWR-001` |
| 40-byte file that is not a PDF | `page_count_error: 'counting a document''s pages failed…'` | `ok  hash-only  cited by DEC-PWR-001` |

`fetch` records `page_count_error:` in the lockfile and `check` reports it as a
warning. `audit` — the command whose job is to summarise what state the project
is in — never mentions it. Given that `#147` exists because "audit claiming it
checked" was the problem, the same honesty applied one level up is the natural
follow-up, and the data is already in the lockfile.

### F2 — pypdf's bare stderr line

```
$ refdes fetch
EOF marker not found
WARNING  http://127.0.0.1:8803/bad.pdf: the pages could not be counted to check the page
          numbers cited here -- counting a document's pages failed: pypdf could not read the
          PDF: Stream has ended unexpectedly
fetched  http://127.0.0.1:8803/bad.pdf  sha256=978f7f5073c7...  hash-only
```

`EOF marker not found` is pypdf's own logger output, unattributed, on its own
line, immediately above a refdes message explaining the same failure. To a user
it reads as the tool crashing and then recovering. One line of routing (or one
`logging` config) would keep it inside the message that already says it.

### F3 — the opt-back-in overlay is silent

Adding three lines to `refdes-schema.yaml`:

```yaml
types:
  log:
    sealing: build
```

changes the project from "an edit to a log entry leaves no trace" to "an edit
to a log entry fails the build". `check` and `build` print nothing about it.
The only output on the first run after the edit is an unrelated one-time
`.refdes/schema.json was older than refdes-schema.yaml -- refreshed`, which
happened to fire in my run only because the file had never been generated.
There is no `note:`, no `WARNING`, nothing confirming the overlay resolved.
A user who adds it and runs `check` cannot tell whether it worked, and a user
whose *intent* was the overlay but who forgot it has no way to discover that
either — the state is indistinguishable from a deliberate history-backed setup.

### F4 — `edited after captured` dropped the remedy

The `sealing: build` error it replaces says, in full:

> Append a new entry with `amends: [LOG-001]` instead, or run with refdes build
> --reseal if the edit is deliberate.

The replacement says:

> `LOG-001: edited after captured -- current semantic content differs from the
> snapshot in captured event b2d097c6-16e8-5511-916a-79b5b7f32dff`

For an `append_only` type the old advice (`amends:`) still applies and is still
the right move; the new message drops it. The event id is the right thing to
name, and it is what makes the trail auditable — but a warning that tells you
your append-only log was edited, without telling you how an append-only log is
supposed to be edited, is a step back for the exact reader who needs it most.
Every other new diagnostic in this delta carries a remedy or a URL; this one
carries neither.

### F5 — `check --help` is stale for history-backed types

`refdes check --help`:

> A seal exists only once 'build' has run over the entry, so an entry that has
> never been built has no append-only protection at all, however many clean runs
> of this command has behind it.

False for the bundled `hardware@3` log: it never gets a seal, and its protection
is `refdes history capture`, not `build`. `build --help` *was* updated in this
delta — `--reseal`'s description now ends "A `sealing: history` type has nothing
to reseal and is left untouched" — and `docs/cli-reference.md:140-144` and
`docs/troubleshooting.md:440-444` both handle it. Only this one epilog sentence
was missed.

### F6 — the refresh line, twice

```
$ refdes check --refresh --allow-unreachable
WARNING <project> — could not refresh http://127.0.0.1:8801/manual.pdf: <urlopen error [Errno 111] Connection refused>
WARNING <project> — 1 pinned citation could not be refreshed, so upstream drift was NOT verified for it -- drop --allow-unreachable to fail the run on this instead
```

The URL and the errno appear in both lines. With two citations it would appear
three times. The summary only needs the count.

### F7 — unknown keys inside a `checks:` entry are not validated

```yaml
checks:
  - rule: P_dens stays inside the packaging limit
    value: P_dens
    against: BND-PWR-001
    exrta: typo of extra
```

```
6 items, 0 errors, 1 warnings     # no diagnostic at all
```

The emitted JSON Schema declares `additionalProperties: false` for that
sub-mapping, and a top-level typo *is* caught (`WARNING … unknown field
'nonsense_field' on decision.`), so the gap is specifically list-entry
sub-mappings — the same class of gap that produces B1. Low, but it means the
published schema and the enforced schema disagree.

### F8 — three wordings, one of them without the command

The unknown-key diagnostic varies with circumstance, and the variant printed
when the label names a **live item that has no key** drops the remedy the other
two carry:

```
# label names nothing live
… satisfies points at key 'wvtjpbhajfy' (labelled REQ-PWR-001), which no item declares.
  A live item labelled REQ-PWR-001 declares key '57x0gq5x86p'. … If it is the same item, run
  `refdes keys restore DEC-PWR-001@yza0trq9f0a --dry-run`, then repeat without --dry-run…

# label names a live item with no key
… records points at key 'yza0trq9f0a' (labelled DEC-PWR-001), which no item declares. The
  label may be stale; the key is what resolves. The target may have been deleted or its key
  lost or changed. Check git history before restoring the original key or removing the reference.
```

Both are honest and both name the trap. The second just does not tell you there
is a command, when there is.

---

## 7. Fixed since run 4

| Run-4 finding | Verdict | Evidence |
|---|---|---|
| **F1** — `stub-tests` and `revise apply` print a raw `PermissionError` traceback; `stub-tests` leaves a half-finished write with no summary | **fixed** (`#152`) | See the matrix below. `stub-tests` and `revise` now `refused:` with the file named and a rollback; `stub-tests` names what landed; `keys adopt` and `calc-rewrite` — run 4 §7 listed as plausible survivors — also refuse cleanly. **One partial layout survives, as B2.** |
| **F2** — the one breaking diagnostic with no remedy and no docs URL (`page: '2-4'`) | **fixed** (`#145`) | Now names the two-entry remedy and carries the troubleshooting URL; I followed it to green. Went further than asked: alphabetic and roman-numeral shapes get a second sentence explaining *why* (printed page number vs PDF sheet index). |
| **F3** — duplicate-key diagnostic repoints references in other files with no warning | **still open** | Re-reproduced exactly. A composite `satisfies: [REQ-PWR-002@6bbwvs4wymw]` in another file silently became `satisfies: [REQ-PWR-004@6bbwvs4wymw]` with only `(rewrote 1 reference(s) while loading)` on stdout, while `items/power/req.yaml` reported five duplicate-key errors. Not in this delta's scope. |
| **F4** — `getting-started.md` says "four files" then "add those three lines" | **fixed** | `docs/getting-started.md:74-86` now reads "a `.gitignore` to keep **four paths** out of your commits" and "add those same **four** lines yourself, one per line — except any one your file already covers". Internally consistent, and the `init` output agrees. |
| **F5** — `troubleshooting.md`'s sample `check` block omits a `WARNING` line | **fixed** | `docs/troubleshooting.md:341-345` now carries `WARNING <project> — 2 item(s) with no coverage — see coverage.html`, plus a parenthetical saying it is the two-item project's own and is there "because the block is what the command prints, in full." |
| **N5** — `ls` has no workspace column | **fixed** (`#148`) | Column appears only where `workspaces:` is declared, positioned before the board column, blank for items in no workspace, and dropped entirely when every row is blank. A project with no `workspaces:` block is byte-identical to before. |

### The read-only matrix run 4 §8 asked for

Built as a *list* from `--help` rather than from the last report, across whole
tree, `items/`, `.refdes/`, one read-only subdirectory, and one read-only item
file. Every line below is verbatim, path-ablbreviated.

```
check                    6 items, 0 errors, 2 warnings           [exit=0]   (degrades, names schema.json)
build                    error: cannot write the site to <D>/_site (Permission denied)
                         -- nothing was rendered.               [exit=2]   (refuses)
id                       (load could not write this file (read-only tree?) -- .refdes/schema.json…)
                         no items are missing an id             [exit=0]   (degrades)
ls                       full listing                            [exit=0]
audit                    full output                             [exit=0]
index                    full JSON                               [exit=0]
revision r9              error: cannot write .refdes/baselines/r9.yaml (read-only tree?) --
                         revision 'r9' was not stamped. …         [exit=2]   (refuses)
stub-tests               refused: cannot write items/stub-tests.md (read-only tree?) -- no stub
                         was written for BND-PWR-001, … Make the tree writable and run it again.
                                                                            [exit=1]   FIXED
stub-tests --dry-run     would write 4 stub(s) to items/stub-tests.md: …
                                                                            [exit=0]
calc-rewrite             refused: cannot write items/decisions/dec-pwr-001-regulator.md
                         (read-only tree?) -- no item file was rewritten and no hash was carried
                         forward…  rolled back.                    [exit=1]   FIXED (run 4 untested)
fetch                    (load could not write this file …)  0 citation(s) processed  [exit=0]
former-ids propose       error: no baseline stamped yet …         [exit=1]
history capture LOG-001  error: cannot write .refdes/history/objects/c3563d1f… (read-only tree?) --
                         nothing was captured. …                 [exit=1]
keys adopt               refused: adoption failed; rolled back: [Errno 13] Permission denied:
                         '<D>/.refdes/keys-adopted.yaml'           [exit=1]   FIXED
```

`stub-tests`, partial layout (three boards, `items/gamma/` read-only) — the
shape run 4 said only appears if you go looking for it:

```
refused:
  cannot write items/gamma/stub-tests.md (read-only tree?) -- no stub was written for
  REQ-GAMMA-001 in this file. Make the tree writable and run it again; the stubs that did land
  are not re-emitted.
wrote 1 stub(s) to items/alpha/stub-tests.md: REQ-ALPHA-001
wrote 1 stub(s) to items/beta/stub-tests.md: REQ-BETA-001
wrote 2 stub test(s) across 2 file(s)
[exit=1]
$ chmod -R u+w items && refdes stub-tests
wrote 1 stub(s) to items/gamma/stub-tests.md: REQ-GAMMA-001
wrote 1 stub test(s) across 1 file(s)
```

Exactly the documented behaviour: what landed stays, what was refused is named,
and the re-run picks up precisely the missed one. That sentence in
`docs/cli-reference.md` is now true.

`revise`, all layouts except one: tree, `items/`, and one read-only
subdirectory all refuse with `cannot write items/power/req.yaml (read-only tree?)
-- no item file was rewritten and no hash was carried forward, so the tree is
exactly as it was found. Make the tree writable and run it again.` + `rolled
back.`, exit 1. **One read-only item file takes the B2 path instead.**

**Everything else came back with `6 items, 0 errors, 1 warnings` and no refusal
noise under `--no-write`**, and the `(read-only tree?)` filter run 4 depends on
still catches every refusal except the two documented exceptions (`keys adopt`,
`keys restore`), which is what `docs/cli-reference.md:50-51` now claims.

**B4, found while building that matrix.** Reachable from `check`, `build`,
`--no-write check` and `--no-write build`, and present on `b068f96` too:

```
ERROR   items/power/req.yaml:9 [REQ-PWR-001] — key deleted since baseline 'r1': was
        'wvtjpbhajfy', now no key is declared. The old key is recorded for REQ-PWR-001 in
        baseline 'r1'. … Add the field `key: wvtjpbhajfy` back to the item that starts at
        items/power/req.yaml:9 … Or, if this really is a new, different item, give it a new
        display id so it is not mistaken for the old one -- a fresh key will then be minted
        for it.
WARNING items/power/req.yaml:9 [REQ-PWR-001] — key deleted since baseline 'r1': was
        'wvtjpbhajfy', now no key is declared. …            <- byte-identical
6 items, 3 errors, 2 warnings
```

Byte-identical text, one ERROR and one WARNING, from
`src/refdes/keys.py:249` `_validate_deleted_keys` (`project.error`) and
`src/refdes/keys.py:563` `report_deleted_keys` (`project.warn`) — both calling
the same `deleted_key_message`, and both on the normal load path. The
user-visible cost: one finding is counted twice, and the counts
(`3 errors, 2 warnings`) are two higher than the number of things that are
wrong.

---

## 8. Still open from run 4

**F3**, restated, since it is the only one left and it has now survived a
second run:

> The duplicate-key diagnostic protects the file that reports the merge, but not
> the files whose references it repoints.

Reproduced with run 4's exact shape. The reporting file is left untouched (five
duplicate-key errors, `items/power/req.yaml` still on disk as written). But in
another file:

```
$ sha256sum items/decisions/dec-pwr-002-ripple.md
9f792fa308735ee8be0e8bbaee5e7b62e56f0955a0f5272aec245c56388f5d5a
$ refdes check
(rewrote 1 reference(s) while loading)
…
$ sha256sum items/decisions/dec-pwr-002-ripple.md
6382ab08d3ed47d4bce81bd022c2d0928c39d68913fabdb253ecc707d4cc1697
$ grep -n satisfies items/decisions/dec-pwr-002-ripple.md
7:satisfies: [REQ-PWR-004@6bbwvs4wymw]
```

`satisfies: [REQ-PWR-002@6bbwvs4wymw]` became `satisfies: [REQ-PWR-004@6bbwvs4wymw]`
with no warning beyond the bare `(rewrote 1 reference(s) while loading)`, while
the merge that caused it was producing five errors one file over. Run 4's
cheapest fix still stands: one sentence in the duplicate-key message — *a
reference in another file may have been repointed at the surviving item while
this was broken* — plus the `(rewrote …)` line naming the files it touched.

Two shapes of the same class where the tool did the *right* thing, recorded so
run 6 does not re-derive them: a **bare** reference to an id that failed to load
gets the dangling-reference remedy (naming all three explanations and the fix)
rather than being silently refreshed, and the label-refresh warning does fire —
`check against references 'BND-PWR-001@02qpcct8665', but that key is BND-THM-001
and BND-PWR-001 is a different live item. Refusing to refresh the label until you
confirm which was meant.` — when the stale label names a *different live* item.
F3 is the residual where the stale label names nothing live at all.

---

## 9. Upgrade path: a `b068f96`-built project on `3010883`

Built entirely with run 4's `refdes` — `init`, `id`, `fetch`, `build`,
`revision r1` — with two boards, a stamped baseline, a seal file, an ID ledger,
a board manifest, a lockfile with `page_count: 12`, and composites throughout.
Then handed to current `main`.

**Every command works with no migration step, no configuration error, and no
traceback:**

| command | result |
|---|---|
| `check` | `5 items, 0 errors, 1 warnings`, exit 0 |
| `ls` | 5 rows, board column, **no** workspace column (correct — no `workspaces:`) |
| `audit` | exit 0; `Citations: docs/manual.pdf — ok hash-only cited by DEC-PWR-001` |
| `index --compact` | full JSON, composites resolved |
| `fetch` | `skipped  docs/manual.pdf  sha256=efd2bb5d190c...  hash-only`, exit 0 |
| `stub-tests --dry-run` | `would write 3 stub(s) to items/board-a/stub-tests.md: BND-PWR-001, REQ-PWR-001, REQ-PWR-002` |
| `former-ids propose` | `no candidate former-id mappings found`, exit 0 |
| `history migrate-seals` | `legacy-seal marker for LOG-001 (.refdes/log-seal-board-a.yaml)`, exit 0 |
| `build` | site written, exit 0, seal file untouched |
| `release rel-a` | ran the gate; `FAIL uncovered_requirements BND-PWR-001, REQ-PWR-002` — a real finding about my project, not a migration problem |

The old lockfile, the stamped baseline, the seal file, the board manifest and
the ID ledger are all read without complaint. **The only behaviour change is
B3**: the log stops being sealed, silently. The other breaking changes run 4
found (`page:`, duplicate keys, the config split) are all either absent from my
project or fully diagnosed with a remedy.

Nothing in the tool mentions the migration. No advice to run anything, no
notice that the seal file changed meaning. Run 4 §8 question 4 is unanswered
for the fourth consecutive run, and this delta is the first where it costs
something real.

---

## 10. What wasn't covered

- **The `log` type's `follows:`-driven capture** was not exercised: `docs/design-log.md` says `hardware@3` declares no `follows:`, so the `follows:`-freezes-an-edge path cannot be reached without inventing a type. `history capture` covers the same code path by hand.
- **A `sealing: history` type declared by the project itself** (not via the overlay on a standard type) was not built. The overlay covers the semantics; the schema rule (`history` requires `append_only: true`, and a subtype cannot declare it under a `build` parent) was not tested by construction.
- **`history redact`** was read (`--help` only) and not driven. It is not new in this delta and redacting a captured log entry mid-sweep would have destroyed the fixtures the rest of §5 depends on.
- **VS Code was not driven.** B5 is verified against `editors/vscode/extension.js:198-203, 505-517` and `serve/api.py:89-104` — the two functions the hover reads from — plus the serve API over real HTTP. I did not claim to have hovered anything.
- **`stub-tests` was not tested against a read-only *workspace* folder** (`item_layout: workspace`, one of several read-only), only a board. The one-scope-per-file design makes it the same code path, but I did not confirm it.
- **The `page:` and >100 MB exercises used synthetic PDFs and a local HTTP origin**, not vendor datasheets or the real internet. `#145`/`#147` are message- and threshold-shaped, so neither depends on egress; `pdf-picker-exercise.md` and `remote-fetch-exercise.md` from earlier runs cover the rest.
- **`check --refresh` was tested against connection-refused only**, not DNS failure, timeout, or an HTTP 4xx/5xx. The message interpolates the underlying reason in all cases and the four are enumerated in `--help`, so I expect them to be uniform — unconfirmed.
- **`--allow-unreachable` and `--refresh` combined with a real drift** (a source that answers with different bytes) was not driven; I only exercised the unreachable half of `#149`.
- **`standard upgrade --to 2`** on a `hardware@3` project is refused (`project is already at hardware@3, not below the requested --to 2`, exit 2), so the hash-format-rewrite row in the read-only table was not reachable and is unconfirmed.
- **Multi-root VS Code, Windows, macOS, identity recovery** — out of scope by instruction.

---

## 11. Suggested shape for run 6

1. **Take B1 first.** It is a `check`-clean / `build`-traceback divergence on an
   ordinary authoring mistake, it has been reachable through four runs and one
   release, and it points at a general question the gate has never asked:
   *for every list field, is a list of scalars validated the way a scalar is?*
   Answer it as a list from `refdes schema --json`, not from one finding — that
   is how F1 and F3 were both found. F7 is the same list.
2. **Then B2**, as the last entry in run 4's read-only matrix. `#152` did the
   work; what it missed is the layout run 4 named. A sweep that enumerates
   *(command × which of its writes is it about to make × which subset of the
   tree refuses)* rather than *(command × tree layout)* would find it, because
   the answer here is not about the tree at all but about how many of the
   planned rewrites landed.
3. **Close B3 with one line.** A one-time project-level notice on the first
   load after the switch, naming the seal files found and both escapes
   (`history migrate-seals`, `types: log: sealing: build`), turns "my log lost
   append-only protection and nobody told me" into a documented decision. The
   version string cannot help while `hardware@3` is unreleased.
4. **Keep the upgrade-path pass, and add one question to it:** for every
   behaviour change between two versions, is there any *in-product* signal? So
   far the answer has been no for four runs running. Run 6 could make it a
   table — breaking change / user-visible signal / remedy — which is the thing
   that would let it be closed rather than re-observed.
5. **B5 is a 3-line fix with a reviewable claim.** `_find_item` consulting
   `project.former_ids`, and `itemsById()` indexing `former_ids` entries too.
   Worth doing because three doc sentences currently promise it.
6. **The three areas runs 3–5 have now left, unchanged:** real-internet `fetch`
   (redirects, `rev:` inference, a 404 on a pinned citation), a real vendor PDF
   with a real outline through the source picker, and VS Code under a real
   instance — including, now, a hover on a retired id, which is the one VS Code
   claim in `README.md` that has a failing test in the data.
7. **Process, carried forward and extended.** Everything in run 4's §8.6 still
   holds, and two of my own from this run: **drive every sweep through a helper
   that hard-codes the project directory** rather than relying on a `cd` in a
   compound command, and **never `pkill -f <pattern>` when the pattern also
   appears in the command line you are running** — it will kill your own shell
   and you will read the resulting timeout as a product hang.

---

## Appendix — how to reproduce this run

```bash
python3 -m venv .scratch/venv && .scratch/venv/bin/pip install -e '.[pdf]'   # a real refdes, not a wrapper

.scratch/rr <projectdir> <refdes args…>   # always run in the copy, never the repo root
.scratch/ro2.sh <src> <tree|items|refdesdir|subdir|srcfile|ids> <cmd…>
                                         # copy, chmod layout, run, print, chmod back, flag a traceback
.scratch/refdes-old <args…>              # b068f96's src; .scratch/old/src from
                                         #   git archive b068f96 src | tar -x -C .scratch/old
.scratch/mkpdf.py <path> <pages>         # the blank-page construction tests/test_citation_pages.py uses
.scratch/srv/serve_files.py <dir> <port> # a local origin for the >100 MB and --refresh exercises
```

Project inventory, all under `.scratch/run5/`: `base` (a green six-item
synthetic board, the fixture for most sweeps), `p1` (the walkthrough that
produced it), `log1` / `logold` / `upg` / `optin` / `logdel` / `calold2` /
`sealbad` (the history-backed log: history-backed, `sealing: build`-era, the
upgrade, the opt-back-in overlay, a deleted legacy-sealed entry, the
retired-spelling escalation, a malformed legacy seal), `fi` / `fi2` / `fi3`
(retired ids in `ls`, prose, and the reused-id case), `cit` (malformed and
out-of-range `page:`), `rem` / `big` / `bad` (citations over a local HTTP
origin), `kr` (the `#151` baseline conflict), `amb` / `amb2` / `amb3` (`#146`'s
YAML-ambiguous and reserialized keys), `ws` (workspaces, boards, the
cross-workspace lint, the namespace collision), `mb` (three boards, for the
partial-layout `stub-tests`), `dup` / `dup2` / `dup3` (run 4's F3),
`rv` / `rw` / `_lf*` (read-only layouts and the list-field shapes), `rel`
(release gate with every rule relaxed), and `upgrade` (built entirely with
`b068f96`'s `src/`).