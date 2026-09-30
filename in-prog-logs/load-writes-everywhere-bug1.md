# Load-time writes everywhere (BUG 1 + BUG 2 from the run-2 release gate)

Source: `in-prog-logs/user-sim-release-gate-run2.md`, §0 BUG 1 and BUG 2.
Scope agreed with the task: the **minimum fix** — report the load's own writes
honestly, and survive a write failure instead of crashing. Not in scope:
changing any command's default from `write=True` to `write=False`, and not
touching `--no-write`'s behaviour.

## What I found (all verified by running, not recalled)

Environment note first: the `refdes` on PATH in this venv is the stale editable
install run 2's report complained about (`ModuleNotFoundError: No module
named 'refdes'`). Everything below ran through
`.scratch/refdes-cli`, which puts this worktree's `src/` on `sys.path`, and
through `pytest` (whose `tests/conftest.py` does the same bootstrap). Scratch
projects are under `.scratch/loadwrites-repro/` + `.scratch/repro/`;
`.scratch/mkproj.py` copies them and flips permissions (`cp`/`chmod` are
outside this session's shell whitelist).

### BUG 1 is real, and it is not only `check`

Repro project: two items that already carry display ids, one bare `refines:`
target, no `key:` anywhere. `.scratch/repro.py` runs each command against a
fresh copy and reports whether `items/r.yaml` changed:

```
=== refdes check
exit: 0
stdout: WARNING <project> — types.requirement does not declare 'coverable:' ...
WARNING <project> — 2 item(s) with no coverage — see coverage.html
2 items, 0 errors, 2 warnings
item file changed: YES

=== refdes --no-write check
exit: 0
stdout: (same three lines)
item file changed: no

=== refdes ls            -> item file changed: YES   (no mention of writing)
=== refdes index --compact -> YES                    (no mention)
=== refdes audit         -> YES                      (no mention)
=== refdes build         -> YES                      (says only "site written to ...")
=== refdes former-ids propose -> YES                 (errors out on "no baseline", still wrote)
=== refdes fetch         -> YES                      (says only "0 citation(s) processed")
=== refdes revision rev-a -> YES                     (says only "revision 'rev-a' stamped")
=== refdes history capture REQ-001 -> YES            (says only "captured REQ-001")
=== refdes id            -> YES, and it DOES say:
    (minted 2 key(s) and rewrote 1 reference(s) while loading)
```

The diff `check` made, unannounced:

```diff
-  - id: REQ-001
+  - key: d5br8vhc040
+    id: REQ-001
     text: Target.
-  - id: REQ-002
+  - key: ckj60wqyp1c
+    id: REQ-002
     text: Refiner.
-    refines: [REQ-001]
+    refines: [REQ-001@d5br8vhc040]
```

`_load_write_notice()` (`src/refdes/cli.py:95`) is called from exactly two
places on the commit I started from: `cmd_id` (cli.py:492) and `cmd_stub_tests`
(cli.py:1193). Every other `_load()` call site — cli.py lines 167 (`check`),
221 (`build`), 313 (`_run_stamp`, i.e. `revision`/`release`), 395 (`index`),
441 (`ls`), 532 (`fetch`), 630 (`audit`), 1225 (`former-ids propose`), 1295 /
1330 / 1380 (`history capture` / `redact` / `migrate-seals`) — loads with
`write=True` and says nothing about what that load wrote. None of them
announces the *load's* writes in its own way; the ones that announce anything
(`build`, `fetch`, `revision`, `history capture`) announce only their own
output. So all of them need the notice, not just the six named in the task.

`cmd_new` (cli.py:854) and `cmd_schema` (cli.py:871) call `schema.load_project`
directly — config only, no item parse, no minting — so they are not in scope.
`cmd_revise`, `cmd_calc_rewrite`, `cmd_standard_upgrade`, `cmd_keys_restore`
and `cmd_keys_adopt` never go through `cli._load` at all (they call
`revise.apply` / `adopt.apply` / `key_restore.apply` on a project root), so
there is no `Project` in the CLI to read `load_writes` from; out of scope.

### The false claim in `--help` is in exactly one place

`grep -rn "Nothing of the project|one exception is|editor-completion schema"`
across `src/`, `docs/`, `tests/`, `README.md`, `editors/`: the only hit for the
claim is `check`'s own description at `src/refdes/cli.py:1536-1542`.
`docs/cli-reference.md:60-67` already tells the truth ("Loading the project can
still write back surrogate `key:` fields ... Run `refdes --no-write check` for
a run that writes none of those either"), so the help text is the outlier, as
the report said. Two neighbouring claims I checked and deliberately left alone:
`check --refresh`'s "(network; writes nothing)" — `citations.refresh()` really
is read-only (citations.py:1552-1560) — and `serve`'s "Loading is
side-effect-free", which is true because serve loads through
`loader.load_readonly`.

### BUG 2 is real, both sites, same line numbers as the report

Whole tree read-only (`python .scratch/repro_ro.py whole check`):

```
exit: UNHANDLED PermissionError
  File ".../src/refdes/loader.py", line 92, in load_tree
    schema_was_stale = schema_json_mod.write_schema(project, write=write)
  File ".../src/refdes/schema_json.py", line 350, in write_schema
    os.makedirs(os.path.dirname(path), exist_ok=True)
PermissionError: [Errno 13] Permission denied: '.../.refdes'
```

Only `items/` read-only, project root writable (`python .scratch/repro_ro.py items check`):

```
exit: UNHANDLED PermissionError
  File ".../src/refdes/loader.py", line 103, in load_tree
    minted = keys_mod.mint_missing(project, write=write)
  File ".../src/refdes/keys.py", line 743, in mint_missing
    write_rewrites_verified(project, plan.rewrites)
  File ".../src/refdes/revise.py", line 703, in write_rewrites_verified
    write_rewrites(rewrites)
  File ".../src/refdes/revise.py", line 640, in write_rewrites
    textio.write_text(rewrite.path, rewrite.after)
  File ".../src/refdes/textio.py", line 273, in write_text
    with open(path, "w", encoding="utf-8", newline="") as fh:
PermissionError: [Errno 13] Permission denied: '.../items/r.yaml'
```

Both are the BUG 1 writes and nothing else, exactly as the report said.

### Is either write safe to skip? Reading what each one is *for*

- `.refdes/schema.json` (`schema_json.write_schema`): a gitignored, regenerated
  on every load, "a pure function of the current merged config". Nothing reads
  it back during a CLI run — `write_schema` returns the *staleness verdict*
  computed from mtimes before the write, and `check`'s trip-wire diagnostic
  uses that verdict, not the file. Skipping the write costs editor completion
  until the next writable command. Safe to skip.
- key minting / link expansion (`revise.write_rewrites_verified`): the write is
  an idempotent normalisation of the source. `--no-write` already runs the
  whole pipeline without it — bare targets still resolve on the display id
  (`links.expand_missing` docstring, `loader.load_tree`'s comments), and the
  in-memory `Item.key`/`Item.links` updates happen after the write call
  regardless. So a `check` that could not write reports exactly what a
  `--no-write check` reports. Safe to skip.

## What I built

Two things, and deliberately nothing else: the load's writes are reported by
every command that makes them, and a filesystem that refuses one is a warning
rather than a traceback. No command's default flipped, `--no-write` is
untouched, and nothing about *what* is written or *when* changed.

### 1. The notice reaches every writable load (`src/refdes/cli.py`)

`_load_write_notice()` is unchanged — its string is asserted verbatim in
`tests/test_load_time_writes.py`, and the two commands that already printed it
must keep printing exactly that. Two new helpers sit beside it:

- `_announce_load_writes(project, *, stream=None, name_blocked=True)` — the
  one call every `_load()` site makes, replacing the three-line inline pattern
  in `cmd_id` and `cmd_stub_tests`.
- `_load_blocked_notice(project)` — the refused-write half, for the commands
  that print no diagnostics of their own.

Wired at all 13 `_load()` call sites: `check`, `build`, `_run_stamp`
(`revision`/`release`), `index`, `ls`, `id`, `fetch`, `audit`, `stub-tests`,
`former-ids propose`, `history capture`, `history redact`,
`history migrate-seals`. Two per-stream/per-command parameters carry the real
decisions:

- **`index` prints to stderr.** Its stdout is JSON for the VS Code extension;
  a parenthetical in front of it breaks every consumer. Verified below.
- **`name_blocked=False` for `check`, `build`, `_run_stamp` and `index`** — the
  four that report project diagnostics, where `project.warn` already names each
  refused file. Saying it twice in one run is noise. `ls`, `audit`, `fetch`,
  `id`, `former-ids propose` and the `history` commands print only
  `project.errors`, so for them the summary line naming the refused files is
  the only channel, and it prints.

`check --help`'s description no longer claims "Nothing of the project's own is
written … The one exception is `.refdes/schema.json`". It now says the true
thing, which is what `docs/cli-reference.md:60-67` has said all along: this
command writes nothing of the project's own, *loading* writes keys,
composites and `.refdes/schema.json`, and `--no-write` skips those.

### 2. A refused write is a warning, not a crash

- **`revise.write_rewrites(rewrites, on_error=None)`** — with no hook (every
  explicit write command: `revise apply`, `calc-rewrite`, `keys adopt`,
  `keys restore`) the first `OSError` propagates exactly as before; there the
  user asked for the write, so a refusal is a failure. `write_rewrites_verified`
  — the load-time path — passes a hook that warns and keeps going, and returns
  the project-relative paths that were refused.
- **`schema_json.write_schema`** wraps its `makedirs` + write in
  `try/except OSError`, warns, records the refusal, and still returns the same
  staleness verdict (which is computed from mtimes *before* the write, so the
  trip-wire survives intact).
- **`model.LoadWrites`** gains `blocked: list[str]` — the paths this load tried
  to write and could not. `__bool__` deliberately ignores it, so
  `_load_write_notice()`'s existing behaviour and its asserted string are
  untouched.

**The part the task did not spell out, and the reason it matters.** Both
minting and expansion update the in-memory model after writing: `item.key =
new_key`, `item.links[...] = composite`. If the write is refused and the model
is updated anyway, the run resolves against keys that exist only in that
process — and the next step in the same load can then freeze
`REQ-001@<key>` into a file that *is* writable, naming a key its own file never
received. That is a composite resolving to nothing, which is run 2's F4
downstream-corruption case, created by the fix for BUG 2. So a refused write
means the write did not happen, full stop:

- `keys.mint_missing` drops the assignments whose file refused — no in-memory
  key, and they count into `plan.remaining`, so the existing "N items have no
  key yet" info line covers them.
- `links._drop_refused(plan, refused)` does the same for the four expansion
  steps (`expand_missing`, `expand_missing_checks`, `expand_missing_calc_refs`,
  `freeze_follows`) before anything is applied in memory or returned.

That is also what makes the tallies honest for free: each step returns only
what landed, so `loader.load_tree`'s `load_writes` counts need no change and
can never claim a write that did not happen. The net effect is the property the
task asked for stated the sharpest way available: **a blocked run behaves like
`--no-write`** — which is not an accident of this design but the rule
`keys.mint_missing`'s own docstring already states ("a key is only durable once
persisted").

## After: the same commands, the same project

`python .scratch/repro.py` (fresh copy per command, same keyless project as the
BEFORE section):

```
=== refdes check            exit 0   item file changed: YES
stdout: (minted 2 key(s) and rewrote 1 reference(s) while loading)
        … 2 items, 0 errors, 2 warnings
=== refdes --no-write check exit 0   item file changed: no
stdout: … 2 items, 0 errors, 2 warnings        <- no write line at all
=== refdes ls               exit 0   YES   notice on stdout, above the listing
=== refdes index --compact  exit 0   YES   notice on STDERR, stdout still parses
=== refdes audit            exit 0   YES   notice on stdout
=== refdes build            exit 0   YES   notice, then its own report
=== refdes former-ids propose exit 1 YES   notice, then "no baseline stamped"
=== refdes fetch            exit 0   YES   notice, then "0 citation(s) processed"
=== refdes revision rev-a   exit 0   YES   notice, then "revision 'rev-a' stamped"
=== refdes history capture REQ-001 exit 0 YES  notice, then "captured REQ-001"
=== refdes id               exit 0   YES   unchanged: it already said so
```

`stub-tests` could not be exercised on this project ("no type declares a
'verifies' link" — it exits before loading); it was already wired, and its
inline three lines became the one helper call.

`python .scratch/repro_ro.py whole check` / `items check`, which were tracebacks:

```
=== whole: refdes check   exit 0
WARNING .refdes/schema.json — could not write this file (read-only tree?); run with --no-write to silence this
WARNING items/r.yaml:1    — could not write this file (read-only tree?); run with --no-write to silence this
2 items, 0 errors, 4 warnings

=== items: refdes check   exit 0
WARNING items/r.yaml:1    — could not write this file (read-only tree?); run with --no-write to silence this
2 items, 0 errors, 3 warnings
```

Same verdict as `--no-write check` (`2 items, 0 errors`) plus the refusals,
which is the intended shape. `ls`/`index`/`audit`/`id`/`fetch` on the same two
trees also exit 0, naming the refused files in their own summary line:

```
(load could not write .refdes/schema.json, items/r.yaml -- read-only tree? run with --no-write to silence this)
```

and `index` on a read-only tree reports `"key": null` with the link still bare
`REQ-001` — the model matching the tree it could not change.

## What is still broken, on purpose

- **`build` and `revision` on a wholly read-only tree still crash** — in their
  *own* writes, not the load's: `render.render_site`'s `makedirs(_site)` and
  `lifecycle._save_baseline_file`'s `makedirs(.refdes)`. Both are commands whose
  entire purpose is to write; a traceback there is arguably right, and fixing
  the CLI's error handling for explicit writes is a different change. With
  `items/` read-only and the root writable, both now succeed. Noted for the
  report; not touched.
- **`ids.allocate`'s ledger write** (`refdes id` on a tree where the ledger is
  unwritable) is another explicit-write crash site, same category, same reason
  for leaving it.
- The task's "better fix" — `check`/`ls`/`index`/`audit` defaulting to
  `write=False` — is not done, as instructed.

## Tests

`tests/test_load_time_writes.py`, 10 new test functions — 29 cases once the
first three are parametrized, so that file collects 44 where it collected 15
before:

- `test_every_writable_command_announces_what_its_load_wrote` — parametrized
  over `check`, `ls`, `index --compact`, `audit`, `build`, `revision rev-a`,
  `fetch`, `history capture`: the notice appears, *and* the item file really
  changed, so the notice cannot drift away from the writes it reports.
- `test_the_steady_state_still_announces_nothing` — same eight commands, tree
  primed with `check` first: no write line on the second run. (Primed with
  `check` rather than with the command itself, so `revision rev-a` twice is not
  what the test is accidentally about.)
- `test_no_write_still_announces_no_writes_it_did_not_make` — six commands under
  `--no-write`: no notice, no refusal line, file byte-identical.
- `test_index_announces_on_stderr_and_keeps_its_stdout_json` — `json.loads` on
  stdout still works.
- `test_check_survives_a_read_only_tree` / `..._a_read_only_items_dir` — the two
  BUG 2 sites, together and separately: exit 0, no `Traceback`, the right files
  named, the item file untouched, and `check`'s verdict unchanged.
- `test_check_survives_a_tree_that_cannot_create_refdes` — the refused
  `os.makedirs(".refdes")` half, POSIX-only by necessity; see the next section.
- `test_a_refused_mint_leaves_the_run_reading_like_no_write` — the corruption
  guard above, asserted through `index`: `key: null` and the target still bare.
- `test_commands_without_diagnostics_still_name_the_refusal` — `ls` gets the
  summary line, `check` does not, and says it exactly once.
- `test_check_does_not_call_a_refused_schema_refresh_refreshed` — the trip-wire
  says "not refreshed (the write was refused)". (First draft used a bare
  `os.utime()` to make the file stale and could land on the same clock tick as
  the write it must postdate; it now offsets by an hour, so it cannot.)
- `test_an_explicit_write_still_raises_on_a_read_only_tree` — `write_rewrites`
  without the hook still propagates `PermissionError`.

One existing test changed: `tests/test_cli_load_errors.py::
test_clean_project_index_and_ls_unchanged` asserted `index` leaves stderr
empty. Its fixture's item has no key, so that assertion *was* the BUG 1
silence; it now asserts the notice on stderr, and that the steady-state `ls`
after it still prints nothing.

## CI: the read-only test was asserting a POSIX-only mechanism

`ubuntu-latest` and `py3.13` passed. `windows-latest` failed one test —
`test_check_survives_a_read_only_tree` — and the failure output is the whole
story: `items/r.yaml:1 — could not write this file` was right there, but
`.refdes/schema.json` was missing from the output entirely.

Two different filesystem operations sit in `write_schema`'s `try`, and the two
platforms do not refuse them the same way:

| refused operation | POSIX `0o555` on the dir | Windows read-only dir |
| --- | --- | --- |
| `os.makedirs(".refdes")` — *create* an entry | EACCES | **allowed** |
| `open(existing, "w")` — *overwrite* a file | EACCES on the file's own bits | EACCES (read-only attribute) |

The test's tree had no `.refdes/` at all — `_id_project` never makes one, and
`schema.json` is gitignored — so the only way the schema write could fail was
the *first* row, and Windows does not implement that row. `os.makedirs`
succeeded, the write succeeded, nothing was refused. The item file refused on
every platform because it is the second row, which is also why
`test_check_survives_a_read_only_items_dir` passed on the same run.

So the premise, not the assertion, was platform-specific. Split rather than
weakened:

- **`test_check_survives_a_read_only_tree`** now creates `.refdes/schema.json`
  first, so both refusals come from the second row — overwriting an existing
  read-only file — which both platforms honour. It still asserts *both* files
  named in one run, which is the case it exists for.
- **`test_check_survives_a_tree_that_cannot_create_refdes`** keeps the first
  row, `skipif(os.name == "nt", reason="needs POSIX directory permission bits:
  Windows' read-only attribute on a directory does not stop new entries being
  created inside it, so a refused os.makedirs cannot be produced that way")`.
  Reproducing that on Windows needs an ACL (`icacls /deny`), not `chmod`.

**Not taken on trust.** A Linux pass says nothing about Windows, so the
mechanism was isolated directly (`.scratch/which_bit.py`): every *directory* at
`0o755`, only *files* at `0o444`. Both refusals still fire and `schema.json`
keeps its `{}` placeholder — so the refusal comes from the file's own bit, not
the directory's. And `write_schema` and `write_rewrites` both go through the
same `textio.write_text` → plain `open(path, "w")` (`textio.py:271`), the exact
call the Windows runner was observed refusing for `items/r.yaml`. Same function,
same condition, already witnessed on that runner.

Nothing in `src/` changed for this — the product code caught both operations
from the start. Only the test's setup was asserting a permission Windows has no
notion of.

### ...and the second Windows failure, which was a real product bug

The split worked: the re-run shows the schema refusal firing on Windows —
`WARNING .refdes\schema.json — could not write this file`. The test still
failed, on the *separator*:

```
E  AssertionError: assert ('.refdes/schema.json' in
   'WARNING .refdes\schema.json — could not write this file ...')
```

So my first diagnosis was only half right, and the fix was not "the test needed
a pre-existing file" — that was necessary but not sufficient, and I stated it as
the whole story. The remaining half is a defect in what I wrote, visible only on
Windows:

`SCHEMA_REL_PATH` is `os.path.join(".refdes", "schema.json")`, which is
`.refdes\schema.json` on Windows, and I passed it straight to `project.warn` and
into `load_writes.blocked`. But this codebase normalises project-relative paths
in anything a person reads — `parse.rel_source`, the `revise` report
(`cli.py:435`), `keys.py:430`, `history.py:870`, ~20 `.replace("\\", "/")` sites
— and `revise._refuse_unwritable` appends `rewrite.rel`, and the refused set is
matched against `item.source_file`, both already `/`-form. So `blocked` was a
list with one foreign-spelled entry, and one `refdes check` on Windows printed
the same file two ways: `.refdes\schema.json` in my warning and
`.refdes/schema.json` in `check`'s own trip-wire literal (`cli.py:238-254`),
which is also how `--help` and the docs name it. A path copied out of the warning
matched nothing.

Fixed in the product, not the test — the test's forward-slash assertion was
correct all along and is now the guard:

- `schema_json.SCHEMA_REL_DISPLAY = ".refdes/schema.json"` — the prose spelling,
  with `SCHEMA_REL_PATH` kept for the filesystem. The `except OSError` branch
  records and warns in display form.
- `cli.py`'s trip-wire compares against `SCHEMA_REL_DISPLAY`.
- The test now also asserts `".refdes\\schema.json" not in out`, so the
  convention is pinned rather than re-derived next time it breaks.

The lesson I got wrong once already: a cross-platform failure in a test I wrote
is evidence about my code, and "the mechanism is now portable" was a conclusion I
reached from a table rather than from the re-run's output. The re-run is the only
test that says whether Windows agrees.

## Gates

- `pytest tests/` — **2793 passed, 2 skipped in 193.99s** on the final tree
  (2792 before the Windows split; the separator fix added assertions, not a
  test). Clean. The two skips are environment-conditional
  markers (`os.name != "nt"`, "needs a case-insensitive filesystem",
  `needs_install`) in `test_serve_upload.py`, `test_citations.py` and
  `test_version_flag.py` — none in a file this change touches.
- CI on #113 commit 1 (`e6fa618`): `ubuntu-latest` pass, `py3.13` pass,
  `windows-latest` **fail** — the permission-mechanism test above.
- CI on commit 2 (`ec72d58`): `ubuntu-latest` pass, `py3.13` pass,
  `windows-latest` **fail** again — different cause, the separator bug, and the
  one thing the second failure proved is that commit 2's split *did* work. A
  local Linux pass is not evidence about Windows; that assumption produced the
  first failure, and over-confidence in a mechanism table produced the second.
- Commit 3 is the separator fix. Third run on all three platforms pending; I am
  not calling this done until `windows-latest` says so.
- `ruff check src/refdes/cli.py src/refdes/schema_json.py src/refdes/revise.py
  --select I,F` — 2 findings, both `I001` import-block formatting in
  `revise.py:28` and `schema_json.py:16`. Both are **pre-existing**: piping
  `git show HEAD:<file>` through the same ruff reports the same one error in
  each, and my diff touches no import line in either file (`git diff -U0 | grep
  import` is empty for both). `AGENTS.md` says as much — `ruff check .` has ~99
  pre-existing findings and is not a completion gate. `--select F,E9` over every
  file I touched, `src` and `tests` both: clean. `--select I` over `cli.py`,
  `keys.py`, `model.py` and both test files: clean.
