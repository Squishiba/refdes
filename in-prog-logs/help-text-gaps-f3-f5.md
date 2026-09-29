# help-text gaps F3 + F5 — `release` and `standard upgrade` argparse text

Source: `in-prog-logs/user-sim-release-gate-run2.md` §2 **F3** (line 326) and
**F5** (line 366). Two independent `--help` text fixes, no behavior change,
both confined to `src/refdes/cli.py`'s parser setup.

`pip install -e .` on this checkout was needed first (the `refdes` on `PATH`
came from a stale editable install pointing at a deleted worktree — same
environment note as run 2's header). Version reported: `refdes 0.5.0`.

---

## F3 — `release --help` names none of the eight gate rules

### Facts verified, not copied

**The eight current rule names**, read from the loaded module rather than
from the report or from `docs/`:

```
$ python -c "from refdes.lifecycle import RULE_NAMES; print(len(RULE_NAMES)); print(', '.join(RULE_NAMES))"
8
draft_items, unpinned_citations, missing_kept_copies, uncovered_requirements,
unverified_requirements, info_check_failures, unaccepted_board_moves,
unaccepted_workspace_moves
```

(`lifecycle.py:597` — `RULE_NAMES = tuple(RELEASE_GATE_DEFAULTS)`; the dict
itself is `model.py:57`. Order is insertion order of the dict, which is the
order the config-typo error also prints.)

**The config-typo error really does print the full list** — reproduced on a
scratch project (`.scratch/f3f5/v1ok/`) with a bogus rule appended:

```
$ refdes check
configuration error: refdes-project.yaml: release_gate.nosuch_rule is not a known rule (one of draft_items, unpinned_citations, missing_kept_copies, uncovered_requirements, unverified_requirements, info_check_failures, unaccepted_board_moves, unaccepted_workspace_moves).
exit 2

$ refdes release demo
configuration error: refdes-project.yaml: release_gate.nosuch_rule is not a known rule (one of draft_items, unpinned_citations, missing_kept_copies, uncovered_requirements, unverified_requirements, info_check_failures, unaccepted_board_moves, unaccepted_workspace_moves).
exit 2
```

**Docs line numbers confirmed** (the report's ~47-57 / ~165-173 have moved
slightly): the eight-rule table with its "Blocks a release when…" column is
`docs/lifecycle.md:47-56`; the sample gate report showing `FAIL uncovered_requirements`
is `docs/cli-reference.md:153` / `:168`.

**Is a static literal necessary?** Yes. `description=` here is a plain string
literal, like every other parser description in `cli.py` (e.g. `keys adopt`
at `cli.py:1790`, `revision` at `cli.py:1573`) — there is no precedent in
this file for an f-string description, and argparse help strings are plain
text rendered into `--help`; injecting `RULE_NAMES` at runtime would make the
help text depend on import-time state for no benefit over writing the list
out, given the dict is module-level and frozen. The names were transcribed
from the live `RULE_NAMES` output above, not from the report's sample report.

### Before

```
$ refdes release --help
usage: refdes release [-h] name

Run the full readiness gate (release_gate: in refdes-project.yaml) and stamp
.refdes/baselines/<name>.yaml only if every enabled rule passes. On failure,
nothing is written and the blocking rules are printed. Running this when the
project isn't ready *is* the check -- there is no --dry-run. Takes exactly one
argument (the name); the global --no-write flag is accepted to report what
would be stamped without writing.

positional arguments:
  name        baseline name, e.g. rev-b

options:
  -h, --help  show this help message and exit
```

### After

One sentence added, immediately after the "every enabled rule passes"
clause that is what makes the reader want the list:

```
usage: refdes release [-h] name

Run the full readiness gate (release_gate: in refdes-project.yaml) and stamp
.refdes/baselines/<name>.yaml only if every enabled rule passes. The eight
rules are draft_items, unpinned_citations, missing_kept_copies,
uncovered_requirements, unverified_requirements, info_check_failures,
unaccepted_board_moves, and unaccepted_workspace_moves. On failure, nothing is
written and the blocking rules are printed. Running this when the project
isn't ready *is* the check -- there is no --dry-run. Takes exactly one
argument (the name); the global --no-write flag is accepted to report what
would be stamped without writing.

positional arguments:
  name        baseline name, e.g. rev-b

options:
  -h, --help  show this help message and exit
```

---

## F5 — `standard upgrade --help` overstated rollback as all-or-nothing

### The per-step rollback behavior, verified by running it

The report claims a `--to 9` from v1 applies v1→v2, then v2→v3, then fails
at the v3→v4 step, exiting 1 with `standard.version: 3` and the v3 rewrites
already on disk. Reproduced for real, twice, on scratch projects.

**(a) chain fails at an intermediate step** — `.scratch/f3f5/v1clean/`,
pinned at `standard: hardware@1` with a `constraint`/`requirement` pair, both
carrying prose bodies (the thing that trips v3's `text:` → `body:` merge
guard):

```
$ refdes standard upgrade --to 9
v1 -> v2:
changed 1 file(s):
  items/power/con-001.md
id changes:
  CON-THM-001 -> BND-THM-001
v2 -> v3:
refused:
  items/power/req-001.md:2 [REQ-PWR-001] -- can't rename requirement.text to body: this item already has its own body content, which the rename would silently orphan or overwrite. Merge them by hand first.
  items/power/con-001.md:2 [BND-THM-001] -- can't rename bound.text to body: this item already has its own body content, which the rename would silently orphan or overwrite. Merge them by hand first.
exit 1

--- config after:
standard:
  base: hardware
  version: 2
  presets: []

--- items after:
items/power/con-001.md:
---
key: gmb3ndjeyqe
type: bound
id: BND-THM-001
text: Thermal ceiling
status: active
limit: "<= 60 C"
---

--- check after:
2 items, 0 errors, 2 warnings
```

**This is the key data point**: the v1→v2 step's rewrite (`type: constraint`
→ `bound`, `CON-` → `BND-`, `title:` → `text:`, key minted) is *still on
disk* after the v2→v3 step was refused, and the project loads clean at
`standard.version: 2`. The invocation is not atomic; the failing step alone
rolled back.

**(b) chain runs past the newest bundled version** — `.scratch/f3f5/v1ok/`,
same v1 project without prose bodies, so the real v2 and v3 steps both
apply:

```
$ refdes standard upgrade --to 3
v1 -> v2:
changed 1 file(s):
  items/power/con-001.md
id changes:
  CON-THM-001 -> BND-THM-001
v2 -> v3:
changed 2 file(s):
  items/power/con-001.md
  items/power/req-001.md

upgraded to v3.
exit 0
...
$ refdes standard upgrade --to 9
v3 -> v4:
refused:
  rewritten project no longer loads: standard.version 4 does not exist for base 'hardware' (available: ['v1', 'v2', 'v3'])
exit 1
--- config after: version: 3
```

`--to 9` from v3 keeps `standard.version: 3` (the v3→v4 step rolled back,
nothing before it needed to), matching what `docs/cli-reference.md` says.

**Docs line confirmed**: the precise wording — "Stops at the first version
step that fails, leaving the project fully valid at whatever version it
reached" — is `docs/cli-reference.md:660-667` (as the report said); the
`refdes check` / sample-report references moved to `:153`/`:168`.

Code path that produces (a)/(b): `revise.apply_standard_upgrade()`
(`src/refdes/revise.py:1704`) loops `while current < to_version`, appends each
step's result, and `break`s on `not result.ok` (`revise.py:1760-1761`) —
already-completed steps are never revisited.

### Before

```
$ refdes standard upgrade --help
usage: refdes standard upgrade [-h] --to N

Chain the bundled standard's own migration.yaml files, one version at a time,
from the project's currently pinned standard.version: up to --to N -- each
step rewrites item files for that version's own rename, bumps
standard.version: to match, and carries content hashes forward in every
stamped baseline and seal so the rename doesn't look like a content change.
Never merges steps: a multi-version jump is always applied as its full chain
of individual deltas, in order. Refuses (rolling back cleanly) rather than
guessing at an ambiguous or ill-formed step.

options:
  -h, --help  show this help message and exit
  --to N      target standard.version: to upgrade to
```

### After

```
usage: refdes standard upgrade [-h] --to N

Chain the bundled standard's own migration.yaml files, one version at a time,
from the project's currently pinned standard.version: up to --to N -- each
step rewrites item files for that version's own rename, bumps
standard.version: to match, and carries content hashes forward in every
stamped baseline and seal so the rename doesn't look like a content change.
Never merges steps: a multi-version jump is always applied as its full chain
of individual deltas, in order. Refuses the failing step, rolling it back
cleanly rather than guessing at an ambiguous or ill-formed one; earlier
steps in the chain stay applied.

options:
  -h, --help  show this help message and exit
  --to N      target standard.version: to upgrade to
```

Same length, same register, same final-sentence slot; only the rollback
scope changes from "the invocation" to "the step".

---

## Tests / lint

- `pytest tests/` — full suite green (no test asserts on either help string;
  grepped `tests/` for `rolling back`, `release_gate` and `--help`, the hits
  are `tests/test_blocks.py`, `tests/test_no_write.py`,
  `tests/test_version_flag.py`, none of which touch these two descriptions).
- `ruff check src/refdes/cli.py --select I,F` — clean. (Repo-wide bare
  `ruff check .` has ~99 pre-existing findings, untouched, per AGENTS.md.)

## Changelog

`changelog.d/help-text-gate-rules-and-upgrade-rollback.fixed.md` — one
fragment covering both, since they are the same run and the same class of
fix (a documented fact the `--help` was the only place left claiming
something narrower or stronger than the truth).

## Scratch

`.scratch/f3f5/` holds the repro projects: `v1clean/` (mid-chain refusal) and
`v1ok/` (chain succeeds, then refuses past the ceiling). Both are throwaway
and gitignored.
