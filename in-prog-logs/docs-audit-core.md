# Docs accuracy audit — core pages

Task: audit `docs/getting-started.md`, `docs/authoring.md`, `docs/concepts.md`,
`docs/ids.md`, `docs/checks.md`, `docs/coverage.md` one page at a time. Every
concrete claim is verified by running the real tool in a throwaway project
under `.scratch/audit/`, never from memory. Only proven discrepancies are
edited, and always with the smallest possible edit. No source or test file is
touched; any source bug found is recorded here and in the PR body, not fixed.

## How the verification was run

The venv at `C:\Users\Jared\Refdes\.venv` has `refdes` installed editable
against the **main checkout**, not this worktree — so a bare `python -c "import
refdes"` would have audited the wrong code. `.scratch/r.ps1` therefore pins
`PYTHONPATH` to this worktree's `src/` before invoking
`refdes.cli:main`, and every run below is confirmed to resolve
`refdes/__init__.py` under `.ao/data/worktrees/refdes/refdes-178/src`.

`.scratch/check_links.py` validates every relative link and anchor on the six
pages: it resolves the target file, and for `.md` targets it slugifies the
destination's headings the way GitHub does (lowercase, drop punctuation
*except* hyphen and underscore, spaces to hyphens). That last detail matters —
see the `blocked_by` finding under `docs/coverage.md`.

---

## docs/getting-started.md

Scratch project: `.scratch/audit/my-board` (plus throwaway `probe2`“`probe4`
for single-claim probes).

### Claims checked — all verified correct, left as-is

- `refdes init` writes exactly the YAML shown (12 lines, `site`/`standard`/
  `id` only, no `types:`). Compared byte-for-byte against
  `.scratch/audit/my-board/refdes-project.yaml`. `scaffold.py:104-111` is the
  writer. "That's the whole file" holds.
- `version: 3` is the resolved newest bundled standard, never the literal
  `"latest"` — `standards.latest_version()` returned 3 and `init` printed
  `standard: hardware@3`; the `v1/ v2/ v3/` directories under
  `src/refdes/standards/hardware/` confirm 3 is newest.
- `init` writes `.vscode/settings.json` binding `items/**/*.yaml` to
  `.refdes/schema.json`. Read the generated file: exactly that mapping.
- `refdes init --standard none` exists and writes `standard: none`
  (`.scratch/audit/probe4/refdes-project.yaml`).
- The `./.venv/Scripts/python.exe -m refdes.cli` fallback works —
  `python -m refdes.cli --help` prints the top-level usage. `cli.py:1854` has
  the `__main__` guard, and `pyproject.toml` declares the `refdes` console
  script, so both invocation styles in the Install section are real.
- A project is "any folder containing `refdes-project.yaml`" and the tool
  finds it from a subdirectory — `schema.find_config()` walks up from the
  start directory looking for the marker.
- `items/` is scanned recursively — the scratch project keeps items in five
  different one-level-deep folders (`requirements/`, `bounds/`,
  `decisions/`, `tests/`, `log/`) and the build reports all 6 items.
- Step 2's `refdes id` output, modulo the line number fixed below: the
  format `allocated <ID>  (<file>:<line>) <body>` and the trailing
  `allocated 2 id(s)` are exactly right, and IDs really are written into the
  file.
- Step 3: `bound` is a real type with a required `limit` field, and
  `constraint` was its `hardware@1` name (`refdes new bound` prints
  `limit:  # required -- limit`; the rename is `v2/migration.yaml:41`).
- Step 4: every field used exists — `refdes new decision` lists `title`,
  `status` (with `accepted` among the choices), `date`, `options`, `checks`,
  `satisfies` (targets `requirement, bound`) and `constrained_by` (target
  `bound`).
- Step 4's three bullet claims, each reproduced:
  - "`V * A` yields watts; `V + A` would be a build error" — a probe decision
    with `bad = V_out + I_load` fails the build with
    `calc 'bad': cannot add V and A — the units do not match`.
  - "`P_diss ... | W` is a unit assertion ... the build fails at that line" —
    a probe with `| A` on a `V * I` expression fails at that line with
    `declared as A but the expression evaluates to AÂ·V`.
  - "`checks:` compares `P_dens` against `BND-THM-001`'s limit" — the
    documented build output reproduces exactly.
- Step 5's sample output is exact, including the `0.2366 W/inÂ²` figure, the
  `4 items, 1 errors, 1 warnings` counts, the `--keep-going` hint and the
  exit-1 status. Verified with the streams captured separately via
  `Start-Process` redirect: the `ERROR` line *and* the
  `build completed with errors` line are on **stderr**; the `WARNING`, the
  counts and `site written to` are on **stdout** — so the page's note that the
  two streams interleave differently than shown is accurate, and the shown
  ordering is explicitly not claimed to be literal. Left as-is.
- Step 6: `test` has `verifies` (targets `requirement, bound`), `title` and
  `status: passing`. After adding the test, `_site/coverage.html` shows
  `REQ-PWR-001` as **verified** and `REQ-PWR-002` as **satisfied** but not
  verified, and the build's warning changes to
  `1 requirement(s) satisfied but not verified` — exactly as the page says.
- Step 7: `log` has required `date` and `summary`, plus `author`, `addresses`
  and `amends`. The append-only claim is real — editing the sealed entry
  fails the build with `LOG-001 is append-only and has been modified since it
  was sealed. Append a new entry with \`amends: [LOG-001]\` instead, or run
  with --reseal if the edit is deliberate.`

### Discrepancies fixed (3)

1. **`items/` is not created by `refdes init`.** The step-1 tree listing
   showed `items/` as part of what the command produces. `scaffold.init()`
   creates only `refdes-project.yaml` and `.vscode/settings.json`
   (`scaffold.py:109-119`); after running `init` in an empty directory,
   `Test-Path items` is `False`. Added one clause to the sentence introducing
   the tree saying `items/` is not created for you.
2. **`refdes id` line number.** The sample output claimed
   `items/requirements/power.yaml:12` for `REQ-PWR-002`; the real output is
   `:13`, reproducibly (two clean runs). Allocating the first item inserts
   *two* lines — `id:` and the surrogate `key:` — which shifts the second
   item down. Fixed the number only; the rest of the sample is accurate.
3. **"It was called `constraint` up to `hardware@2`."** The rename happened at
   `hardware@2`, not after it: `v1/base.yaml:55` defines `constraint`,
   `v2/base.yaml:100` defines `bound`, and `v2/migration.yaml:41` is the
   `constraint: bound` mapping. Corrected to `in \`hardware@1\``.

### Left unverifiable / not changed

- Nothing on this page was left unverified. The one judgment call is step 5's
  sample block, whose line ordering is not literal; the page already says so
  two lines below it, and the underlying stream split is correct, so editing
  it would be style, not accuracy.

---

## docs/authoring.md

Scratch projects: `probe5` (list files), `probe6` (sections in both formats),
`probe7`/`probe7b` (section error paths), `probe8` (unknown field), `probe9`
(later `defaults:`), `probe10` (multi-item markdown), `probe11`
(`enforce_grouping:`), `probe12`/`probe13` (schema overlay), `probe14`/`probe15`
(`limit` and `citations` enforcement).

### Claims checked — verified correct, left as-is

- `defaults:` merges into every entry and an entry's own keys win — read back
  out of `_site/items.json`: an entry with `status: draft` keeps `draft` while
  inheriting `owner`/`tags`.
- `prefix:` is consumed by the allocator and never stored as a field — the
  emitted `fields` map for an item declared with `prefix: REQ-MECH` contains
  only `owner`, `tags`, `status` (and `source` where given). No `prefix` key.
- An entry may omit `id:` and `refdes id` fills it in; per-item `prefix:` beats
  `defaults.prefix` and works in list files exactly as documented.
- A list-file `body:` supports `calc` blocks and `{{value}}` references — a
  `body:` containing both built clean.
- Markdown files: front-matter then body, filename irrelevant, several items
  per file, an optional *leading* `defaults:` block applying to every item that
  follows. `refdes id` inserted the second id **at its own fence** (line 14) in
  a two-item file, as claimed.
- The `defaults:`-not-at-the-top rule is real: a `defaults:` block in the
  second position is an error — `'defaults:' only applies as the very first
  block in a file -- a later one here doesn't take effect.`
- `section:` works in **both** formats with the same spelling, and items under
  a section need no `type:` of their own — a list file with two sections built
  3 items/0 errors, the markdown equivalent built 2 items/0 errors.
- Both section error messages reproduce **verbatim**, including the line
  numbers: `items/main-io/interfaces.yaml:6 — item declares type 'decision' but
  sits inside a 'section: requirement' block (opened at line 2) …` and
  `'section: bound' conflicts with this file's own 'defaults: {type:
  requirement}' …`.
- "There is no `enforce_grouping:` setting" — putting it in
  `refdes-project.yaml` gives `configuration error: refdes-project.yaml:
  unknown setting 'enforce_grouping'.`, exit 2.
- An unknown field is a **warning**, the value is kept, and the suggestion is
  offered: `unknown field 'sorce' on requirement. Did you mean 'source'?`, and
  `sorce` is still present in the emitted `fields`.
- The documented custom-type override in `refdes-schema.yaml` is accepted
  verbatim (`status` enum with `choices: [draft, active, retired]`, `owner`
  person with `on_change: log`, required `body`), and `refdes new requirement`
  then scaffolds against it.
- Field-type enforcement is exactly the three types named: a non-quantity
  `limit` errors (`could not read limit 'some vague prose'`) and a citation
  with no `path` errors (`citations[0]: each citation needs a 'path'`).
- The `on_change:` table matches the resolved schema field-for-field:
  `source`/`note` are `log`, `rationale`/`body` are `invalidate`; `body` is a
  reserved key and appears in no type's `fields`.
- `source` and `note` really do come from the `provenance` set, and
  `decision.rationale` is required when `status: rejected`.
- `prefix`/`board` are overridable reserved keys (`parse.py:37`
  `OVERRIDABLE = {"prefix", "board", "workspace"}`).
- "Everything under `items/` is scanned recursively", "folders carry no
  meaning", the 11-character key shape, the `verified_by` inverse, and the
  board-token advice all check out.

### Discrepancies fixed (4)

1. **Title precedence was in the wrong order.** The page listed
   `title` → `text` → `body` → `summary` → `name` → `id`. The engine tries
   `("title", "text", "summary", "name")` first and only then falls back to
   `body` (`model.py`, `Item.title`). Proved it on a real item rather than by
   reading: `LOG-001` in the getting-started project has **both** a `summary`
   and a non-empty `body`, and its rendered title is the summary — under the
   documented order it would have been the body's first sentence. Reordered
   `body` to sit after `name`.
2. **The list-file example did not build.** Its `defaults:` block sets
   `status: accepted` on a `requirement`, whose `status` choices are
   `[draft, active, retired]`. Reproduced: two errors, exit 1. Changed the one
   word to `active`; the following entry's `status: draft # overrides the
   default` still demonstrates the override correctly.
3. **Reserved-keys table was incomplete.** `parse.py` reserves
   `{id, type, history, body, former_ids, key}` plus the overridable
   `{prefix, board, workspace}`; the table listed six keys and was missing
   `workspace`, `key` and `former_ids`. Added three rows.
4. **"the other five starter types".** `hardware@3` ships **seven** types
   (`requirement`, `bound`, `decision`, `test`, `log`, `component`, `group`) —
   counted by dumping the resolved project's `types`, not from memory. Changed
   to "the other six".
5. **Removed a false parenthetical.** The page claimed the starter schema's
   `log` type "still has its own hand-typed `board` field". No type in
   `hardware@3` declares `board`, and no `sets:` block mentions it — confirmed
   two ways: iterating `project.types` for a `board` field (False for all
   seven) and grepping `v1`/`v2`/`v3` `base.yaml`, where the only `board`
   occurrence anywhere is the word inside `component.refdes`'s `doc:` string.
   It never existed in any bundled version, so the parenthetical was deleted
   rather than reworded.

### Left unverifiable / not changed

- The `body:` example under "Bodies in list files" shows only an `items:` list
  with a `LOG-005` entry and no `defaults:`/`type:`, so taken literally it
  would not load. It is introduced as illustrating `body:`, and every other
  example on the page is a complete file, so I read this as a deliberate
  excerpt rather than a claim that the snippet is complete. Not changed.
- "Item types … are declared in `refdes-schema.yaml`" (concepts.md) and the
  `text:` fallback note are simplifications rather than falsehoods — a custom
  type genuinely is declared there. Left alone; correcting them would be prose
  rewriting, not an accuracy fix.

---

## docs/concepts.md

Scratch projects: `probe16` (tolerances), `probe17` (content hash), `probe18`
(all five coverage stages), `probe19` (calc DSL restrictions).

### Claims checked — verified correct, left as-is

- `verifies` ↔ `verified_by` are the two ends of one edge — read the
  `inverse` of every link type at runtime; `verifies.inverse == 'verified_by'`,
  and `_site/items.json` really shows `REQ-PWR-001` with
  `backlinks.verified_by == ["TST-PWR-001"]`.
- `3.3 V * 1.2 A` is 3.96 W and `3.3 V + 1.2 A` is a build error — both
  reproduced (the latter under getting-started).
- `12 V ± 5%` carries 11.4 V to 12.6 V — the evaluated `bounds` field is
  literally `11.4 V … 12.6 V`.
- All **five** coverage stages, with the documented sources, reproduced in one
  project: `open` (nothing references), `addressed` (a log entry `addresses`),
  `claimed` (a `proposed` decision `satisfies` — `satisfying_statuses:` is a
  real per-type key, `decision: ['accepted']`, `component: ['selected']`),
  `satisfied` (an `accepted` decision), `verified` (a `passing` test).
- Log entries are append-only and enforced by the build (reproduced).
- The content hash covers `invalidate` fields only — measured: changing
  `owner` (a `log` field) left the hash at `dae31d0c4ec61164`; changing
  `rationale` (an `invalidate` field) moved it to `69fe43b25c1a2c8d`.
- `log` and `ignore` are indistinguishable today — consistent with
  `model.py:20` ("reserved for a future history layer -- behaves as ignore
  today") and with the table's own "no" in the baseline-diff column.
- The calc DSL has no imports, conditionals or attribute access — a probe
  using all three produced `expected an assignment of the form 'name =
  expression'`, `only plain function calls are allowed`, and `could not parse
  expression '3 if x else 4'`.
- `refdes promote` is not a command — it is absent from `refdes --help`'s
  subcommand list, as the page says ("not yet built").
- A markdown file holding several items with a leading `defaults:` block
  (reproduced under authoring.md).

### Discrepancies fixed (1)

1. **The item-type enumeration omitted `group`.** The page opens "Everything is
   an **item**: a requirement, a bound, a decision, a component, a test, a log
   entry." `hardware@3` ships a seventh type, `group` (prefix `GRP`, added by
   `changelog.d/hardware-v3-group-type.added.md`). Added it to the list.

### Source bug found, not fixed (reported, not edited)

- None from this page.

### Left unverifiable / not changed

- "No server. The output is static HTML that works with JavaScript disabled."
  There *is* a `refdes serve` command, but the claim is about the output
  having no server-side component, which is true. Left as-is rather than
  rewording a deliberate design statement.

---

## docs/ids.md

Scratch projects: `probe20`–`probe30`.

### Claims checked — verified correct, left as-is

- `refdes id` writes the id back preserving comments and indentation, and
  `--dry-run` exists (`usage: refdes id [-h] [--dry-run]`, help text "show
  without writing") and prints `would allocate …` / `would allocate 1 id(s)`.
- A quoted numeric hint is expanded once, in the file, the moment a prefix is
  available: `id: "042"` + `prefix: CAN` became `id: CAN-042` on disk, and the
  project then built clean.
- "The value must be quoted, always" — `id: 42` is refused with an error whose
  message spells out the octal hazard (`042 silently becomes 34, not 42`).
- A burned number is refused even after the item is deleted: allocated
  `REQ-B-001`, deleted it, then tried `id: "001"` → `id: 001 would expand to
  'REQ-B-001', but that number is already used or was burned by an earlier
  item under prefix 'REQ-B'`, exit 1.
- The ledger lives at `.refdes/ids.yaml` and has exactly the documented shape
  — `allocated:` (a list) and `burned:` (per-prefix high-water mark). It also
  confirms the page's carve-out: a hand-typed `REQ-W-1` never entered the
  ledger, only the allocated id did.
- `id.width: 3` zero-pads — the next allocation was `REQ-W-002`.
- Prefix mismatch is a nonblocking warning with the documented text
  (`WARNING … id 'CNA-001' does not match this item's prefix 'CAN' (from
  defaults:)`), `refdes check` exits 0, and a free-form category segment
  (`CAN-AI-002` under prefix `CAN`) is correctly *not* flagged — the check
  only requires the id to start with the prefix.
- Duplicate ids fail `refdes check` (exit 1) with the documented message
  shape, including the `(also defined at …)` half.
- Surrogate keys are 11 characters (every key minted during this audit was
  exactly 11), live in the `Crockford base32` alphabet — no `i`, `l`, `o` or
  `u` appeared in any key minted — and the lint checks **both** format and
  uniqueness on `refdes check`: a key with an out-of-alphabet character errors
  ("contains a character outside the key alphabet"), and two items sharing one
  key errors ("is already used by …").
- `refdes keys adopt` exists, is transactional, and writes
  `.refdes/keys-adopted.yaml` (`adopted: true`, `format: 1`).
- `refdes former-ids propose` exists (`usage: refdes former-ids [-h] {propose}`),
  and `refdes build --accept-board-move` exists.
- `former_ids:` resolves `[[CAN_00]]`, renders with a visible
  `(formerly CAN_00)` marker in the built page, warns when an entry cannot
  bare-autolink ("does not match the bare-reference shape (PREFIX-NNN)"), and
  errors when it names a still-live id ("must name only retired ids, never one
  still in use").

### Discrepancies fixed (2)

1. **Every `text:` example on the page failed the build.** Seven examples used
   the `hardware@2` field name `text:`. `hardware@3` folded that into `body:`,
   and the tool is not silent about it: a probe using `text:` on a
   `requirement` produced
   `ERROR … 'requirement.text' is now 'requirement.body' -- rename this key in
   the source file.` plus a missing-id error, exit 1, **0 items loaded**. All
   seven were changed to `body:`; nothing else on the page was touched. This
   was the largest single fix in the audit and the only one that made several
   documented examples non-functional.
2. **Extra space in the sample `refdes id` output.** The page showed two spaces
   between `)` and the item text; `cli.py:463` formats one. Fixed the space.

### Source bug found, not fixed (reported, not edited)

- **`refdes id --dry-run` writes to the source file.** Its help text is "show
  without writing" and `docs/ids.md` says "see what would be allocated without
  writing". It correctly withholds the `id:`, but the surrogate-key minting
  that runs as a side effect of loading the project still writes `key:` into
  the item's source. Reproduced twice: a file with no `key:` came back with
  `key: 43wys1x2ag3` after a single `--dry-run`, and no `id:` was added. The
  documented promise is therefore only half-kept. Left the docs alone, since
  the page's actual subject (whether ids get allocated) behaves correctly.

### Left unverifiable / not changed

- "issue #6, finding 10 part 2" and the surrounding discussion of the
  hand-typed-id gap are references to a tracker issue and an internal finding
  number; neither can be checked from this checkout. The surrounding
  behavioural claims around them *were* checked and hold.
- The `width` advice ("Three digits suits most boards") is judgement, not a
  measurable claim.

---

## docs/checks.md

Scratch projects: `probe31` (limit forms), `probe32` (`%`), `probe33` (limit
errors), `probe34` (unevaluable checks), `probe35` (worst case), `probe36`
(`check_severity`), `probe37` (`value:` scope).

### Claims checked — verified correct, left as-is

- All six limit forms parse: `<=`, `<`, `>=`, `>`, `==`, and a range. One
  eight-bound project mixing every documented form built with 0 errors.
- "In a range, the lower bound may omit the unit: `9 .. 36 V` works" — true.
- The unparseable-limit error reproduces the documented wording exactly, and
  the second `note:` line really does appear
  (`note: if this limit describes more than one bound, split it into one item
  per bound`).
- `limit` is scalar, not a list — a two-element list is refused.
- `value:` must name a variable defined by a `calc` block **in the same item** —
  a value defined in a *different* item gives `check refers to 'shared', which
  no calc block defines`.
- `against:` is expanded in place to the composite form on the next writable
  load, exactly as documented: `against: BND-W-001` became
  `against: BND-W-001@7s2rw7tr1h0`.
- Worst case, not nominal: `V = 10 V ± 20%` against `<= 11 V` fails with
  `worst case 12 V vs <= 11 V (nominal 10 V)`, i.e. it fails on the interval
  reaching 12 V even though nominal 10 V passes.
- The `(nominal X)` suffix exists and the page's second failure sample
  reproduces **verbatim including its numbers** — a probe with
  `CLIM = 0.6061 A ± 15%` against `<= 600 mA` produced
  `worst case 0.697 A vs <= 600 mA (nominal 0.6061 A)`, matching the
  documented line character for character.
- All three `check_severity` values behave as tabulated, checked with custom
  types: default/`error` fails the build; `warning` is visible by default and
  exits 0; `info` is absent from plain `check` output, appears under `-v`, and
  exits 0.
- `check_severity` really does not touch the item page — `_site/opt-001.html`
  still carries the `fail` badge for an `info`-severity failure.
- All four "checks that cannot be evaluated" messages reproduce verbatim,
  including `check I against BND-TEMP: cannot compare: Cannot convert from
  'ampere' ([current]) to 'degree_Celsius' ([temperature])`.
- Margins: `_site/summary.html` exists and carries a **Margins** table headed
  "Worst-case slack against each limit, relative to the limit. Tightest
  first", with the sign agreeing with the verdict.

### Discrepancies fixed (2)

1. **Four `text:` examples, same v3 rename as `ids.md`.** Lines using
   `text:` on `bound` items do not load at `hardware@3`. Changed to `body:`.
2. **"% is not a unit" was false.** The bound example carried
   `limit: "<= 0.01"   # 1 % of full scale, as a dimensionless fraction -- % is
   not a unit`. `%` *is* understood: a bound written `limit: "<= 1 %"` parses
   clean, and a check of `0.5` against it **fails** with
   `worst case 0.5 vs <= 1 %`, proving `1 %` is read as `0.01` rather than as
   `1.0`. (`calc.py:545` divides the percent by 100.) Rewrote the example to
   use `%` directly.

### Left unverifiable / not changed

- "`against` … may be imported from another project" — the cross-project
  import machinery was not stood up for this audit; the claim is delegated to
  `multi-board.md` and its anchor resolves. Left unverified rather than
  assumed.
- "a bound owned by a shared platform project can be checked by every board
  that imports it" is the same untested cross-project claim.

---

## docs/coverage.md

Scratch projects: `probe38`–`probe45`.

### Claims checked — verified correct, left as-is

- The five-stage table and `build.compute_coverage` reading only
  `satisfied_by` / `verified_by` / `addressed_by`. Reproduced all five stages
  from scratch (see concepts.md), including that a requirement can be
  `verified` with `addressed_by` empty, which is the page's "cumulative in
  intent but not required to be in practice" point.
- **`constrained_by` does not feed coverage.** A decision whose only link to a
  bound was `constrained_by: [BND-CV-001]` left the bound at stage `open`,
  with `satisfied_by: []` — the page's strongest claim, and it holds.
- The passive/active convention, with the one honest exception the page calls
  out. A `requirement` cannot author `verified_by:` at all in the bundled
  standard (`unknown field 'verified_by' on requirement`), so I tested the
  exception the way the page describes it — via a project overlay that adds
  the link. With `types.requirement.links.verified_by: [test]` in
  `refdes-schema.yaml`, the requirement reached stage `verified` through
  `verified_by`. So "a project overlay that reaches for the legacy
  `verified_by:` spelling is the one place the passive form does feed
  coverage" is accurate as written.
- The engine-level flags: dumped them from the resolved project.
  `coverable: True` is declared explicitly on `requirement` and `bound` (and
  `False` on `group`); `coverable_statuses: ['active']` is set on
  `requirement`/`bound`; `satisfying_statuses` is `['accepted']` on decision
  and `['selected']` on component; `verifying_statuses` is `['passing']` on
  `test`. All match the page.
- `extends:` inheritance: a type with `extends: requirement` and no coverage
  flags of its own was tracked in coverage, inheriting `coverable` and
  `coverable_statuses` with nothing redeclared.
- `satisfying_statuses:` without a `status` field fails to load —
  `configuration error: types.widget3.satisfying_statuses requires a 'status'
  field on widget3`, exit 2.
- The `coverage.html` column headers are character-for-character the
  documented set: `ID | Title | Stage | Addressed by | Claimed by | Satisfied
  by | Verified by`, and rows are ordered least-covered first.
- The two collapsed warning lines, and the suppression rule: a project whose
  requirements were `satisfied` but which had **no** `test` items at all
  produced **0 warnings**; adding a single test item immediately produced
  `1 requirement(s) satisfied but not verified`. The page's "the moment the
  first one is added" is literally true.
- The per-item `claimed` warning text is exact:
  `claimed but not verified (no test links to it)`.
- The `blocked_by` chain warning, resolved to its root through two hops:
  `claimed but not verified (no test links to it); claimed by DEC-BL-016,
  which is blocked_by DEC-BL-003 <- DEC-BL-001 (on_hold)` — same shape as the
  documented sample.
- The grouped summary line is exact: `WARNING <project> — 2 requirement(s)
  unsettled because DEC-BL-001 is on_hold — see coverage.html`.
- The board token lint message is verbatim, including the file position and
  the parenthetical token:
  `WARNING items/board-a/stub-tests.md:2 [TST-002] — item is on board
  'board-a' (token 'A'), but its id prefix 'TST' does not contain that token`,
  while a `REQ-A-IO-001` whose prefix carries the token drew no warning.
- `stub-tests`, end to end: it wrote stubs only for the coverable items
  lacking a verifying test, into **one** multi-item markdown file
  (`items/stub-tests.md`) rather than one file per item, with `verifies:`
  already pointing at the target and `status: planned` — the type's own
  default, deliberately *not* in `verifying_statuses:`, so a fresh stub does
  not mark its target verified. Ids came out as `TST-001`/`TST-002`, i.e. the
  type's default prefix, not a board-derived one. Re-running with nothing new
  reported "no coverable item is missing a verifying test" — it skipped the
  `planned` stubs rather than duplicating them. After adding one requirement, a
  re-run added only that one and **appended** to the existing file, leaving
  the earlier stubs intact.
- The `items.json` coverage block matches the documented JSON exactly (same
  five keys, same nesting).

### Discrepancies fixed (1)

1. **Two broken anchors.** The page linked
   `links.md#blocked-by-and-the-cascade-report` twice (the "Warnings" and "When
   the claimer is blocked" sections). The heading in `links.md` is
   ``## `blocked_by:` and the cascade report``, and GitHub keeps the
   underscore in a slug, so the real anchor is
   `links.md#blocked_by-and-the-cascade-report`. Both links now resolve. The
   same page's other links into that file
   (`#governed_by-vs-refines-vs-constrained_by`) already used the underscore
   form, which is what made the two inconsistent.

### Source bug found, not fixed (reported, not edited)

- None new. One cosmetic note: re-running `refdes stub-tests` against an
  existing file appends its new fence as a second consecutive `---`, so the
  file momentarily reports `item has no id` until you run `refdes id`, which
  then absorbs the doubled fence and leaves a clean file (confirmed: 10 items,
  0 errors after `refdes id`). Since the command prints exactly that advice,
  the documented flow is sound — this is a report, not a defect.

### Left unverifiable / not changed

- "Imported items are excluded regardless" and the per-board coverage
  behaviour (`coverage-<board>.html`, "Conforming contracts", "not yet
  satisfied on boards") both need a configured import or a second board with a
  `conforms_to:` group. Neither was stood up; the claims are delegated to
  `multi-board.md`, whose anchor resolves. Left unverified rather than
  assumed.
- `coverage.group_inherited` was not exercised; the surrounding `extends:`
  inheritance claim was verified independently and holds.
