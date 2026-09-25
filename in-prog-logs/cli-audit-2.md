# CLI reference accuracy audit — chunk 2

Scope: `docs/cli-reference.md` only. Commands audited in this chunk, one at a
time: `audit`, `init`, `new`, `schema`, `standard` (`add-preset`,
`remove-preset`, `upgrade`). Chunk 1 (merged as `docs: correct CLI reference
for serve/build/check/ls/id`, #36) already covered `serve`, `build`, `check`,
`revision`, `release`, `index`, `ls`, `id`, `fetch` — not redone here.

No source or test file is edited. Probes run from
`.scratch/cli-audit-2/<project>/` against this worktree's `src/` on
`PYTHONPATH`, using the repo virtual environment:

```powershell
$env:PYTHONPATH="<worktree>\src"
& "C:\Users\Jared\Refdes\.venv\Scripts\python.exe" -c "import sys;from refdes.cli import main;sys.exit(main(sys.argv[1:]))" <args>
```

Scratch projects: `base/` (flat, `hardware@3`, seeded with requirement /
bound / decision / component / test / log), `reseal/` (sealed log then edited),
`boards/` (boards + workspaces registry, a board/workspace move, and an
`imports:` entry).

---

## `refdes audit`

Generated help (`audit --help`) exposes only `-h` beyond the global set, and
its description enumerates: schema fields excluded from invalidation,
item-level history overrides, append-only log entries edited after sealing
(`--reseal`), accepted and outstanding board and workspace moves
(`--accept-board-move`), what's changed since the last revision and release,
and imported projects. No undocumented flags; the reference has no option
table for this command and needs none.

Confirmed as documented (no change needed):

- The example's section headings and line shapes all reproduce: `Item-level
  overrides:` printing `REQ-PWR-004    owner -> ignore  — <reason>` (verified
  with a real `history: {fields: {owner: ignore}, reason: ...}` front matter);
  `Append-only entries edited after sealing:` listing a `LOG-PWR-001` id after a
  `build` sealed the log and the body was then edited; `Ledger entries with no
  live item and no former_ids: explaining them:` listing a deleted item's
  ledger id plus its four-line explanatory note; `Blocked chains:` printing
  `DEC-PWR-002 <- DEC-PWR-001 (on_hold, root)`; `Citations:` printing
  `<path>` then `unpinned       hash-only  cited by CMP-PWR-001`; `Parts:`
  printing `TPS62913       used by CMP-PWR-001 (component)`; `Former IDs:`
  printing `REQ-PWR-099    -> REQ-PWR-001`; and the closing
  `N items audited (N local)`.
- `relabelled` behaves exactly as documented: changing an item's `id:` after a
  baseline produced `relabelled 1` with `DEC-PWR-001 -> DEC-PWR-010   (3chzg81n10r)`
  on its own line with the surrogate key in parentheses, and `(5 unchanged)`.
- `uncomparable` behaves exactly as documented: a baseline entry whose stored
  hash does not check out under its own recorded `hash_format` produced
  `uncomparable 1   REQ-PWR-001` on its own line with a two-line explanation,
  was absent from `changed`, and was excluded from the unchanged count
  (`(4 unchanged)`). The line is absent when the count is zero, as documented.
- "Board moves" and "Workspace moves" print only when `boards:` /
  `workspaces:` are declared, and `Board moves ...`/`Workspace moves ...`
  correctly reported `REQ-PWR-001    power -> signal` and
  `REQ-PWR-001    alpha -> beta` after the registry was written by a `build`.
- The draft wording is correct: a never-stamped project prints
  `Baselines:` / `(none stamped yet -- project is in draft)` and
  `Since last revision: (no revision stamped yet)`.
- A file that fails to parse is reported on stderr, the report for everything
  that did load is still printed, and the exit code is 1.

**Proven discrepancy 1 — an always-printed section is missing from the
reference.** After the "Since last release" block, `audit` *unconditionally*
prints

```
Older baseline keys no current item declares:
  (none)
```

It appeared in every run, including on a project with no baselines at all, and
`cli.py:676` prints it with no `if` guard. The reference's sample output
(`docs/cli-reference.md:381-440`) omits the section entirely, and the opening
summary list (`docs/cli-reference.md:364-371`) does not mention it either. Fix:
add the section to the sample output and to the summary list, with its `(none)`
empty form.

**Proven discrepancy 2 — the "Baselines" prose covers only the fully-unstamped
case.** With a `revision` stamped but no `release`, the section prints two
lines:

```
Baselines:
  most recent stamp:   rev-a (revision, 2026-09-25T20:27:33Z)
  most recent release: (none stamped yet)
```

`docs/cli-reference.md:444-447` documents only the `(none stamped yet -- project
is in draft)` replacement, so the `most recent release: (none stamped yet)`
line is undocumented. Fix: state it.

**Proven discrepancy 3 — the "Imported projects" line has an undocumented
variant.** The sample shows only `pinned to 2026.3`. An import declared without
a `version:` prints `platform       1 items unpinned  <- ../reseal/_site/items.json`
(`cli.py:715`), and the item count then folds into the trailer, which printed
`2 items audited (1 local)`. Fix: note the `unpinned` form.

Not changed: the "Citations" gating sentence. It is accurate as written — a
citation only reaches `Citations:` once the mapping form
(`citations: [{path: ...}]`) is used; a bare string citation is a
`each citation needs a 'path'` error, which is a `check`/schema matter, not an
`audit` one.

---

## `refdes init`

Generated help exposes exactly the two documented options, with the same
descriptions, and adds that `<latest>` is resolved to a concrete pinned
integer rather than written literally. No discrepancy; nothing changed except
the exit-code and `-c` sentence noted below.

Verified in fresh directories:

- A bare `init` wrote `refdes-project.yaml` (`site:`/`standard:`/`id:` only —
  no `types:`/`link_types:`/`sets:`, as the help says) plus
  `.vscode/settings.json` pointing at `.refdes/schema.json` for
  `items/**/*.yaml`, and exited 0.
- `init --standard none` wrote `standard: none` and printed
  `standard: none -- types:/link_types: are yours to declare`, exit 0.
- `init --preset design-debate` wrote `presets: [design-debate]` under
  `standard: {base: hardware, version: 3}` and printed
  `standard: hardware@3, presets: ['design-debate']`, exit 0.
- `init --standard none --preset design-debate` is the documented load-time
  error: `presets require a base standard; ...`, exit 2, nothing written.
- A second `init` in a directory that already has `refdes-project.yaml` is the
  documented refusal: exit 2, nothing written.
- `--no-write init` refuses and exits 2, matching the global-option table.
- `-c <elsewhere> init` still wrote to the *current* directory, so `-c` has no
  effect on `init`.

Applied: the section said only that it "refuses to run" on an existing
config; it now also says the name checks and that refusal are exit-2
configuration errors with nothing written, and that `init` ignores `-c`.

## `refdes new <type>`

Generated help: `new [-h] [--list] type`.

- The documented `new decision > items/power/dec-005.md` form works and exits 0.
- An unknown type exits 1 with a did-you-mean suggestion
  (`unknown type 'requirment'. Did you mean 'requirement'?`, and `bnd` →
  `bound`). With no near match it is just `unknown type 'nope'.`, still exit 1
  — the "did-you-mean" half is conditional, which the reference implies but
  does not overclaim.
- It works on a project-defined type from a `refdes-schema.yaml` overlay
  (`standard: none` plus a `waiver` type), for both the plain and `--list`
  forms.
- It works in a directory with no project at all, falling back to the bundled
  standard, exit 0.
- It writes nothing: no `.refdes/` directory was created by any `new` run.
- No `type` argument is an argparse error, exit 2.

**Proven discrepancy 4 — an entire flag is undocumented.** `new` has a
`--list` flag with no option table anywhere in the reference. It prints a
list-file skeleton instead of a single item:

```
---
defaults:
  type: component
  status: candidate

items:
  - id:
    ...
```

The generated help's own example is
`refdes new component --list > items/power/candidates.yaml`. Fix: added the
option table and that second example line.

**Proven discrepancy 5 — "front matter" is incomplete.** The single-item form
emits front matter *and* a body stub after it (`---`, a blank line, and
`<!-- required: the content itself goes here. -->`, or
`<!-- optional body. -->`). Saying it "prints a starter item's front matter"
understates what lands in the redirected file. Fix: one clause.

## `refdes schema --json`

Generated help: `schema [-h] [--json] [--graph] [type]`, and it states
`--json` "the default".

- `refdes schema --json` and a bare `refdes schema` produce the same document.
- That document is byte-for-byte identical to `.refdes/schema.json` written by
  another command (checked with `check`), so "the same document" is accurate.
- The `jq` example's path is real: the emitted schema has a `$defs` with
  `decision__bare` and `decision__entry` keys.

**Proven discrepancy 6 — `schema` does not write `.refdes/schema.json`.** The
section says the document is written by "every command that loads the project
(`build`, `check`, `index`, `id`, `fetch`, `audit`, **and this command
itself**)". Running `schema`, `schema --json`, and `schema --graph` in a
project with no `.refdes/` directory exited 0 and created nothing. Fix: the
"and this command itself" clause is removed and the read-only behaviour
stated.

**Proven discrepancy 7 — the list of writers is both wrong and incomplete.**
Measured one command at a time in a project with no `.refdes/`:

| command | writes `.refdes/schema.json` |
|---|---|
| `build` | yes |
| `check` | yes |
| `index` | yes |
| `ls` | yes |
| `id` | yes |
| `fetch` | yes |
| `audit` | yes |
| `revision` / `release` | yes |
| `stub-tests` | yes |
| `former-ids propose` | yes |
| `new` | no |
| `schema` (any form) | no |

`ls`, `revision`, `release`, `stub-tests`, and `former-ids` were missing from
the reference's list; `new` and `schema` are the two project-aware commands
that stay out of it. Fix: the list is corrected.

**Proven discrepancy 8 — `schema --graph` is not one SVG document.** See below.

## `refdes schema --graph`

**Proven discrepancy 8 — the bare form emits many documents, and the `>
graph.svg` example is wrong.** The section says `--graph` prints "the
project's actual type/link graph as an SVG document" and shows
`refdes schema --graph > graph.svg`. In a `hardware@3` project the bare form
printed **eight** `<svg>...</svg>` documents concatenated to stdout: the
coverage spine first, then one per type (`bound`, `component`, `decision`,
`group`, `log`, `requirement`, `test`). Redirecting that to one file does not
produce a valid SVG.

**Proven discrepancy 9 — the positional `TYPE` is undocumented.** `schema`
takes an optional `type` argument that, with `--graph`, draws only that type's
diagram: `schema --graph decision` printed exactly one SVG (title
`decision connections`) and exited 0. An unknown type exits 1 with
`unknown type 'zzz'; this project's types are: bound, component, decision,
group, log, requirement, test`. Without `--graph` the positional is accepted
and ignored (JSON is still printed).

The old byte-for-byte claim was checked rather than assumed, and holds per
drawing: the SVG from `schema --graph decision` is character-for-character
identical to the one embedded in the built `_site/vocabulary.html`
(`vocab-term-diagram` for `term-decision`), and the first document of the bare
form is identical to that page's `vocab-spine`. The fix narrows the claim from
"the drawing every built site puts at the top of its vocabulary page" to "the
drawing the built site puts on the matching vocabulary page", which is what is
actually true of all eight documents.

---

## `refdes standard add-preset` / `remove-preset`

Generated help for `standard` lists exactly the three subcommands and adds
that hand-editing `standard.presets:` and re-running `build` "does exactly
the same thing -- these commands exist for the validation and reporting step".
Neither subcommand's own help carries a description (empty `--help` text and
an unnamed positional), so the reference is the only place they are explained —
worth keeping accurate, not worth reporting as a discrepancy.

Verified in a `hardware@2` project:

- `standard add-preset design-debate` printed
  `added preset 'design-debate' to standard.presets:` and exited 0, having
  validated the name *at the pinned version* — the failure message for a bad
  name names the version: `preset 'bogus' does not exist for hardware@2
  (available: ['design-debate'])`, exit 2.
- `--no-write` refuses and exits 2 for both subcommands, matching the global
  table.
- `standard remove-preset design-debate` on a project that *did* use the
  preset printed the `check`-style diagnostics first, then
  `removed preset 'design-debate' from standard.presets:`, wrote
  `presets: []` anyway, printed
  `1 error(s) above -- fix these, or add the preset back with 'refdes standard
  add-preset'`, and exited 1. The reference's "reports ... **before** writing
  the config change, then writes it regardless" and "Exits 1 if the report
  contains any error ... either way, the removal is applied" are both exactly
  right.
- With nothing breaking, the same command exited 0 with only a project-level
  warning.

No flag is undocumented (each takes one positional `name` and nothing else).
The two gaps fixed here are the exit-2 cases — re-adding a preset that is
already selected, removing one that isn't — and the `N error(s) above` way
back, neither of which the reference mentioned.

## `refdes standard upgrade --to N`

Generated help: `standard upgrade [-h] --to N` — `--to` is required.

Verified:

- A single step, `hardware@2 → 3`, printed `v2 -> v3:`, then
  `changed 1 file(s):` with the file list, then
  `baselines carried forward: rev-a`, then `upgraded to v3.`, exit 0. It
  rewrote `requirement.text` to `body:` in the item file and bumped
  `standard.version:` to 3, and carried the baseline's stored hash forward
  (`099dbd3600d0c378` → `2d2c11f07ff637fd`) along with the baseline's own
  recorded `standard.version:`. Every claim in the section is accurate.
- The chain is never merged: a `hardware@1` project upgraded to 3 printed
  `v1 -> v2:` (`no item file needed rewriting -- standard.version: bumped and
  the project re-validated against it`) and then `v2 -> v3:` as separate
  steps, exit 0.
- "Stops at the first version step that fails ... never partway through a
  single step's own rewrite": an item whose body content conflicted with the
  `text → body` rename gave `v2 -> v3:` / `refused:` / `can't rename
  requirement.text to body: this item already has its own body content ...`,
  exit 1, with the config still at `version: 2` and the item file untouched.
- "A baseline stamped before it recorded which standard version it started at
  ... is left alone during a chained upgrade, reported rather than guessed at":
  stripping the `standard:` block out of a stamped baseline and upgrading
  printed `baselines skipped (no recorded standard to migrate from): rev-a`
  and left the baseline byte-for-byte unchanged, exit 0.
- "The project must validate first": a project with a missing required field
  refused with `project has existing build errors -- fix those first, so a hash
  change caused by this rename can't hide behind one already-broken build`,
  exit 1, nothing written.
- Forward-only: `--to 2` on a project already at 2, and `--to 1`, both exit 2
  with `project is already at hardware@2, not below the requested --to N` and
  write nothing. `--to 0` behaves the same. `--to abc` is an argparse error,
  exit 2.
- A target past the newest bundled version is caught only by the post-rewrite
  validation, not up front: `--to 4` printed `v3 -> v4:` / `refused:` /
  `rewritten project no longer loads: standard.version 4 does not exist for
  base 'hardware' (available: ['v1', 'v2', 'v3'])`, exit 1, config left at
  `version: 3`. Safe, but worth stating because the up-front behaviour is
  different.
- `--no-write standard upgrade` refuses and exits 2, its message adding "and
  it has no dry-run" — matching the global table.

**Verified by reading, not by a run:** the claim that a *failing* `checks:`
result is not a blocker. `src/refdes/revise.py`'s `_blocking_errors` returns
`[d for d in project.errors if d.code != CHECK_VIOLATION]`, with a docstring
giving exactly the rationale the reference paraphrases, and the runtime refusal
message quoted above is about build errors. I did not manage a runtime probe
with an actually-failing check (building one at `hardware@2` ran into
`citations` not being a v2 `decision` field, and I stopped rather than sink
more time), so this one rests on the source plus the refusal message, not on a
green run. It should be left as it stands.

Applied: the exit-2 up-front cases and the `--to`-past-the-end behaviour.

---

## Wrap-up

Commands fully audited in this chunk: `audit`, `init`, `new`, `schema`
(`--json` and `--graph`, including the `TYPE` positional), `standard`
(`add-preset`, `remove-preset`, `upgrade`). All five done.

Changed: `docs/cli-reference.md` only, plus this log and a `changelog.d`
fragment. No source or test file was modified.

