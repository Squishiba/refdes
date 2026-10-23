# Upgrading from 0.5.0

The release after 0.5.0 ships `hardware@3` and lands the vocabulary review's
renames. It is the largest breaking surface since the standard library
existed. This page is evidence-based: the ordered steps below were run
against a real v0.5.0-era project (built with `refdes` 0.5.0 —
`refdes init`, a `refdes.yaml` pinned at `hardware@2`, requirements with
`text:`, a test with `method:`, a decision with a colon-unit `calc` block,
a citation with `url:`/`vendor:`, a sealed append-only log entry, and a
baseline stamped by the old `refdes revision`). Every quoted message is
that run's verbatim output.

## Before you upgrade

- **Commit.** The upgrade rewrites item files; `git restore` is the
  rollback (there is no downgrade command — the migration chain is
  one-way).
- **Copy `.refdes/`** (`cp -a .refdes .refdes.pre-upgrade`). It is
  gitignored, and the seals, baselines, citation lockfile, ID ledger and
  surrogate-key state all live there.
- **Expect refusals on the way.** The rewriting commands (`standard
  upgrade`, `calc-rewrite`) refuse to run while the build is red —
  deliberately, "so a hash change caused by this rename can't hide behind
  one already-broken build". The steps below are ordered so each fix turns
  the build greener.

## Step by step

### 1. `refdes check` stops the project at the door

A project that still carries `refdes.yaml` no longer loads:

```
configuration error: refdes.yaml is retired. Split it into the two files
it became: move every project setting (site:, id:, boards:, workspaces:,
units:, on_change:, standard:, equations:, imports:, and the process
settings like sigfigs: and release_gate:) into refdes-project.yaml, which
is now the project marker, and move any schema overlay (types:,
link_types:, sets:) into refdes-schema.yaml, which is optional -- omit it
entirely if the project declares no types of its own. Then delete
refdes.yaml: nothing is read from it any more, so a key left behind there
is a setting that silently stops applying.
```

Exit 2. **Fix:** move every setting into `refdes-project.yaml` (for the
probe project this was a rename), move any `types:`/`link_types:`/
`field_sets:` into `refdes-schema.yaml` — renaming `field_sets:` to
`sets:` while you are there (the old key is a hard error naming the
rename) — then remove `refdes.yaml`. A `types:` left in
`refdes-project.yaml` is an error naming the file it belongs in.

### 2. `refdes check` reports the renames

With the marker in place the first writable load mints surrogate keys for
every item (informational: `minted 8 key(s) and rewrote 8 reference(s)
while loading`) and the v0.5.0 spellings surface as build errors:

```
ERROR   items/components/pwr.yaml:7 [CMP-PWR-001] — datasheets[0]: citation field url: was renamed to path: -- rename it (refdes standard upgrade does this for hardware@2 -> @3 content)
ERROR   items/decisions/dec-pwr-001-regulator.md:30 [DEC-PWR-001] — calc 'P_diss': the 'name : unit = expression' spelling was retired -- write `P_diss           = V_out * I_load * (1/eff - 1) | W`; run 'refdes calc-rewrite' to fix a whole project
ERROR   <project> — the citation lockfile still uses the pre-rename key 'vendored:' for: http://127.0.0.1:8765/ds-tps62913.pdf -- the citation field vendor: was renamed to keep_copy: and its lockfile key to kept_copy:; rename the key in .refdes/citations.yaml or re-pin with 'refdes fetch --update'
```

plus warnings for the stranded `.refdes/vendor/` directory (renamed to
`.refdes/copies/`), the refreshed `.refdes/schema.json`, and — new in this
release — a status/link disagreement check:

```
WARNING items/components/pwr.yaml:21 [CMP-PWR-002] — status is 'selected' but nothing selects it -- no item declares selects: pointing at this one. Author selects: on the item that makes it so, or move this item off 'selected'.
```

### 3. Fix the citation renames by hand

The `url:` error names `standard upgrade` as the rewriter, but the upgrade
refuses while the build is red — and this error is what keeps it red. The
citation field renames are one-key edits, so do them first:

- in each item: `url:` → `path:` (a remote citation keeps its full
  `http(s)://` URL — the field is dispatched on scheme), `vendor:` →
  `keep_copy:`;
- in `.refdes/citations.yaml`: `vendored:` → `kept_copy:`, or re-pin with
  `refdes fetch --update`;
- `mv .refdes/vendor .refdes/copies` (nothing reads the old name).

### 4. `refdes calc-rewrite`

The colon-unit calc spelling is retired; the command rewrites a whole
project in one transactional pass and compares every value before and
after:

```
rewrote 2 calc line(s) in 1 file(s):
  items/decisions/dec-pwr-001-regulator.md:30  P_diss  : W      = V_out * I_load * (1/eff - 1) -> P_diss           = V_out * I_load * (1/eff - 1) | W
  items/decisions/dec-pwr-001-regulator.md:32  P_dens  : W/in^2 = P_diss / A_board -> P_dens           = P_diss / A_board | W/in^2
```

A retired line inside a *sealed* append-only entry is a warning, not an
error — the build refuses to break history it cannot edit.

### 5. `refdes standard upgrade --to 3`

With the build clean, the v2→v3 step runs. Preview it with `--dry-run`
(first) — it prints the per-file plan, the `standard.version:` bump and
the baselines/seals that would be carried forward, and writes nothing.
The real run:

```
v2 -> v3:
changed 6 file(s):
  items/bounds/thermal.yaml
  items/components/pwr.yaml
  items/decisions/dec-pwr-001-regulator.md
  items/log/2026-03.yaml
  items/requirements/power.yaml
  items/tests/pwr.yaml
baselines carried forward: pre-upgrade-baseline

upgraded to v3.
```

In the files: `requirement`/`bound` `text:` → `body:`, `test` `method:` →
`body:`, `component` `datasheets:` → `citations:`, `equivalent:` →
`drop_in:`, and `type: decision` → `type: log` with `title:` → `summary:`
and `records:` → `follows:` (the merged `log`). `standard.version:` is
bumped to 3. The step is one refuse-and-roll-back transaction; a
`text:`/`body:` collision is refused up front (see the table).

### 6. `refdes check` after the upgrade — the seal follow-up

The migrated append-only log entry's content hash moved (the merged `log`
counts `date:` in its hash now), so its old seal no longer matches:

```
WARNING items/log/2026-03.yaml:6 [LOG-PWR-001] — LOG-PWR-001: edited while uncaptured -- the current content no longer matches the hash d141e66be61d4851 recorded in .refdes/log-seal.yaml, and nothing in .refdes/history/ holds a snapshot of this entry, so the edit leaves no trace. Run `refdes history capture LOG-PWR-001` to record the current text; an edit after that is reported as edited after captured.
```

Run the command it names (`refdes history capture LOG-PWR-001` →
`captured LOG-PWR-001: manual capture`). It is a warning, not an error —
the build was never red because of it. Migrated `follows:` edges are
bare in the upgrade's own write; the first *writable* load anchors each
to its target's current thread tip, so the file reads
`follows: [DEC-PWR-001@xd6hk1vhg05]` afterwards. If you do not want those
edges maintained, delete the `follows:` lines before your first writable
command.

### 7. Clear the new strictness warnings, then stamp

The `selected`-with-no-`selects:` warning is the status/link-disagreement
check: add the `selects:` link on the item that makes it so, or move the
item off `selected` (the probe's second-source part became
`status: candidate`). Then:

- `refdes fetch --update --path <url>` re-pins citations and records the
  page count, which is what the new citation page check reads ("pages
  unchecked" in `refdes audit` names the command);
- `refdes build` → `site written to …`, exit 0;
- `refdes revision post-upgrade` stamps a fresh baseline (see below);
- `refdes audit` → `Since last revision (post-upgrade, …): changed 0 …
  (8 unchanged)`.

## Every breaking change, its symptom, its fix

| Change | What you see | Fix |
|---|---|---|
| `refdes.yaml` retired; config is two files | `configuration error: refdes.yaml is retired…`, exit 2, on every command | Split by top-level key: settings → `refdes-project.yaml` (the marker), `types:`/`link_types:`/`sets:` → `refdes-schema.yaml`; remove the old file (`refdes revise` can't do config layout) |
| `field_sets:` → `sets:` | load error naming the rename | Rename the key in `refdes-schema.yaml`; entries unchanged |
| `url:` → `path:` in citations | `citation field url: was renamed to path:` | Rename in each item (keep the `http(s)://` value); `refdes standard upgrade --to 3` rewrites it with the build green |
| `vendor:` → `keep_copy:`; `vendored:` → `kept_copy:` | lockfile error naming the keys; `.refdes/vendor/` warning | Rename in items and `.refdes/citations.yaml`, `mv .refdes/vendor .refdes/copies`, or `refdes fetch --update`; a project configuring the renamed release-gate rule must rename `missing_vendored_copies:` → `missing_kept_copies:` |
| Citation `page:` is checked | `page: 0`/`eight` refused at load; a page past the end is a warning naming the citer (error under `build --require-citations`); lockfiles without a count report `pages unchecked` | Write positive integers; `refdes fetch --update` records the count (needs the `refdes[pdf]` extra) |
| Colon-unit calc retired | `the 'name : unit = expression' spelling was retired`, per line | `refdes calc-rewrite` (sealed entries warn only) |
| `text:`/`method:` fold into `body:` (requirement/bound `text:`, test `method:`) | under a v3 pin: `text:` is no longer a field of the type — build error | `refdes standard upgrade --to 3` rewrites; an item that already has body prose of its own is refused by name — merge the two texts, re-run |
| `decision` retired into `log` | under a v3 pin: `type: decision` is not a type; `design-debate` preset load error | `refdes standard upgrade --to 3` (title→summary, records→follows, DEC ids kept via `legacy_prefixes`); a debate project migrates to plain logs or declares the four types itself |
| `equivalent` → `drop_in` | under a v3 pin: unknown-verb error naming `drop_in` (escalated for this verb) | The upgrade rewrites it |
| `equivalent`→`drop_in`, `records`→`follows` capture side effect | first writable load after the upgrade prints `captured …` lines; migrated `follows:` edges get anchored to thread tips | Expected — history is being recorded; delete the `follows:` lines first if you want the edges inert |
| `on_change` mode `log` → `timeline` | with a v3 pin (or no pin): load error naming `timeline`, per spelling (config, schema annotations, item overrides) | Rename by hand — `refdes rename` renames keys, not values; v1/@2 pins keep `log` |
| project/item setting `history:` → `on_change:` | hard error naming `on_change:` | Rename in `refdes-project.yaml` and item front matter (`refdes revise` can't) |
| Duplicate mapping key in an item file | `duplicate key 'id' in one mapping (lines 14 and 17) …` — put the `- ` back on its own line, the fragment remedy | One error per repeated key; the file is not rewritten |
| Duplicate key in the config files | `configuration error: refdes-project.yaml: duplicate key 'site' … (lines 1 and 14)` | Delete/merge the two blocks |
| Scalar for a list field | `field 'tags' is a list field, but it was given a string …` | Write a real list — the value is never split on commas |
| Confident field-name typo | `unknown field 'partnum' on component -- did you mean the field 'part_number'? …` now exits 1 | Fix the spelling and check the value landed |
| Link verb named like a reserved key | load-time configuration error (exit 2) naming verb and key | Rename the verb in `refdes-schema.yaml` |
| `check --refresh` unreachable pinned citation | `ERROR … could not refresh https://… -- upstream drift was NOT verified for this citation …`, exit 1 | Accept it, or pass the new `--allow-unreachable` (unverified sources become warnings — you give up the drift guarantee) |
| hardware@3 ships; `init` pins it | new projects start at `version: 3` (0.5.0's init wrote `version: 2`) | Nothing to do for pinned projects — v1/@2 bytes are frozen; new projects get the v3 vocabulary from the start |

## What is safe to ignore

- The `minted N key(s) and rewrote N reference(s) while loading` line —
  surrogate-key bookkeeping, printed on writable loads.
- `.refdes/schema.json … refreshed` — editor-completion cache refresh.
- The coverage warnings (`1 item(s) with no coverage`, `satisfied but not
  verified`) if you had them on 0.5.0 — unchanged.
- `refdes audit`'s "Schema fields not tracked as 'invalidate'" section and
  its `timeline` spellings — a report, not a finding.
- Migrated `follows:` anchors and captured events — the thread machinery
  doing its job (delete the lines first if you want them inert).

## Seals and baselines after the upgrade

- **Baselines**: `standard upgrade` carries stamped baselines forward
  (`baselines carried forward: pre-upgrade-baseline`) so the rename is not
  reported as a content change. After the v3 hash-definition changes the
  migrated entries are then reported, honestly, as
  `uncomparable 5 … older-format entries whose stored hash can't be
  checked against the current definition -- not counted as changed;
  review the content, then stamp a new baseline` — stamp one
  (`refdes revision post-upgrade`) and the diff reads `changed 0` from
  then on.
- **Append-only seals**: a migrated sealed log entry's hash moves with
  the merge (its `date:` now feeds the hash); the old seal reports
  `edited while uncaptured` as a **warning** and `refdes audit` lists it
  under "Append-only entries edited after sealing" as
  `(legacy seal: recorded hash only; original content was not captured)`.
  Fix: `refdes history capture <id>` — it names the command itself.

## Rollback

There is no downgrade command; the v2→v3 migration chain is one-way
(the `decision` merge in particular is not invertible). Roll back by
restoring what the upgrade rewrote: `git restore` the item files and
config (the composite `ID@key` link spellings and folded `body:` fields
leave with them), and restore `.refdes/` from the pre-upgrade copy — the
minted keys, captured events and re-stamped baselines live only there,
outside version control.
