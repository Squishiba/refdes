# Source-bug cleanup sweep (session refdes-179)

One commit per bug, each with a test that fails on the unfixed code. Branch
`ao/refdes-179/source-bug-sweep`, one PR at the end, not merged here.

Every "fails before the fix" claim below was verified by restoring the
unfixed file with `git checkout HEAD -- <file>` (never `git stash` — there is
a pre-existing `stash@{0}` belonging to another session that I did not touch)
and re-running the new tests.

## Commits

| # | Bug | Commit |
|---|---|---|
| 1 | `former-ids propose` printed an empty old title on the key-paired path | `32870b3` |
| 2 | `revise <missing/broken mapping>` died with a traceback, not exit 2 | `b3c1dfb` |
| 3 | `revise` did not validate a link rename's target verb | `5a4f355` |
| 4 | global `--no-write` help omitted `calc-rewrite` | `3bac9cf` |
| 5 | `--dry-run` still wrote `key:` lines during the load | `9dc1461` |
| 6 | `calc-rewrite` refused the tolerance line `check` points it at | `09e5de2` |
| — | two docs fixes (type count, `sets:`) | `a94842b` |

## 1. Empty old title in `former-ids propose`

`src/refdes/former_ids.py:110` looked the baseline entry up by the surrogate
key. A current baseline is keyed by **display id** with the surrogate inside a
`key:` field (`lifecycle._items_map`), so the lookup missed, `entry` fell back
to `{}`, and `old_title` printed as `''` on every candidate — which is the
field that tells a human which item they are about to re-identify.

Fixed by resolving the record through both shapes (key first, then display
id), so the shape `refdes keys adopt` produces keeps working. 3 new tests: two
fail pre-fix, one pins the adopted shape.

## 2. `revise` on an unreadable mapping file

`cmd_revise` already had `except SchemaError -> exit 2`, but
`revise.load_mapping` let `FileNotFoundError` / `IsADirectoryError` /
`yaml.YAMLError` escape past it, so the crash produced a traceback and exit 1
— the exact case the global exit-code table promises 2 for. All three are now
wrapped in `load_mapping`, **before** the project is even loaded, as a
one-line message (PyYAML's multi-line mark-and-caret report is collapsed to
one line). 6 new tests, all verified failing pre-fix.

Found while reproducing: an unparseable mapping file crashed identically. Same
function, same handler, so it is fixed in the same commit rather than left as
a second traceback path.

## 3. Link rename's target verb was not validated

`check_ambiguous` validated a *type* rename's target in both directions and a
*link* rename's only in the collision direction. `links: {refines: narrows}`
on hardware@3 rewrote every `refines:` line to `narrows:`, exited 0, and left
`unknown field 'narrows'` as a **warning** — so every renamed edge silently
stopped being an edge. A type rename does not get away with this because an
unknown type is a hard error the post-rewrite reload rolls back; an unknown
link verb is not.

Now refused up front. Two deliberate scoping decisions, both pinned by tests:

- **A verb counts as known from either end.** `refined_by` is not a
  `link_types:` key of its own but is a spelling the project resolves
  (`schema.py`'s two-way `inverse_of`). A check consulting only
  `project.link_types` would refuse a valid rename.
- **The check only fires when the old verb is known**, so a mapping naming a
  verb this project never had still reports `nothing to do` instead of a hard
  failure (the chained-migration leniency `check_ambiguous`'s own docstring
  promises).
- **`standard upgrade` is exempt** (`schema_moving=standard_transition is not
  None`). This is load-bearing: hardware v2's `equivalent` becomes v3's
  `drop_in`, and `drop_in` is not a v2 link type. A regression test runs a
  real v2->v3 upgrade end to end.

## 4. `--no-write` help text

`calc-rewrite` folds `--no-write` into `--dry-run` (cli.py `cmd_calc_rewrite`)
and reports/writes nothing, which `docs/cli-reference.md`'s global table
already said. The global help string's reporting list omitted it. The docs
were right, so no doc change; a test now pins the whole reporting set so the
help and the table cannot drift apart again.

## 5. `--dry-run` was not side-effect-free — **fixed**, it was small and safe

`refdes id --dry-run` printed `no items are missing an id` and reported
success while the *load* on the way in had already written a `key:` line into
the item file. Loading mints every missing surrogate key and expands bare link
references into `DISPLAY-ID@key` composites.

Judgment: **small and safe, so fixed.** `_load()` already threaded
`write=not args.no_write`, and both commands with a `--dry-run` that use it
(`cmd_id`, `cmd_stub_tests`) already force `args.dry_run` from `--no-write` —
so the combination "dry run + write=False" was not a third behaviour to get
right, it was the path `--no-write` was already tested through. The change is
folding `dry_run` into the same expression.

**`stub-tests --dry-run` had the identical bug** and the identical one-line
fix. I fixed it in the same commit rather than leaving one command with the
same broken promise; a test covers both.

I did **not** touch `revise`/`calc-rewrite`/`keys adopt`, which have their own
load paths and already left the tree byte-identical under `--dry-run` (verified
by running them). `build --dry-run` still writes `_site/`, which is that
command's own documented output, not a side effect.

## 6. `calc-rewrite` refused the tolerance line — **fixed**

The reported hypothesis was that the meaning-change guard "wrongly counts the
tolerance as a unit difference". The real cause is adjacent and simpler:
`_snapshot_diff`'s "this line did not compute before, so there is nothing to
preserve" guard read **`result is None`**, but `CalcLine.result` is a `str` and
`build.py` only assigns it when the outcome carried a value — so a line that
never computed holds the dataclass default `""`, never `None`. The escape hatch
was dead code, so a retired-spelling line that never parsed fell through to
the comparison and was reported as a meaning change against **its own empty
before-picture**: `was '' in unit 'W ± 10%', now evaluates to '14.4 W' in unit
'W'`. Both halves of that difference were artefacts of the line never having
computed. (The "tolerance as unit" appearance is real but is a *symptom*: the
un-split `W ± 10%` annotation is simply what an unevaluated line holds.)

Clear and local, so fixed (`result is None` -> `not result`). The
post-rewrite full validation still stands behind the rewritten line, and a
test pins that a line which *did* compute before is still refused when the
rewrite would change its value — so the guard was narrowed, not weakened.

Verified end to end: `check` errors, `calc-rewrite` rewrites to exactly the
form `check` named (`P = V_supply * I_load ± 10% | W`), `check` is clean.

---

# Report only: `history migrate-seals` marker ids for deleted sealed items

Not fixed, per instruction. Findings, all reproduced in
`.scratch/repro_migrate.py` / `.scratch/repro_migrate2.py` against a scratch
hardware@3 project.

**What I verified.** `history.migrate_seals` (history.py:879) derives the
marker's identity as
`item_key = key or (item.key if the live item exists) or display_id or record_id`.
Every other event in the store is keyed by an immutable **surrogate**. So for
a seal record whose live item has been **deleted** *and* whose record carries
no surrogate — a pre-keys legacy seal, which is precisely the population this
command exists to migrate — the marker is written with a **display id standing
in for an identity**. Observed event file:

```
item_key: LOG-001        # the deleted item's marker
item_key: 0sqcs3gk5a4    # a later, different item that took the id LOG-001
```

Both events' `reason` text names `LOG-001`, so the store ends up holding two
markers that read as "about LOG-001" under two different key spaces. A reader
resolving markers by display id would attribute the deleted item's marker to
the new item. This is the one case where the marker's id most needs to be
stable identity, because there is no live item left to re-derive it from.

**What I could not reproduce.** An actual *collision* — two distinct seal
records deriving one marker id, which would make the migration silently skip a
record and break the "replaying the same edge is a no-op" guarantee the event
format documents. The seal verifier refuses an append-only id reuse outright
(`LOG-001 is append-only and has been modified since it was sealed`), so the
seal file keeps exactly one record and a second `migrate-seals` correctly
reports `already migrated`. So the hazard is a non-identity `item_key`, not
lost migration records. Severity: low-to-moderate, no data loss.

**Why I did not fix it anyway.** It is out of the assigned scope, and the fix
is not obviously local: minting a surrogate for an item that no longer exists
is exactly the decision the surrogate-key design deliberately declines to make
(`docs/design/keys.md` — keys are minted for live items, and a deleted item's
identity is meant to die with it). Choosing a stand-in needs a real answer to
"what is the identity of something that is gone", which is a design question,
not a bug fix.

**Possible directions, for whoever picks it up.**
1. Leave `item_key` as the display id and *document* it — it is already the
   honest label, and the reason string names the seal file and recorded hash,
   so the marker is self-describing without being identity-bearing.
2. Namespace the fallback so it can never be confused with a surrogate, e.g.
   `deleted:LOG-001`. Cheap, but any reader keying on `item_key` would need to
   learn the prefix.
3. Derive the marker's id from `(kind, seal-file, recorded-hash)` instead of
   from the item, which is what actually makes the record unique. This is the
   most faithful to the existing idempotence guarantee and needs no identity
   for a dead item, but it changes the marker's id for the *live* case too and
   so invalidates already-migrated stores.

## Progress log

- Branch cut from `ao/refdes-179/root` at 7f4b561 (origin/main already merged).
- Bugs 1-6 each fixed, tested, and committed separately; pre-fix failure
  verified for every new test.
- Docs: caveat text removed for bugs 1, 2, 5, 6; bug 3 gained a documented
  section; bug 4 needed no doc change (the docs were already right).
- Changelog fragments added for all seven commits, unique names, existing
  `.added.md`/`.fixed.md` format.
