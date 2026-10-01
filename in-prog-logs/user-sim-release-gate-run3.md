# User-simulation release gate — run 3 (the delta, re-tested as a user)

Run 3 of the standing gate, scoped to what changed since run 2's report
(`ded3100`). Seventeen commits have landed since, and between them they address
every run-2 finding: `git log --format='%h %s' ded3100..HEAD` and the sixteen
`changelog.d/` fragments they added (a seventeenth, an earlier cut of the
VS Code README note, was added and then replaced within the same series).

**Method, unchanged from runs 1 and 2:** use only documented surfaces — `docs/`,
`--help`, real CLI invocations, real HTTP — and re-run the *original scenario*
from the run-2 report rather than reading the fix. Reported version is
`refdes 0.5.0`. The `refdes` on `PATH` in this worktree is a broken editable
install, so every command below went through a one-line wrapper in
`.scratch/refdes` (`PYTHONPATH=<this worktree>/src python -m refdes.cli …`); that
is a local-machine artefact, the same one run 2 recorded, and it is not counted
as a product finding.

**Nothing under `src/`, `tests/` or `docs/` was modified.** All synthetic
projects live under `.scratch/run3/`, which is gitignored. This report adds one
file.

Two areas are **deliberately not covered**, because other workers are on them:
concurrent editing against `serve`, and breaking/recovering item identity
(`keys restore` / `keys adopt` / `revise` / `former-ids` as recovery tools).

---

## 0. Headline summary

**Every run-2 finding is fixed except one, and the one that is not fixed is the
same class of bug run 2 filed.** BUG 1 (silent load-time writes) is fixed
everywhere, not just in the two commands it was filed against: all twelve
writable-load commands announce what they wrote, and `check --help` no longer
claims a single exception. BUG 3 (`init`'s machine-specific `.vscode` file) is
fixed at all three points — gitignored, announced, and a note when skipped. F1–F8
are all fixed, F8 (`--port` / `--token-file`) completely, including every
documented refusal. The five "lower severity" items are all fixed.

**BUG 2 is only partly fixed, and the residue is a raw traceback.** The fix
caught the two *load-time* write sites. `build`, `revision` and `release` write
two more places — the append-only seal file and `.refdes/baselines/` — and on a
read-only checkout all three still die with an unhandled `PermissionError`
traceback and no diagnostic. That is finding **N1** below, medium severity, and
it is the same failure a CI container with a frozen checkout would hit.

Nothing in this run rose above medium. One new low-severity finding is worth a
newcomer's attention: `getting-started.md`'s sample command output no longer
matches what the commands print, because of the very notice lines that fixed
BUG 1 (**N3**).

Incidental, and useful for run 4: **this sandbox does have network egress.**
Run 2 recorded "no network egress from the sandbox" and therefore could not
exercise a real remote `fetch`. `refdes fetch` here fetched
`https://www.ti.com/lit/ds/symlink/tps62913.pdf` and recorded
`sha256=6b27cbc00d3de5f5b838cbab15a37c5b136b835e43fdaf98bac290015b862bc5`
(`6003120` bytes) with no error, so run 2 §4 item 1 is now reachable.

---

## 1. Re-test table — every run-2 finding, re-run as a user

Each row is the scenario run 2 filed, reproduced against current `HEAD`
(`81c9a5e`), with the verdict.

| # | Run-2 finding | Verdict | What I ran, and what it printed |
|---|---|---|---|
| BUG 1 | `check` rewrites item files while its `--help` denies writing anything of the project's own | **fixed** | Fresh project, `items/` with `id:` and no `key:`, `check`/`ls`/`index`/`audit`/`build`/`release`/`revision`/`former-ids propose`/`history capture`/`id`/`stub-tests`/`fetch` each against a pristine copy. All twelve announce `(minted 5 key(s) and rewrote 5 reference(s) while loading)`; `index` puts it on **stderr** so stdout stays pure JSON. `check --help` now says loading writes keys, composites and `.refdes/schema.json`. |
| BUG 2 | read-only checkout → unhandled `PermissionError` traceback | **partly fixed** | Whole tree `chmod -R a-w`: `check`, `ls`, `audit`, `index`, `build` (items-only), `fetch`, `history`, `former-ids` all degrade to a warning naming the files it could not write, no traceback, exit code unchanged — in either of two shapes (**N2**). **`build`, `revision`, `release` still traceback** at `src/refdes/seal.py:206` / the baselines write → **N1**. |
| BUG 3 | `init` writes a machine-specific absolute path into a committed `.vscode/settings.json`; silent skip when one exists | **fixed** | `refdes init` now prints `wrote .vscode/settings.json (gitignored -- the yaml.schemas path in it names one checkout)`, writes a 5-line `.gitignore`, and `git check-ignore -v .vscode/settings.json` → `.gitignore:5:.vscode/settings.json`. With an existing settings file: `note: .vscode/settings.json already exists; left it alone. Add "yaml.schemas": {"…/.refdes/schema.json": ["items/**/*.yaml"]} yourself…`, and the file is untouched, comments and all. |
| F1 | `ls` has no `--workspace` | **fixed** | `refdes ls --workspace product-a` → `REQ-A-PWR-001  requirement  Product A shall run from 9 V to 36 V.`; `--workspace platform` → `IFC-CAN-001  bound  CAN bitrate`. Combines as AND with `--type`; unknown name → `no items match`, exit 0. Documented at `docs/cli-reference.md:246,254,267-271`. |
| F2 | citation severity table implies a `check --require-citations` flag | **fixed** | `docs/markdown.md:435-448` now names `refdes build --require-citations` in each soft row and says plainly "only `build` can escalate them, so the soft rows below stay warnings at `check` and never fail it". `refdes check --require-citations` still exits 2 with `unrecognized arguments`, which is now consistent with the page. |
| F3 | `release --help` never names the gate rules | **fixed** | `refdes release --help`: "The eight rules are draft_items, unpinned_citations, missing_kept_copies, uncovered_requirements, unverified_requirements, info_check_failures, unaccepted_board_moves, and unaccepted_workspace_moves." |
| F4 | imported lost-key error describes only the upstream cause | **fixed** | Two real projects (`up/` builds an artifact, `down/` imports it and links `constrained_by: [IFC-CAN-001]`). `down`'s bare link expanded to `IFC-CAN-001@y0k4sad04qr`; upstream then lost its key and minted `7hq21ktn8ft`; `down`'s check now ends `… If it is the same item, restore its original key upstream. This composite reference was written into your file by refdes on a load, not typed by hand — see docs/multi-board.md.` The **local** lost-key case was re-run too and keeps its `refdes keys restore BND-THM-001@nw8jpwr2fyr --dry-run` recipe with none of the new text. |
| F5 | `standard upgrade --help` implies all-or-nothing | **fixed** | Now: "Refuses the failing step, rolling it back cleanly rather than guessing at an ambiguous or ill-formed one; **earlier steps in the chain stay applied**." |
| F6 | inconsistent exit codes for "no such thing" | **fixed** (by documentation; no code changed) | `docs/cli-reference.md:16-31` adds a nine-row table. I ran all eighteen invocations it names and every code matched, including `ls --board nosuchboard` → `0` as the one documented exception. One trap for the reader: the row `build --reseal` means `refdes build --reseal nosuchboard` (exit 1), **not** `--board nosuchboard`, which `build` has no flag for and which exits 2. |
| F7 | VS Code README claims a surface with no test coverage, and nothing says so | **fixed** | `editors/vscode/README.md` "Developing" now names `tests/test_vscode_extension.py` and `tests/test_vscode_adapter_contract.py` (both exist), describes them as "automated coverage, but it is static rather than live", and says plainly "there is no `@vscode/test-electron` harness, so checking the features above still means exercising them in a real instance". The surface is still ungateable; the README no longer pretends otherwise. |
| F8 | `serve` needs two undocumented facts for scripted use (ephemeral port, token scraping) | **fixed** | Scripted end to end: `refdes serve --no-open --port 8731 --token-file …`, read the URL from the file, `curl` the API, stop. Busy port → `error: cannot listen on 127.0.0.1:58413: Address already in use -- … choose another --port` exit 2. `--port 99999` and `--port 0` → argparse error, exit 2. `--token=abc` → `unrecognized arguments` (abbreviation disabled). Symlink refused, foreign file refused byte-for-byte, a real stale launch file rewritten and tightened `644 → 600`, removed on SIGINT. And F8's actual trap, live: token `oHre90_Zok73eOWtYvUhsy7_Gd-UpTF9B-tSuYVg7QE`, naive `[0-9a-zA-Z-]+` scrape gives `oHre90` → **403**, real token → **200**. |
| L-a | `init` prints nothing about the `.vscode/settings.json` it wrote | **fixed** | Verbatim above, in BUG 3. |
| L-b | `init` skips an existing `.vscode/settings.json` silently | **fixed** | Verbatim above, in BUG 3. |
| L-c | board/workspace name collision is only discovered after you write both | **fixed** | `docs/workspaces.md` now carries "Workspace names share one namespace with board names" directly under "Declaring workspaces", quoting the error and exit 2, naming the five colliding report filenames. Reproduced: `configuration error: 'board-a' is declared as both a board and a workspace — boards and workspaces share one namespace for generated report names (e.g. coverage-board-a.html); rename one of them`, exit 2. |
| L-d | `release`'s log-entry nudge prints a plausible-looking `LOG-...` | **fixed** | `refdes release rel-a` on a passing project now suggests `- id: LOG-A-0NN  # placeholder: your log prefix, next free number` and `records: [DEC-A-0NN]  # the decision(s) this release turned on`. Pasting it verbatim fails immediately and legibly (`ERROR … records points at 'DEC-A-0NN', which does not exist`) rather than minting a plausible-looking id. |
| L-e | `audit` calls an unpinned citation `hash-only` | **fixed** | One project, four citations, one of each state: `unpinned  no pin`, `ok  hash-only`, `ok  kept`, and the `kept` copy really is at `.refdes/copies/4f5536cb…pdf`. |

### Still-open run-1 items run 2 §4 named

| Run-1 finding | Verdict | What I ran |
|---|---|---|
| F4 — the getting-started narrative never reaches a green build | **fixed, by documentation rather than by reaching green** | Followed `docs/getting-started.md` top to bottom, literally. §5's documented build output still reproduces exactly (`P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2`, `4 items, 1 errors, 1 warnings`), and the page still ends **red** — which is now what §7 says it does, in as many words: "**Nothing above turns the build green, and superseding the decision will not either.**" I confirmed the claim it makes: wrote `DEC-PWR-002` (passing, `supersedes: [DEC-PWR-001]`), set `DEC-PWR-001` to `superseded`, and the build still failed on `DEC-PWR-001`. Then followed the escape hatch the page now gives, verbatim — the `refdes-schema.yaml` `check_severity` overlay — and got `7 items, 0 errors, 1 warnings`, exit 0, with the demoted failure exactly where the page says it goes: `INFO items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates …` under `refdes check -v`. |
| BUG 3 — `--reseal` rewrites history and records nothing | **fixed** (not in my brief; checked because I hit the section) | Built, edited a sealed `LOG-001`, `check` refused (and now says `run with refdes build --reseal`, which fixes run-1 F7's "flag the printing command doesn't have"), then `build --reseal`. The seal file grew a `reseals:` record (`old_hash: 78cdac99272edc9c`, `new_hash: 02e3cd37767cc05e`, `occurred_at`, `key`), and `refdes audit` prints a new section **"Accepted append-only reseals (durable history)"** naming the entry, the action, the timestamps and both hashes. |
| BUG 1 — editor create ignores `defaults.prefix`; BUG 2 — lost-key recovery via `keys adopt` | **not re-tested** | Out of scope for this run (identity recovery is another worker's; the editor create path was not in the brief). Neither is claimed as regressed. |

---

## 2. What this run covered

- **BUG 1 follow-through**, all twelve writable-load commands, each against a
  byte-hashed pristine copy, plus `--no-write` and steady-state runs.
- **BUG 2 follow-through**, both run-2 variants (whole tree read-only, `items/`
  read-only with a writable root), extended to nine commands and to the
  realistic CI shape (inputs read-only, `site.out` pointing at a writable
  directory elsewhere).
- **BUG 3**, three cases: fresh `init`, `init` with an existing settings file,
  `init` with an existing `.gitignore`.
- **`getting-started.md` followed literally**, top to bottom, in a fresh git
  repo, including the documented escape hatch.
- **F1–F8** and the five lower-severity items, each re-run as the original
  scenario.
- **The new surfaces as a user meets them**: `ls --workspace`;
  `serve --port` / `--token-file` driven from a script (start, read credential,
  `curl` the API, stop) plus every refusal path I could think of; the new exit-code
  table, row by row; `release`'s log nudge; `audit`'s citation pin column;
  `init`'s new output lines.
- **Bonus re-tests** that fell out of the above: run-1's `--reseal` auditability,
  run-1's `ls <ID>` free-text search (`$RD ls REQ-A-PWR-001` now returns the
  item — run-1 L5 is fixed), and the board/workspace namespace guard.

Not covered, and why:

- **Concurrent editing against `serve`** and **identity breakage/recovery** —
  other workers, by instruction.
- **Anything requiring a real VS Code** — no `code` CLI, no display.
- **Windows and macOS** paths, line endings, case-insensitive filesystems.
- **A real PDF through the source picker** — no PDF was available to hand. The
  `section:` path was exercised against a plain-text local file and failed in
  exactly the shape `docs/markdown.md` documents for "pypdf can't parse the
  file", which is correct but is not the same as exercising PDF resolution.
- **`--require-citations` against a real gate** — exercised only far enough to
  confirm the documented flag scoping (§1, F2).
- **Performance at scale** — a separate in-prog log covers it
  (`in-prog-logs/scale-test-large-project.txt`).

---

## 3. New findings

### N1 — `build`, `revision` and `release` still die with a traceback on a read-only checkout

**Severity: medium.** This is run-2 BUG 2's residue. The fix caught the two
*load-time* write sites; these commands write two more, further down.

Whole tree read-only, on a project that is otherwise green:

```
$ refdes build
Traceback (most recent call last):
  ...
  File ".../src/refdes/cli.py", line 314, in cmd_build
    build_mod.build(
  File ".../src/refdes/build.py", line 2930, in build
    seal.verify(project, write=seal_write, reseal=reseal)
  File ".../src/refdes/seal.py", line 467, in verify
    save_seals(project, base, board="", events=base_events)
  File ".../src/refdes/seal.py", line 206, in save_seals
    os.makedirs(os.path.dirname(path), exist_ok=True)
PermissionError: [Errno 13] Permission denied: '…/.refdes'
exit 1
```

`refdes revision r1` and `refdes release rel-a` fail the same way on the
`.refdes/baselines/` write.

Three things make this worse than the load-time case it was modelled on:

1. **`build` cannot degrade, because it has no honest degraded mode here** — it
   is the command that seals. But it *can* say so. Run 2's own suggested fix
   shape ("catch `OSError` around both write sites and emit a `WARNING …`
   then continue") applies verbatim to `save_seals`. The condition it would be
   reporting is one the tool already documents — `check --help` says outright
   that "a seal exists only once `build` has run over the entry, so an entry
   that has never been built has no append-only protection at all" — so a
   `WARNING <project> — could not record append-only seals (read-only tree?);
   run with --no-write to silence this` plus a non-zero exit is honest and
   useful: the entries really are unsealed, and saying so is the whole point.
   For `revision`/`release` the honest answer is a refusal naming the file, not
   a traceback.
2. **The traceback comes before any output.** `seal.verify` runs at
   `src/refdes/build.py:2930`, ahead of `render_pages`, so the site is not
   written, no summary line prints, and nothing in the output distinguishes
   "your filesystem is read-only" from "your project is broken". Exit is 1,
   which is the "errors found" code.
3. **It survives the obvious workaround.** I tried the shape a CI job actually
   has — a read-only source tree with the site written elsewhere:

   ```
   site:
     out: /tmp/…/refdes-site-readonly-demo     # writable
   $ chmod -R a-w <project>
   $ refdes build
   PermissionError: [Errno 13] Permission denied: '…/.refdes'
   ```

   Still a traceback. `.refdes/` has to be writable no matter where the site
   goes, and nothing tells the user that.

Fix shape: catch `OSError` at `seal.save_seals` and at the baseline-stamping
write; for `build`, warn and continue to the render with a non-zero exit; for
`revision`/`release`, refuse with the file named and exit 2 (they are stamping
commands, and a stamp that did not happen should not read as one that did).
`tests/test_load_time_writes.py` already pins the load-time half, including
`test_check_survives_a_read_only_tree`,
`test_check_survives_a_read_only_items_dir` and
`test_an_explicit_write_still_raises_on_a_read_only_tree`; the seal and baseline
halves want the same three shapes, and `build` is the gap none of them covers.

### N2 — the same read-only condition is announced in two different sentences

**Severity: low.** Now that the condition is reported rather than crashed on, it
is reported two ways, and a user grepping for one will miss the other:

```
# commands that print diagnostics of their own, per file
WARNING items/bounds/thermal.yaml:1 — could not write this file (read-only tree?); run with --no-write to silence this

# commands with no diagnostics of their own, in a summary line
(load could not write .refdes/schema.json, items/bounds/thermal.yaml, items/decisions/dec.md, items/log.yaml (+2 more) -- read-only tree? run with --no-write to silence this)
```

Two prefixes (`WARNING` vs a parenthesised aside), two separators (em dash vs
`--`), one with a trailing full stop and one without, one with the hint in
parentheses and one without. The split is deliberate — "commands that print no
diagnostics of their own name the refused files in their own summary line" — and
reasonable. But the *sentence* could be one string with the file list elided or
not. This is exactly the kind of thing a CI log filter is written against.

### N3 — `getting-started.md`'s sample output no longer matches the commands, because of the BUG 1 fix

**Severity: low.** The page's whole value for a newcomer is that its sample
blocks are what their terminal shows. Two of them no longer are, and both are
off by exactly the line the BUG 1 fix added.

§2 shows:

```
allocated REQ-PWR-001  (items/requirements/power.yaml:9) The unit shall operate from an input supply of 9 V to 36 V.
allocated REQ-PWR-002  (items/requirements/power.yaml:13) The 3V3 rail shall supply 1.2 A continuous.
allocated 2 id(s)
```

and prints:

```
(minted 2 key(s) while loading)
allocated REQ-PWR-001  (items/requirements/power.yaml:9) The unit shall operate from an input supply of 9 V to 36 V.
allocated REQ-PWR-002  (items/requirements/power.yaml:13) The 3V3 rail shall supply 1.2 A continuous.
allocated 2 id(s)
```

§5's build block likewise gains `(minted 2 key(s) and rewrote 3 reference(s)
while loading)`. Every other line in both blocks still matches character for
character, which is the property run 1 singled out as worth protecting — so this
is a two-line docs edit, not a rewrite. Worth doing while the delta is fresh:
the moment a newcomer's first `refdes id` prints a line the tutorial did not
promise, the tutorial stops being the thing they can check their terminal
against.

### N4 — `--token-file` survives a `SIGTERM`, which is how a script stops `serve`

**Severity: low.** The flag's whole purpose is scripted use, and the ordinary
scripted stop is `kill $pid`, i.e. SIGTERM. The help says the file is "removed
when `serve` stops cleanly" and the stdout line says "removed on Ctrl+C"; only
SIGINT removes it.

```
# SIGINT
after SIGINT: token file exists? False
# SIGTERM
after SIGTERM: token file exists? True
```

Nothing is lost — the file left behind *is* a valid launch file, so the next
`--token-file` at that path rewrites it (verified: a stale file was rewritten
and its mode tightened from `644` to `600`), and its token authenticates nothing
once the launch is gone. So this is a hygiene issue, not a security one: a
credential-shaped file with a dead token stays on disk after every scripted
run, and a script that reads it after the server exited gets a connection error
rather than a clean "no such file". Catching SIGTERM alongside SIGINT in the
same handler would close it.

### N5 — `ls` still has no workspace column, so `--workspace` is the only way to see one

**Severity: low.** The flag answers "what's in product-a?", which was run-2 F1's
complaint, and it answers it correctly. What it cannot do is show you *where* an
item's workspace came from: plain `ls` output is id / type / board / title, so
in a three-workspace project the unfiltered listing gives no hint that the
project has three of them.

```
$ refdes ls
IFC-CAN-001    bound        CAN bitrate
REQ-A-PWR-001  requirement  Product A shall run from 9 V to 36 V.
REQ-B-PWR-001  requirement  Product B shall run from 12 V to 24 V.
```

`--board` has exactly the same gap and is older, so this is consistency with
the existing listing rather than a new inconsistency — but `ls` is the discovery
command, and `index --compact` has been exporting a `workspace` per item all
along. A `--workspace` column when (and only when) the project declares
`workspaces:` would make the flag's existence discoverable from the listing it
filters.

### N6 — two cosmetic leaks in `audit`'s new reseal section

**Severity: trivial.** In a project with no boards:

```
Accepted append-only reseals (durable history):
  LOG-001 [unboarded] 2026-10-01T06:31:53.622647+00:00 edit
    key 5770ky4fphv
    was 78cdac99272edc9c, now 02e3cd37767cc05e
```

`[unboarded]` is an internal placeholder leaking into prose — everywhere else
an absent board is shown by omission rather than by naming the absence — and
the bare surrogate `key` is the same class of implementation detail run-1 L6
flagged leaking into user-facing messages. Both are one-line changes and neither costs
a reader anything they cannot already infer.

### Noted once, not per message

Several diagnostics still point at **repo-relative docs paths** rather than
URLs — `see docs/multi-board.md` in the new lost-key message
(`src/refdes/build.py:527`), `docs/multi-board.md` / `docs/workspaces.md` in the
config validator (`src/refdes/configcheck.py:102-103`), plus a handful in
`serve/upload.py` and `lifecycle.py`. A separate PR is switching these to full
documentation URLs, and `init`'s candidate-parts pointer has already moved
(`candidate parts live in items/<board>/candidates.yaml --
https://squishiba.github.io/refdes/parts.html#candidate-parts-the-recommended-layout`,
which also stops run-1 L1's dangling repo-relative pointer (I did not fetch the
URL, so I am not claiming it resolves)). Recording once, as
asked; not re-counted anywhere above.

---

## 4. What worked cleanly

- **The load-write notice is genuinely uniform.** Twelve commands, twelve
  notices, including the two that already announced it in run 2 (`id` and
  `stub-tests`), which still do. `index` gets it right by
  putting the notice on **stderr**, so `refdes index | jq` still works — that is
  the kind of detail that is easy to get wrong and worth naming. And the
  steady state is quiet: a second `refdes check` on a fully-keyed project
  printed exactly `5 items, 0 errors, 0 warnings`, and `--no-write check`
  printed the same. A notice that fires on every run would have been worse than
  the bug.
- **`serve --port` / `--token-file` are exactly as careful as they claim.**
  Every refusal I could think of holds: a busy port is exit 2 with a sentence
  that names both causes and the way out (never a silent fallback to a
  neighbouring port, which would be the quiet failure); `--port 0` and
  `--port 99999` are argparse errors rather than `OverflowError`;
  `--token=abc` is refused because argparse abbreviation is off, which is what
  stops the new flag from quietly undoing the "no flag carries a token"
  property; a symlink at the path is refused and the target is byte-identical
  afterwards; a project file at the path is refused and left alone; a real stale
  launch file is rewritten and tightened `644 → 600`; and the write is atomic,
  so a polling script never sees an empty credential. F8's original trap — the
  `oHre90` → 403 that reads like an auth bug — is now avoidable by construction
  rather than by care.
- **The exit-code table is true.** All eighteen invocations it names return the
  code it claims, and the one asymmetry it flags (`ls --board nosuchboard` →
  `no items match`, exit 0) is real and is called out in the table rather than
  left to be discovered. Pinning each code in `tests/test_exit_codes.py` is the
  right way to keep a table like this from rotting.
- **`audit`'s citation line is no longer self-contradictory.** Four citations,
  four states, four legible lines: `unpinned  no pin`, `ok  hash-only`,
  `ok  kept`, and `kept` really does mean a file at `.refdes/copies/<sha256>.pdf`.
- **The board/workspace namespace guard is airtight where it can fire.** I went
  looking for a hole: a *derived* board key equal to a workspace key is not
  refused at load (`src/refdes/schema.py:744` compares declared boards only) —
  but it also cannot collide, because per-board report files are only generated
  for boards in a `boards:` block. Verified both halves: with a declared block,
  `coverage-one.html` / `coverage-two.html` appear; with derived folder names
  only, `coverage.html` alone appears. So the check covers every case that can
  actually lose a file, which is the right invariant.
- **`getting-started.md`'s honesty is a real improvement.** The page now tells
  you the walkthrough ends red, tells you superseding will not fix it, and hands
  you the overlay — and every one of those three claims is true when run. That
  is a better outcome than a walkthrough contorted to end green, and the
  demoted failure landing in `check -v` rather than vanishing is the right
  shape for it.
- **`--reseal` is now auditable.** An accepted reseal leaves a durable record in
  `.refdes/log-seal.yaml` and shows up in `refdes audit` under a section that
  says what it is. Run-1 BUG 3 was the strongest claim in either prior report —
  "the audit trail lies" — and it is closed.
- **`init`'s two writes are both visible, and the skip is explained.** Three
  files now where there was one, each named at the moment it is written, and the
  machine-specific one carries the reason it is not worth committing. The
  `.gitignore` it writes explains itself in four comment lines rather than
  dropping a bare pattern, and it appends without disturbing an existing file.
- **Run 1's and run 2's baselines held under everything above.** Idempotent
  rebuilds, `--no-write` honesty, diagnostic quality, `serve`'s side-effect
  freedom (re-verified: `serve` loaded and served `/api/revision`, `/api/items`
  and `/api/item/<ref>` and wrote nothing), the token/Origin/Host posture (403
  without a token, 403 on a wrong `Host`), and the headline promise (tightening
  `BND-THM-001` still fails `DEC-PWR-001` with both numbers shown) all still
  work. Run-1 L5 is fixed as a bonus: `refdes ls REQ-A-PWR-001` returns the
  item.

---

## 5. Suggested shape for run 4

Lead with **N1**, because it is the only remaining place where a *green-looking*
workflow produces a raw traceback, and because it is a small, well-understood fix
in the same shape as a fix that already landed:

- re-run the read-only matrix — whole tree, `items/` only, `site.out` elsewhere —
  across every command that writes (`build`, `revision`, `release`, and whatever
  else a fresh eye finds), and confirm each one either degrades to a warning or
  refuses with the file named
- confirm the two phrasings of the read-only warning (N2) have become one string
- confirm `getting-started.md` §2 and §5 sample blocks match again (N3);
  §1 has no `init` output block to fix, but it is the one page that shows the
  generated `refdes-project.yaml` verbatim, so re-read it against a fresh `init`
  while the delta is open

Then the areas three runs have now deliberately left, in rough order of value:

1. **A real remote `fetch`.** Egress appears to be available in this sandbox
   (see §0), so run 2's blocker is gone. Worth covering: HTTP status handling
   and redirects, `rev:` inferred from `Last-Modified`/`ETag`, a 404 on a
   previously-pinned citation (I hit two real 404s from `ti.com` symlinks while
   testing, which is a free sample), and `missing_kept_copies` when a keep-copy
   download fails halfway.
2. **A real PDF through the source picker.** Text-layer extraction, page
   resolution, the `pypdf`-missing fallback, and `--require-citations`
   interacting with a citation that has a page but no rev. A synthetic PDF with
   a real outline would cover most of this without a vendor datasheet.
3. **The VS Code adapter under a real VS Code**, or a headless
   `.vscode-test` harness. The README now says plainly that this gap exists; the
   gate still cannot say more than "reading found no defects".
4. **Windows.** `docs/` mentions Windows-specific schema-path behaviour
   (finding 9) that no run has tested, and the new `--token-file` code has a
   Windows-specific carve-out (`os.fchmod` does not exist before 3.13) that only
   a Windows run would exercise.
5. **Multi-root VS Code.** The absolute `yaml.schemas` path in
   `.vscode/settings.json` exists *for* multi-root workspaces; no run has opened
   two refdes projects in one VS Code session and confirmed one does not validate
   against the other's schema.

And one thing to carry forward as a process note: this run's own first sweep was
run from the wrong directory and wrote into the refdes checkout itself (a
`refdes fetch` created `.refdes/citations.yaml`, which is a committed file here,
and a stray `git add -- .` committed it). It was undone with `git reset` and
`rm`, and the tree is clean — but the safe pattern is the one run 2 used: a
`cp -r` of a pristine project per command and a `find | xargs sha256sum` before
and after, with no `git` involved at all. A gate that can dirty the product it
is gating is a gate that can report on the wrong tree.

---

## Appendix — how to reproduce this run

All commands below ran from `.scratch/` in this worktree; nothing outside it was
written.

```bash
# the wrapper (the refdes on PATH is a broken editable install)
cat > .scratch/refdes <<'EOF'
#!/bin/bash
exec env PYTHONPATH="$PWD/src" python -m refdes.cli "$@"
EOF
chmod +x .scratch/refdes

# one command against a byte-hashed pristine copy
#   .scratch/mkpristine.sh <dest>      -- cp -r of .scratch/run3/pristine
#   .scratch/sweep.sh <refdes args...> -- reset, run, diff items/ hashes

# scripted serve: .scratch/serve_drive.py starts on a free port with a
# --token-file, reads the credential from the file, calls /api/revision,
# /api/items and /api/item/<ref>, then stops with SIGTERM
```

Project inventory, all under `.scratch/run3/`: `pristine` (5 items, one bound,
one decision with real arithmetic, one test, one log entry — the template for the
write sweeps), `pg` (the same, green: bound loosened to `<= 0.95 W/in^2`),
`my-board` (the literal `getting-started.md` walkthrough), `ws`/`ws2`/`ws3`/
`ws4`/`ws5`/`ws6` (workspaces), `up`/`down` (a real import), `cit` (four
citations, one per pin state), `localkey` (a local lost key), `reseal` (the
append-only reseal), `init-fresh`/`init-existing` (`init` cases), `ro*` (the
read-only variants).
