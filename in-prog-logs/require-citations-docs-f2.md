# F2 — the citation severity table implies `check --require-citations`, which doesn't exist

Source: `in-prog-logs/user-sim-release-gate-run2.md` §F2 (line 301). Docs-only fix.
Adding `--require-citations` to `check` is explicitly out of scope (new CLI surface).

## Read first

- `docs/markdown.md:434-443` — the "**Verification**" intro and the six-row severity table.
- `docs/markdown.md:445-450` — the hash-mismatch paragraph immediately after the table.

The table is at line 434, not 435 as the gate report guessed (435 is blank, 436 the
header). Four of the six rows end with a bare `(error with `--require-citations`)`.

## Verification (scratch project, `.scratch/f2`)

Scratch project: `refdes init` in `.scratch/f2` (resolves `standard: hardware@3`),
one item `CMP-001` citing the repo-local path `docs/spec.txt`, pinned with
`refdes fetch` (hash-only), then `docs/spec.txt` edited so its sha256 no longer
matches the lockfile. Run with `PYTHONPATH=<repo>/src`.

### The four required commands

```
$ refdes check
WARNING <project> — local citation 'docs/spec.txt' has changed since it was pinned -- review the change, then run 'refdes fetch --update --path docs/spec.txt' (cited by CMP-001)
1 items, 0 errors, 1 warnings
EXIT=0

$ refdes build --dry-run
WARNING <project> — local citation 'docs/spec.txt' has changed since it was pinned -- review the change, then run 'refdes fetch --update --path docs/spec.txt' (cited by CMP-001)
1 items, 0 errors, 1 warnings
site written to .../.scratch/f2/_site (dry run, not sealed)
EXIT=0

$ refdes build --dry-run --require-citations
ERROR   <project> — local citation 'docs/spec.txt' has changed since it was pinned -- review the change, then run 'refdes fetch --update --path docs/spec.txt' (cited by CMP-001)
build completed with errors (use --keep-going to exit 0)
1 items, 1 errors, 0 warnings
site written to .../.scratch/f2/_site (dry run, not sealed)
EXIT=1

$ refdes check --require-citations
usage: refdes [-h] [-V] [-c CONFIG] [--no-write]
              {serve,build,check,revision,release,index,ls,id,fetch,audit,init,new,schema,standard,keys,revise,calc-rewrite,stub-tests,former-ids,history} ...
refdes: error: unrecognized arguments: --require-citations
EXIT=2
```

**Nothing has changed since the gate report** — same warning/error messages, same
exit codes. One extra detail the report didn't record: the `check --require-citations`
usage error exits **2** (argparse), not 1.

So the distinction the fix has to preserve is precisely: *the diagnostics are emitted
at both `build` and `check`; only the promotion to a hard error is `build`-only.*

### Supporting checks

Flag is on `build` only, in the parser and in `--help`:

```
$ refdes build --help | grep -c require-citations   -> 2
$ refdes check --help | grep -c require-citations   -> 0
```

`src/refdes/cli.py:1517-1522` adds `--require-citations` to `p_build` and nowhere
else. It reaches the verifier at `src/refdes/cli.py:247` →
`require_citations=args.require_citations` → `build.py:2928`
`citations_mod.verify(project, require=require_citations)`. `citations.verify()` has
`require: bool = False` (`src/refdes/citations.py:646`) and is called from exactly
one place, so `check` always runs it with `require=False`.

The first table row's `info` severity and its `-v` gating, also checked by deleting
the lockfile and re-running (remote paths need network, so only the unpinned-local
case was exercised live; the other two soft rows are covered by the `severity =
project.error if require else project.warn` line at `citations.py:676`, shared with
the local-changed case I did exercise):

```
$ refdes check                      -> (silent)
$ refdes check -v                   -> INFO    items/cmp.yaml:3 [CMP-001] — citation to docs/spec.txt has no fetched record; run 'refdes fetch --path docs/spec.txt' to pin it
$ refdes build --dry-run -v         -> INFO    items/cmp.yaml:3 [CMP-001] — ... (same)
$ refdes build --dry-run -v --require-citations
                                    -> ERROR   items/cmp.yaml:3 [CMP-001] — ... (same)
                                       EXIT=1
```

Confirms the row is accurate as written except for the implied command: the info is
hidden unless `-v` at *both* commands, and the escalation exists only at `build`.

## The fix

Chose option (b) plus a one-clause note in the intro sentence, not (b) alone and not
(a) alone:

- (a) alone is not a fix. "checked at every `build` and `check`" is **already true** —
  I confirmed `check` emits the drift warning. The defect lives in the parenthetical,
  which reads as a flag on whichever command the reader was last told about.
- So the parenthetical now spells out `refdes build --require-citations` in all four
  rows, and the intro gains a single clause saying the escalation is `build`'s flag
  and that `check` has no equivalent.

I deliberately did **not** claim "`check` exits zero on citation drift" — that would be
false for the two `**error, always**` rows (hash mismatch, missing local file), which
do fail `check`. The clause is scoped to "the soft rows below".

The `**error, always**` rows needed no change: they are accurate at both commands and
are not affected by the flag. The hash-mismatch paragraph just after the table
(`markdown.md:447-448`) mentions the flag bare but makes no claim about which command
owns it, so it was left alone.

### One change slightly outside the literal table scope

After the table edit I rendered the page and grepped every `--require-citations` on it.
A sixth mention turned up at `markdown.md:327`, in the local-path paragraph
(*"A local file that changed since it was pinned is a warning naming every citer …
an error with `--require-citations`"*). That is the **same situation, the same flag,
the same bare-name defect**, in the same page — leaving it would mean the page still
contains the phrasing that started this task. Qualified it identically
(`refdes build --require-citations`). One line, same file, no restructuring. Flagging
it here because the task scoped the fix to "the table and its intro sentence".

Final state of all six mentions on the rendered page, from `_docs/markdown.html`:

```
  ... -update --path <path>), an error with refdes build --require-citations
  ... e entry for a cited path info (error with refdes build --require-citations
  ... local blob is missing warning (error with refdes build --require-citations
  ... ed warning naming every citer (error with refdes build --require-citations
  ... ed warning naming every citer (error with refdes build --require-citations
  ... t-failed — a corrupted or tampered local cache is not something --require-citations
```

Five qualified; the sixth is the hash-mismatch sentence, which correctly keeps the bare
name because it is contrasting the flag's presence with its absence, not attributing
it to a command.

`grep -rn "check --require-citations" docs/` → no matches anywhere in `docs/`.

## Re-read for internal consistency

The intro clause and the table now agree with the measured behavior row by row:

| Row | Intro claims | Measured |
|---|---|---|
| no lockfile entry | info, hidden unless `-v` | silent at `check`/`build`; `INFO` at `check -v` and `build -v` — matches |
| ↑ escalation | `build` only | `ERROR` at `build -v --require-citations`, exit 1 — matches |
| `keep_copy: true`, no blob | warning, `build` only | same `severity = error if require else warn` line as the local-changed row (`citations.py:676`) — matches |
| blob hash mismatch | **error, always** | docstring `citations.py:658-660`, "ERROR always, never soft-failed" — matches |
| cited local file missing | **error, always** | docstring `citations.py:661-662` — matches |
| local file changed | warning naming every citer, `build` only | warning + exit 0 at `check` and `build`; `ERROR` + exit 1 at `build --require-citations` — matches |
| `section:` unresolved | warning naming every citer, `build` only | `_apply_section(..., severity)` (`citations.py:688`) — same escalation — matches |

The intro's "so the soft rows below stay warnings at `check` and never fail it" is
scoped to the soft rows on purpose: it would be false for the two `**error, always**`
rows, which do fail `check`.

## Build / test

- `refdes build` in `docs-site/` (what `.github/workflows/docs.yml` runs): exit 0,
  `0 items, 0 errors, 4 warnings` — all four warnings pre-existing
  (`site.assets` entry, and three `reference to citation ''` in `docs/vocabulary.md`,
  untouched by this change). No new diagnostics, and the table renders as a real table.
- `refdes build --dry-run` at the repo root: exit 1 on a pre-existing, unrelated
  `P_dens violates BND-THM-001` bound on `items/decisions/dec-pwr-001-regulator-topology.md`.
  Not caused by this change — a `docs/` prose edit produces no item diagnostics.
- `pytest tests/ -q`: **2763 passed, 2 skipped**.

## Files

- `docs/markdown.md` — the only source file changed.
- `changelog.d/require-citations-build-only.fixed.md` — new fragment.
- `in-prog-logs/require-citations-docs-f2.md` — this log.
- Scratch project left at `.scratch/f2` (gitignored).

## Not done

- No `src/` change. `check`'s argument parser is untouched, as instructed. No `ruff`
  run needed — no Python was modified.
- `docs/cli-reference.md:26` already lists `--require-citations` under
  `## refdes build` with correct scoping, so it is consistent with the fix; left alone
  (out of the one-file scope).
- `docs/output.md:422` and `docs/math.md:216` also mention the flag bare, but both are
  output-schema/calc prose that never says the flag applies to `check`; the inaccuracy
  the gate found was specific to `markdown.md`'s table, whose intro put the reader at
  `check` first. Not in the one-file scope. Left alone.

