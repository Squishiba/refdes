# `refdes ls --workspace` (F1)

Source finding: `in-prog-logs/user-sim-release-gate-run2.md` §2, F1 — "`refdes ls`
has no `--workspace`, in a release where workspaces are a headline feature".

## What I set out to do

`check` takes both `--board` and `--workspace`; `ls` takes `--type`, `--board`,
`--file`, `--tag` and no `--workspace`. Add the missing one, filtering exactly
the way `ls --board` already filters, and match `check`'s `--workspace` naming.

## Repro of the gap (before any change)

Scratch project at `.scratch/ls-workspace-flag-f1/wsproj/` — `item_layout:
workspace`, three workspaces (`platform` shared, `product-a`, `product-b`), two
registered boards, five items. Run through this checkout's `src` (the `refdes`
on PATH is an editable install pointing at a *different* worktree,
`help-text-gaps-f3-f5`, so `.scratch/ls-workspace-flag-f1/r.py` inserts this
worktree's `src` first — same stale-install trap run 2 noted in its preamble).

```
$ refdes -c …/wsproj/refdes-project.yaml ls
DEC-A-001     decision     board-a  Uses the shared platform.
DEC-A-002     decision     board-a  Stays within product-a.
DEC-B-001     decision     board-b  Secretly depends on product A.
REQ-A-001     requirement  board-a  Product A's own requirement.
REQ-PLAT-001  requirement           Shared platform requirement.
exit=0

$ refdes -c …/wsproj/refdes-project.yaml ls --workspace product-a
usage: refdes [-h] [-V] [-c CONFIG] [--no-write]
              {serve,build,check,revision,release,index,ls,id,fetch,audit,init,new,schema,standard,keys,revise,calc-rewrite,stub-tests,former-ids,history} ...
refdes: error: unrecognized arguments: --workspace
exit=2
```

The data the listing needs is already exported, confirmed on the same project:

```
$ refdes -c …/wsproj/refdes-project.yaml index --compact | grep -o '"workspace": "[a-z-]*"'
"workspace": "product-a"
"workspace": "product-a"
"workspace": "product-b"
"workspace": "product-a"
"workspace": "platform"
```

plus a top-level `"workspaces": {"platform": …, "product-a": …, "product-b": …}`.
`check --workspace product-a` on the same project prints `3 items, 0 errors, 0
warnings` — so the answer exists, just not through `ls`.

## Filter-combination semantics: AND, and no registry validation

Read `cmd_ls` (`src/refdes/cli.py:424-479`) before adding to it. Every filter is
an independent `continue` in one loop, so `--board`+`--type`+`--file`+`--tag`+query
combine as a plain **AND** — no error, no precedence, no special case. Verified
on the scratch project:

```
$ refdes … ls --board board-a --type decision
DEC-A-001  decision  board-a  Uses the shared platform.
DEC-A-002  decision  board-a  Stays within product-a.
```

So `--workspace` joins the same chain as another AND term.

The other deliberate choice: `ls` does **not** validate its filter values
against the registries, and I kept that. `ls --board nosuch` prints
`no items match` and exits 0; `check --workspace nope` instead errors with
"`--workspace 'nope' is not a workspace declared in refdes-project.yaml's
workspaces: registry`" and exits 1. That difference is not an accident to
paper over — `check` is a gate whose whole job is catching mistakes, while `ls`
is a query tool where "nothing matches your typo" is a legitimate answer, and
`--board` on `ls` already behaves that way. Adding registry validation to only
the new flag would make `ls` inconsistent with itself, which is the opposite of
"filter the same way `--board` does". Noted here so the asymmetry with `check`
is a decision on record, not an oversight.

## Board × workspace: orthogonal, per the data model

Checked `docs/workspaces.md`: "Boards … group items by hardware. A **workspace**
groups boards one level higher — an ownership boundary, not a hardware one", and
under `item_layout: workspace` the workspace is the 1st path segment and the
board the 2nd. `Item.board` and `Item.workspace` are two independent fields
(`src/refdes/model.py:535-536`), both resolved by the same precedence
(item's own value, then the file's `defaults.`, then the path). So
`--board board-a --workspace product-a` is a meaningful AND, and
`--workspace`+`--type`/`--tag` are too. One caveat worth knowing: the two
registries share a namespace for generated report filenames, so a name can never
be both a board and a workspace (load-time error) — which means the combination
can never be self-contradictory by name collision either.

## Plan

1. `src/refdes/cli.py`: one `continue` in `cmd_ls`, one `add_argument` in the
   `p_ls` block, worded off `--board`'s existing help text.
2. Tests: positive filtering in `tests/test_workspaces.py` (that's where the
   `workspace_project` fixture and the existing `check --workspace` CLI tests
   live — `tests/test_blocks.py`, which holds the rest of the `ls` tests, has no
   `workspaces:` registry at all, so every `item.workspace` there is `""` and no
   positive filter is expressible with its fixture). Plus the flat-project
   regression and the help-text assertions in `tests/test_blocks.py`, next to
   the other `ls` tests.
3. Docs: the `refdes ls` option table in `docs/cli-reference.md`, and the
   "Reviewing one workspace" section of `docs/workspaces.md`.
4. `changelog.d/ls-workspace-flag.added.md`.

## What changed

- `src/refdes/cli.py` — two lines of substance. In `cmd_ls`'s filter chain,
  immediately after the `--board` clause: `if args.workspace and
  item.workspace != args.workspace: continue`. In the `p_ls` block, between
  `--board` and `--file`: `p_ls.add_argument("--workspace", help="only items in
  this workspace")` — same shape and voice as `--board`'s `"only items on this
  board"`, no `metavar` (none of `ls`'s filters set one; `check`'s do).
- `tests/test_workspaces.py` — four tests, placed with the existing
  `check --workspace` CLI tests.
- `tests/test_blocks.py` — two tests, placed with the other `ls` tests.
- `docs/cli-reference.md` — `--workspace WORKSPACE` row in the `refdes ls`
  option table, an example line, and a short paragraph on AND-combination and
  the unknown-name posture.
- `docs/workspaces.md` — `refdes ls --workspace product-a` added to "Reviewing
  one workspace", with why.
- `changelog.d/ls-workspace-flag.added.md`.

## After (same scratch project)

```
$ refdes … ls --workspace product-a
DEC-A-001  decision     board-a  Uses the shared platform.
DEC-A-002  decision     board-a  Stays within product-a.
REQ-A-001  requirement  board-a  Product A's own requirement.
exit=0

$ refdes … ls --workspace platform
REQ-PLAT-001  requirement  Shared platform requirement.
exit=0

$ refdes … ls --workspace product-a --type decision
DEC-A-001  decision  board-a  Uses the shared platform.
DEC-A-002  decision  board-a  Stays within product-a.

$ refdes … ls --workspace product-a --board board-b
no items match

$ refdes … ls --workspace product-a --tag review
DEC-A-001  decision  board-a  Uses the shared platform.

$ refdes … ls --workspace nosuch
no items match
exit=0
```

Three items for `product-a`, matching `check --workspace product-a`'s
`3 items` line exactly — the two commands now agree about what a workspace
contains.

`ls --help` after:

```
  --type TYPE           only items of this type
  --board BOARD         only items on this board
  --workspace WORKSPACE
                        only items in this workspace
  --file FILE           only items declared in this source file
  --tag TAG             only items with a tag containing this text
```

## Tests added

`tests/test_workspaces.py` (uses the module's `workspace_project` fixture —
`item_layout: workspace`, `platform` shared + `product-a` + `product-b`):

- `test_ls_workspace_flag_lists_only_that_workspaces_items` — the three
  product-a items in, `REQ-PLAT-001` and `DEC-B-001` out.
- `test_ls_workspace_flag_is_a_shared_workspace_its_own_row` — `--workspace
  platform` is `REQ-PLAT-001` alone.
- `test_ls_workspace_flag_combines_as_and_with_type_and_board` — `--workspace
  product-a --type decision` drops the requirement; `--workspace product-a
  --board board-b` matches nothing (product-a's items are all on `board-a`).
- `test_ls_unknown_workspace_matches_nothing_rather_than_erroring` — pins the
  deliberate `ls`-vs-`check` asymmetry described above, so it can't be "fixed"
  by accident later.

`tests/test_blocks.py` (its `blocks_project` fixture has no `workspaces:`
registry — every `item.workspace` is `""`):

- `test_ls_workspace_flag_matches_nothing_without_a_workspaces_registry` — the
  flat/no-registry regression case: exit 0, "no items match".
- `test_ls_help_advertises_the_workspace_flag` — F1 is a discoverability
  finding, so the flag has to show in `ls --help`.

## Verification

- `pytest tests/` → **2769 passed, 2 skipped** (196s). Green.
- `ruff check src/refdes/cli.py --select I,F` → All checks passed. Also ran the
  same selection over the two touched test files: clean.
- Docs changes are prose/table only; no generated-docs gate covers them
  (`tests/test_docs_examples.py` pins `docs/schema-reference.md`'s generated
  block, which this doesn't touch), and the full suite above includes it.

## Notes / judgement calls

- No workspace column was added to `ls`'s output. The finding asked for the
  filter, and adding a column would change every existing `ls` line in a
  workspace project — a wider, unrequested output change. `--board`'s column is
  already there for the hardware half.
- `check`'s `--workspace` help says "same report-filter posture as `--board`,
  and combinable with it"; `ls`'s filters carry no such commentary for `--board`
  either, so the new help string stays as terse as its neighbours and the
  combinability is documented in `docs/cli-reference.md` and pinned by a test
  instead.
- Nothing else touched: `check`, `index`, `audit` and the rest keep their own
  workspace handling untouched.

## Status

Done. Committed and PR'd against `main`.
