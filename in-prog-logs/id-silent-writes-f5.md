# F5 — `refdes id` reported "nothing to do" while its own load rewrote files

Source finding: `in-prog-logs/user-sim-release-gate-run1.md` §F5.

## Status: finished — full suite green, PR against `main`

## Reproduced first (before touching anything)

Scratch project at `.scratch/f5-proj/` (two items that already carry display
ids, one bare `refines: [REQ-001]`, no `key:` lines anywhere), driven through
`.scratch/run_refdes.py` (a 6-line shim that puts `src/` on `sys.path` and
calls `refdes.cli.main`, since the installed `refdes` on PATH is not this
worktree):

```
$ python .scratch/run_refdes.py -c .scratch/f5-proj/refdes-project.yaml id
no items are missing an id
[exit=0]
```

and `items/r.yaml` after that single run:

```yaml
defaults: { type: requirement }
items:
  - key: h8d6n6577a9
    id: REQ-001
    text: Target.
  - key: 74p0rajz87p
    id: REQ-002
    text: Refiner.
    refines: [REQ-001@h8d6n6577a9]
```

Two `key:` lines minted and one link target rewritten to the composite form,
reported as "no items are missing an id". Confirmed: messaging bug, not a
minting/expansion bug.

## What the code actually does

`cli._load` -> `loader.load_tree` (src/refdes/loader.py:61) runs five
write-back steps, each of which returns the list of what it actually wrote
and each of which returns `[]` when `write=False` (i.e. `--no-write` or
`--dry-run`):

- `keys_mod.mint_missing(project, write=...)` -> `list[tuple[Item, str]]`
  (keys.py:714). Its result was bound to `minted` only to decide whether to
  reparse; the count never left `load_tree`.
- `links_mod.expand_missing` (links.py:461), `expand_missing_checks`
  (links.py:896), `expand_missing_calc_refs` (links.py:1089) ->
  `list[tuple[Item, str, str, str]]`. All three return values were discarded
  outright.
- `links_mod.freeze_follows` (links.py:738) -> same tuple shape; its return
  was already used truthy (`if frozen_follows:`) to trigger a reparse.

So every count needed for the message already exists at the call site; none
of it reached `cli.cmd_id`.

## (a) widen `load_tree`'s return, or (b) stash the counts on `Project`

`grep -rn "load_tree(" src/ tests/` gives 3 call sites in `src/`
(`loader.load_readonly`, `cli._load`, the definition) and **33 in
`tests/`** — 30 of which unpack `project, _stale = loader.load_tree(...)`.
Option (a) means editing all 30 test unpackings for a fix whose whole job is
to add one line of stdout. Option (b) touches the definition of `Project`,
`load_tree`, and the one command that reports it; every other caller is
untouched and keeps compiling.

Chose **(b)**: a `LoadWrites` dataclass on `Project`, defaulting to an empty
(all-zero, falsy) record, filled in by `load_tree` and read by `cmd_id`.
It is also the honest model of what these numbers are — a fact about *this
load*, already living on the object that carries every other per-load
side-effect state (`imports_loaded`, `source_overlay`, `board_moves`).

## Message

House style for counts in this file is `allocated N id(s)` (cli.py:497), so
the notice keeps the `(s)` form rather than hand-pluralising:

```
(minted 2 key(s) and rewrote 1 reference(s) while loading)
no items are missing an id
```

"reference(s)" is the umbrella the codebase already uses for all four rewrite
kinds — `links._report_missing` says "link references",
`_report_missing_checks` "check references", `_report_missing_calc_refs`
"calc references", and a frozen `follows:` edge is a link target. Naming them
"link targets" would have been wrong for two of the four.

Printed before the verdict, not after: a run that just rewrote three lines
should not lead with "nothing is missing".

## The change

- `model.py`: new `LoadWrites` dataclass (`minted_keys`, `rewritten_targets`,
  falsy when both are zero) and `Project.load_writes`, next to the other
  per-load state (`imports_loaded`, `source_overlay`).
- `loader.load_tree`: binds the four previously-discarded expansion results
  and `minted`'s length into `project.load_writes`. No change to *when* or
  *whether* anything is written — the counts are read off the return values
  that were already there.
- `cli.py`: `_load_write_notice(project)` formats the line; `cmd_id` prints it
  straight after `_load`, so it covers all three of that command's branches
  (load errors, nothing pending, allocation happened). `ids_mod.allocate`'s
  own "allocated N id(s)" reporting is untouched.

One judgement call worth flagging: the notice also prints on the branch where
ids genuinely were allocated (`refdes id` on a brand-new item mints that
item's key on the way in, then allocates). That is the same silent write F5
is about, and the newcomer walkthrough hits it first, so it is reported too:

```
(minted 1 key(s) while loading)
allocated 1 id(s)
```

## Verification

New tests, in `tests/test_load_time_writes.py` (the file that already owns
"what the load writes to your files"), section *the load's own writes get
reported (F5)*:

- `test_id_reports_the_keys_and_link_target_its_load_wrote` — the F5 repro.
- `test_id_reports_load_writes_alongside_its_own_allocation` — pending branch.
- `test_id_quiet_case_prints_only_its_own_verdict` — asserts stdout is exactly
  `"no items are missing an id\n"` on the second run, so the quiet case cannot
  regress.
- `test_id_names_only_the_rewrite_when_the_keys_already_exist` — bare a
  composite back by hand, so the notice says "rewrote" and not "minted".
- `test_id_no_write_says_nothing_about_writes_it_did_not_make` and
  `test_id_dry_run_says_nothing_about_writes_it_did_not_make` — one line of
  stdout, and the item file byte-identical afterwards.

```
$ pytest tests/ -q
2719 passed, 2 skipped in 197.25s (0:03:17)

$ ruff check src/refdes/cli.py src/refdes/loader.py --select I,F
All checks passed!
```

(model.py and the test file were run through the same `--select I,F` and are
clean too. The repo's ~99 unrelated `ruff check .` findings were left alone.)

### Manual, twice in a row, `.scratch/f5-proj2/`

First run (nothing on disk but ids; two keys and one link to mint):

```
$ python .scratch/run_refdes.py -c .scratch/f5-proj2/refdes-project.yaml id
(minted 2 key(s) and rewrote 1 reference(s) while loading)
no items are missing an id
[exit=0]
```

Second run, same project, nothing left to mint:

```
$ python .scratch/run_refdes.py -c .scratch/f5-proj2/refdes-project.yaml id
no items are missing an id
[exit=0]
```

Read-only paths on a fresh keyless project (`.scratch/f5-proj3/`), which must
say nothing and write nothing:

```
$ python .scratch/run_refdes.py --no-write -c .scratch/f5-proj3/refdes-project.yaml id
no items are missing an id
[exit=0]
$ python .scratch/run_refdes.py -c .scratch/f5-proj3/refdes-project.yaml id --dry-run
no items are missing an id
[exit=0]
```

and `items/r.yaml` was still the two unkeyed items with `refines: [REQ-001]`
after both.

## Not done, deliberately

`cmd_stub_tests` (cli.py:1183, "no coverable item is missing a verifying
test") has the identical gap — same `_load`, same silent minting, and it is
the other command `--no-write` forces onto `--dry-run`. Fixing it is the same
three lines (`notice = _load_write_notice(project); if notice: print(notice)`),
but it is a second command's output changing and its own tests to re-check, so
it is left for a separate pass rather than folded in here. The helper is in
place for it.

Task finished.
