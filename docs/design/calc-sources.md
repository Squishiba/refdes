Status: Reviewed -- Jared's decisions recorded 2026-09-19; question 2 in
section 11 is still open.

# Calc values from repo-local source files

## Decision (recap)

Add a **read-only, lockfile-pinned source-value function** to item-local calc
blocks. Its two arguments are a repo-local citation `path:` and a reader-defined,
named key:

```calc
eff : 1 = source("analysis/power-budget.csv", "tps62913_half_load_eff")
```

`source()` is deliberately not an I/O function. `refdes fetch` reads the cited
file, selects and parses the named value, and records its canonical decimal text
under that file's existing citation record in `.refdes/citations.yaml`. Calc
evaluation subsequently consumes that lockfile record. It never parses a
spreadsheet, netlist, or schematic during `check` or `build`.

**V1 is CSV only.** CSV uses a fixed `key`/`value` table contract, UTF-8 with an
optional BOM, and the standard library. XLSX is an optional `openpyxl` reader in
a later minor release, behind an extra dependency. Reader registration is an
internal extension seam, not an entry-point plugin API. EDA readers and
schematic drift checks are deferred; their correct first product is a comparison
against a refdes value, not a way to make a schematic authoritative over a
calculation.

The scope is source selection and drift visibility, not spreadsheet navigation,
formula execution, write-back, or synchronization. Refdes must never modify the
cited source file.

---

## 1. Author-facing syntax and citation ownership

### Recommendation

Use a calc builtin with two **string-literal** arguments:

```calc
name = source("repo-relative/cited-file.ext", "reader-defined-named-key") | unit
```

- `path` must exactly name a **repo-local `path:` citation declared on the same
  item**. It is canonicalized with `citations.classify()` before lookup; the
  author spelling remains the citation's spelling.
- `key` is reader-specific but is always a durable name, never a physical
  position. For CSV it is an exact `key` column value; for XLSX it is a defined
  name; for a future LTspice reader it would be a component/reference key such
  as `R1`.
- `unit` remains the calc line's unit assertion. It is required for every
  `source()` assignment, including dimensionless values (`: 1`). The reader
  supplies no unit.
- The source value is a scalar numeric input. It can participate in normal
  arithmetic and existing tolerances, but `source()` itself has no tolerance
  syntax or magic unit conversion.
  **Superseded in part by the section 11 question 5 decision (Jared,
  2026-09-19):** source-level tolerance is allowed and optional, and an
  assignment carrying both a source tolerance and a right-hand-side tolerance is
  an error. The no-tolerance-syntax shape above is what the recommendation
  proposed and is kept here as the rejected option.

A string-argument builtin is new syntax, not current calc behavior.
`calc._eval_node()` currently rejects string constants and only dispatches
functions in `FUNCTIONS` or project `EQUATIONS`; current function calls also
reject keyword arguments (`src/refdes/calc.py:414-471`). The parser change must
therefore recognize `source()` before normal expression evaluation, validate
exactly two string literals, obtain the pinned decimal, and return a dimensionless
`Value`; the existing annotation conversion then supplies the declared display
unit and dimensional assertion (`calc.evaluate_block()` and
`calc.convert_value()`, `src/refdes/calc.py:831-954`).

Reuse citations; do **not** add `source_file:`, `calc_sources:`, or a second
project registry. A citation already models one project-root-relative artifact
and has a lockfile record keyed by `path` (`CitationSpec`,
`src/refdes/model.py:254-280`; `citations.collect()`,
`src/refdes/citations.py:189-220`). Finding 25 Part 2 already rejects paths that
escape the root, are absolute, use backslashes, or traverse a symlink outside the
project (`citations.classify()`, `src/refdes/citations.py:77-129`). Reusing that
boundary makes the source file's authority, provenance, hash, publication, and
review surface one thing.

Same-item ownership is intentional. Calcs are already item-local: variables are
threaded across blocks of one item but not shared between items
(`docs/math.md:30-31`; `build.run_calcs()`, `src/refdes/build.py:863-897`). A
source reference should retain the same local provenance: the item that trusts
and computes with the value explicitly cites the file. A citation elsewhere in
the project is not ambient permission to read a file.

### Worked example: `DEC-PWR-001`

`items/decisions/dec-pwr-001-regulator-topology.md:42-50` currently types a
TPS62913 half-load efficiency of `0.93` with a datasheet comment. The component
citation is remote and belongs to `CMP-PWR-001`, not this decision
(`items/components/power.yaml:12-18`), so it cannot satisfy the proposed
same-item source rule.

**Migration note:** this example intentionally retains its current `type: decision`; after the in-progress phase 4a decision-to-log merge lands, `DEC-PWR-001` is `type: log` with the fields shown here otherwise unchanged.

**Before (current):**

````markdown
---
id: DEC-PWR-001
type: decision
# … existing fields …
---

```calc
V_in             = 12 V ± 5%
V_out            = 3.3 V
I_load           = 1.2 A
eff              = 0.93                 # TPS62913 datasheet, half load
P_out            = V_out * I_load | W
P_diss           = P_out * (1/eff - 1) | W
```
````

**After (proposed):**

````markdown
---
id: DEC-PWR-001
type: decision
# … existing fields …
citations:
  - path: analysis/power-budget.csv
    id: power-budget
---

```calc
V_in             = 12 V ± 5%
V_out            = 3.3 V
I_load           = 1.2 A
eff              = source("analysis/power-budget.csv", "tps62913_half_load_eff") | 1
P_out            = V_out * I_load | W
P_diss           = P_out * (1/eff - 1) | W
```
````

The cited CSV is committed alongside the project:

```csv
key,value,source_note
tps62913_half_load_eff,0.93,TPS62913 datasheet rev E figure at half load
```

The unit assertion makes `eff` visibly dimensionless at the use site. A CSV
comment column is provenance for spreadsheet readers, not input syntax; only the
same-row `value` cell is extracted.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Add a dedicated item field such as `calc_sources:` | Reject | Duplicates citation path validation, lock ownership, and provenance; risks one file being cited but a different spelling being extracted. |
| Let any project citation authorize `source()` | Reject | Makes provenance non-local and allows an unrelated item to silently grant access. |
| `source("citation-id", "key")` | Reject for V1 | Citation ids are optional and globally unique, while a source needs the actual path visible beside its named key. The path also makes the lockfile lookup direct. |
| Cell addresses (`Sheet1!B14`, CSV row 14) | Reject | Inserting a row can return a different valid numeric value with the same file hash. Named keys make that edit an extraction failure or a reviewable diff. |
| A YAML-only `source:` assignment separate from calc | Reject | Splits an ordinary named calc value into a second declaration language and loses the existing expression/unit/error presentation. |

### Requirement: a picker for importing values from an outside file

Raised by Jared on 2026-09-19.

Importing data from an outside file should have some form of **picker** in the
browser editor, provided that is not terribly difficult to implement.

His reason, in his terms: he is not fond of adding more places where a user has
to manually type the things they want out of a file, and intuition and ease of
use are key.

This is a **requirement on the editor work**, not a decided implementation. What
the picker lists, how a named key is chosen from it, and where the resulting
`source("path", "key")` text is emitted are the editor design's to settle.
Cross-referenced from `docs/design/browser-editor.md`.

---

## 2. Why refdes does not sum over items

A log entry that wants a total — the quiescent and load currents of a design,
say — has no way to get one from items. `{{index}}` filters by `by`, `type`,
`board`, and `tag` and renders one ID-and-title row per item, with no totals
and no value columns (`src/refdes/blocks.py:417-419`; only those two cells are
emitted, `src/refdes/blocks.py:197-203`). Calc functions consume the `Value`s
of one expression: `FUNCTIONS` is `sqrt`, `abs`, `min`, `max`, `exp`, `ln`,
`log10`, and `MULTI_ARG` admits only `min`/`max` (`src/refdes/calc.py:130-173`)
— no function takes a set of items. Calc variables are per item, never shared
between items (`docs/math.md:30-31`). The obvious-looking answer — teach refdes
to sum a field across a set of items — is the one to reject, and this section
records why.

### The completeness argument

A total is only correct if the set it sums is complete, and refdes cannot
verify completeness of its own item set. “Every component item on board A”
totals the parts that happen to have been marked up in `items/`; the number
looks authoritative and is silently wrong the moment a part exists in the
schematic but not in `items/`. Refdes has no schematic, netlist, or BOM to
compare against, so it would be asserting something it cannot check — this
project's characteristic failure: a confident answer with nothing verifying it.
A committed budget CSV or an EDA BOM export, by contrast, is maintained by
someone whose job it is that the set is complete, and refdes hash-pins it. An
omitted part moves the number, and the number's change is a reviewed diff; an
omitted item sums to nothing and nothing notices.

### The division of labour

- **Items** hold the components that carry an argument — a decision behind
  them, a datasheet cited, a bound they must meet.
- **A source file** holds the exhaustive tally — a power-budget CSV, an
  exported BOM — maintained by whoever owns the board.
- **Refdes** carries the claim: its value, its provenance, and whether it still
  holds.

Refdes is not a component database. That boundary is what keeps it from
becoming one.

### Worked example: a rail budget in a log entry

The design's quiescent and load currents live on component items, each with its
own argument, so neither `{{index}}` nor calc can total them. The log entry
that records the rail budget instead pulls the two totals from the committed
power budget and leaves the arithmetic where a `checks:` entry can verify it:

````markdown
---
id: LOG-PWR-001
type: log
date: 2026-09-16
summary: Board A 3.3 V rail budget drawn from the committed power budget.
# … existing fields …
citations:
  - path: analysis/power-budget.csv
    id: power-budget
checks:
  - value: P_3v3
    against: BND-PWR-001
---

```calc
I_load = source("analysis/power-budget.csv", "board_a_total_load") | mA
I_q    = source("analysis/power-budget.csv", "board_a_total_quiescent") | mA
P_3v3  = 3.3 V * (I_load + I_q) | W
```
````

As in section 1's example, this uses the post-phase-4a `log` shape; until the
decision-to-log merge lands, the identical entry is `type: decision`. Each
current is one extracted scalar, exactly as this design specifies; the sum is
refdes-side arithmetic, and the check verifies the total against the rail bound
instead of asserting it as prose. When the budget changes, `refdes fetch
--update` prints the extracted-value diff —
`analysis/power-budget.csv: board_a_total_load: 1.85 -> 2.3` — and the check
re-runs against `BND-PWR-001` on the next build: the author sees the changed
input and its consequence as one reviewed change, the same drift visibility as
section 5's command matrix.

### Decision record

**Decision (Jared, 2026-09-16): item-based aggregation — summing a field over
a set of items — was considered and rejected.** The completeness argument above
is the reason: refdes cannot verify that any set of items it summed was
complete, so the total would be a claim it cannot check. **Escape hatch:** if
aggregation is ever wanted, the honest version requires an explicit
completeness declaration — “this group is the complete set of X” — and a
maintained source file already provides that declaration for free. The bar for
revisiting this decision is a case where no such file can exist.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Give `{{index}}` a totals row | Reject | Sums whichever items happen to exist — the completeness failure — and turns a listing block into a computation. |
| A calc builtin that sums a field over items | Reject | Same completeness failure, plus cross-item state where calc deliberately has none (`docs/math.md:30-31`; every function consumes one expression's values, `src/refdes/calc.py:130-173`). |
| Completeness-declared groups, then sum over members | Escape hatch | Requires “this group is the complete set of X” — which a maintained source file already is, for free. Revisit only when no such file can exist. |

---

## 3. CSV reader contract

### Recommendation

A CSV source is a UTF-8 CSV table with exactly one header row and required,
case-sensitive headers `key` and `value`. Extra headers are permitted for human
context. `source(path, key)` selects the `value` field from **the one data row
whose `key` field is byte-for-byte equal to the key argument**. It does not
select by row number, table order, first prefix match, or a label in another
column.

The reader opens the file with `encoding="utf-8-sig"` and `newline=""`, then
uses `csv.reader(..., strict=True)`. `utf-8-sig` removes only a leading UTF-8 BOM;
it never removes BOM-like characters inside a header or key. The implementation
must first validate header names and each row's column count, then construct the
row map itself. Do not use `csv.DictReader` alone: duplicate headers overwrite
one another in a dict before the reader can diagnose them.

The selected text is stripped only of ASCII space (`U+0020`) and horizontal tab
(`U+0009`) at its ends, then must satisfy
`re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", text, flags=re.ASCII)`
**before** `decimal.Decimal` parses it. That explicit grammar admits only ASCII
decimal forms; it rejects locale notation, units, underscores, non-ASCII digits,
and non-ASCII whitespace. The parsed `Decimal` must be finite, and conversion to
the float-backed calc magnitude must also be finite: overflow is an extraction
error, not an infinite `Value`. The resulting finite value is stored as
canonical decimal text (no exponent normalization requirement beyond
`str(Decimal(value))`). This intentionally keeps units on the refdes calc line
rather than making CSV unit parsing a second language.

### Exact behavior, including silent-wrong-value hazards

Every condition below is an extraction error naming the file, source key, and
header/data line, unless stated as successful. `fetch` must leave that file's
existing lock record unchanged when any requested key for it fails.

| Input or condition | Result | Why this must not silently succeed |
|---|---|---|
| Header row has one `key` and one `value` header; exactly one row has matching exact key | Select the `value` cell in that row | Defines the only successful selection. |
| A header is missing, appears twice, has different case, or carries an invisible character other than a leading BOM on the first header | Error | A fallback position or overwritten duplicate could select the wrong column. |
| A data row has fewer or more fields than the header after CSV parsing | Error | Prevents an unquoted comma from moving a number into the wrong column. |
| Two or more rows have the requested key, even if their values are equal | Error listing every matching line | “First wins” changes the selected value when rows are reordered; “last wins” does the same. |
| Requested key has no exact match | Error, with no fuzzy suggestion used for extraction | A near-match must never become a number. The diagnostic may list close keys as prose only. |
| `key` cell is blank, including an empty quoted cell | Error for that row; it cannot match a nonempty source key | Prevents a malformed row being treated as an implicit default. |
| Selected `value` is empty after ASCII space/tab trimming | Error | `0`, `0.0`, and `0e0` remain valid; absence is not zero. |
| Selected `value` is not in the explicit ASCII grammar (`abc`, `NaN`, `Infinity`) | Error | A failed conversion cannot become a default or a floating non-number. |
| Selected cell is `3.3 V`, `100 mW`, `10%`, `$1.20`, or any other unit/suffix-bearing text | Error | Units must be declared at the calc use site; accepting a suffix would conceal a unit disagreement. |
| `1,000` or `1 000` is quoted in one `value` cell | Error | Thousands grouping is locale-specific and must not become either `1` or `1000` by guesswork. |
| `1,000` is unquoted | Row-width error | Standard CSV sees two fields; accepting it would shift columns. |
| `1,23` intended as a locale decimal is quoted | Error | Decimal comma is never silently reinterpreted as `1.23`. |
| `1_000` | Error | `Decimal` accepts underscores, but an underscore is digit grouping and must not silently alter the source contract. |
| Arabic-Indic `١٢٣`, fullwidth `１２`, or any other non-ASCII digit | Error | `Decimal` accepts Unicode digits; the reader accepts ASCII numeric notation only. |
| A non-breaking space (`U+00A0`) or any other non-ASCII whitespace, including before `1` | Error | Only ASCII space/tab are trimmed; Unicode whitespace must not be silently erased. |
| A quoted `value` cell containing `1` followed by a newline | Error | `re.fullmatch` must consume the entire cell; `^...$` would otherwise accept before a trailing newline. |
| `1e999999` or another value that overflows when converted to calc's float-backed magnitude | Error | A finite `Decimal` is not sufficient if evaluation would receive infinity. |
| Leading UTF-8 BOM on the file | Accepted; it is removed from the first header only | Common export form, handled deterministically. |
| Malformed quoting, dangling quote, invalid UTF-8, or CSV parser error | Error with parser message and physical line when available | A permissive recovery can select a different row. |
| Valid RFC-style quoting, including commas/newlines inside an unused context column | Accepted by the standard CSV parser | The same parsed row is used for header width and selection; quoted text does not alter `key`/`value`. |
| Leading/trailing whitespace in a `key` | Preserved; exact matching means it does not match an unspaced source key | Trimming keys makes two visually similar keys collide. |
| Leading/trailing ASCII space/tab in a numeric `value` | Stripped before the ASCII-grammar check | This is presentation outside the numeric token, not a distinct value. The raw text and canonical decimal must both be available in the error/debug record. |
| `+1.0`, `-1.0`, `.5`, `1.`, `1e-3` | Accepted if the parsed and calc-converted values are finite | These are the explicit grammar's unambiguous ASCII numeric forms. |

The reader must enumerate and extract **every declared source key for a file in
one parse**, not repeatedly search the file per calc line. This produces one
consistent diagnostic set, detects duplicated keys even if only one duplicate is
currently used, and avoids needless I/O.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Configurable key/value column names | Defer | A second mapping syntax creates another place to select the wrong cell. Fixed headers make CSV portable and tests finite. Reconsider only when a real committed table cannot be converted. |
| Row label plus arbitrary value column | Reject for V1 | Equivalent flexibility with more ambiguity; `key`/`value` has one selection rule. |
| Trim and case-fold keys | Reject | Two keys can then alias silently. Keep keys opaque and exact. |
| Parse cell units with Pint | Reject | Violates the finding's refdes-side unit rule and would make `100 mW` look interchangeable with `0.1 W` before the reviewer sees the calc line. |
| Locale-aware parsing | Reject | The source file does not carry a reliable locale contract; a comma can be delimiter, decimal separator, or grouping. |

---

## 4. XLSX reader: optional follow-on

### Recommendation

Implement XLSX only after CSV is proven in a real project, as an optional
`xlsx` extra that depends on `openpyxl`. It uses a defined name, workbook- or
sheet-scoped, never a sheet/cell address:

```calc
thermal_rise = source("analysis/thermal-model.xlsx", "case_rise") | delta_degC
```

The source key resolves a workbook-scoped or sheet-scoped defined name; it must
resolve to one cell containing a finite numeric cached value. A sheet-scoped
name is qualified in the key as `Sheet1!case_rise` (a defined-name key, not a
cell address); the rules for unqualified keys are in the table below. The reader
loads with `data_only=True`; it does not calculate formulas. It returns a
decimal derived from the returned Python numeric value and rejects text,
boolean, date/time, error, blank, formula-without-cache, multi-cell ranges, and
external references.

`openpyxl` is not currently a project dependency; `pyproject.toml:34-42` lists
only four runtime dependencies and no `xlsx` extra. This feature therefore does
not exist today.

### Verified formula-cache behavior

An isolated probe used `openpyxl 3.1.5` to save a workbook with `A1 = "=1+2"`.
Reloading it with `data_only=True` returned `None`; `data_only=False` returned
`=1+2`. The generated worksheet XML was `<c r="A1"><f>1+2</f><v /></c>`.
The probe artifact remains at `.scratch/xlsx-no-cached-value.xlsx` and the
isolated package at `.scratch/openpyxl-probe/`. Therefore a file saved by a tool
that writes formulas without cached results is **not** a source of a numeric
value; fetch must error rather than evaluate the formula or coerce `None`.

### Defined-name and cell rules

| Case | Proposed result |
|---|---|
| Exactly one workbook-scoped name with one internal, single-cell destination | Read the one cached cell under `data_only=True`. |
| Qualified sheet-scoped name, e.g. `Sheet1!case_rise`, with one internal, single-cell destination | Read the one cached cell under `data_only=True`. The part before `!` must name an actual sheet; the part after is matched with the same defined-name rules as an unqualified key. A qualified key never falls back. |
| Unqualified key with no workbook-scoped match, sheet-scoped in exactly one sheet | Read the one cached cell under `data_only=True`. |
| Unqualified key with no workbook-scoped match, sheet-scoped in two or more sheets | Ambiguity error naming every sheet that defines the name; never a pick. |
| No defined name matches the key after the rules above | Extraction error. |
| Two defined names differing only by case | Use `openpyxl`'s exact name identity; source keys remain case-sensitive. Any ambiguity reported by the library is an error. |
| Multi-cell range, union of cells/ranges, 3-D range, table/structured reference, or external workbook reference | Extraction error. This feature extracts one scalar, not an aggregate or query. |
| Literal numeric cell | Accepted if finite. |
| Formula cell with cached numeric result | Accepted as the workbook author's last-calculated value; lockfile records it, not the formula. |
| Formula cell with no cached result (`data_only=True is None`) | Extraction error with `open the workbook in a calculating application, save it, then fetch --update`. Refdes must not calculate Excel formulas. |
| Error cell (`#DIV/0!`, `#N/A`, etc.), blank cell, string, boolean, date/time | Extraction error. |
| Formula cached as a string/boolean/error | Extraction error. |

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Require a defined name plus `Sheet!A1` fallback | Reject | Restores the row/column insertion hazard that named ranges eliminate. |
| Evaluate formulas in refdes | Reject | Requires a partial Excel engine with incompatible semantics and makes fetch execution rather than extraction. |
| Accept sheet-scoped names by choosing the active sheet | Reject | Active-sheet state is presentation and can select a valid but wrong value. |
| Add `openpyxl` to mandatory dependencies now | Reject | CSV covers the first product without a new binary/package surface; XLSX demand must justify it. |

---

## 5. Lockfile, commands, and drift lifecycle

### Recommendation

Extend each existing citation record with a `values:` map only when that cited
local file is used by `source()`. Keep the existing top-level `citations:` map
and canonical-path keys unchanged. Existing citation records contain `sha256`,
`fetched`, `kept_copy`, and `bytes` as written by `citations.fetch_all()`
(`src/refdes/citations.py:496-589`); their current provenance fields are
intentionally outside the item (`CitationSpec`, `src/refdes/model.py:254-263`).

Proposed shape:

```yaml
citations:
  analysis/power-budget.csv:
    sha256: 15cc0b…
    fetched: "2026-09-15T04:18:00Z"
    kept_copy: false
    bytes: 214
    values:
      tps62913_half_load_eff:
        reader: csv
        value: "0.93"
```

`value` is canonical numeric text, not a YAML number, preserving the extracted
lexeme's decimal meaning through YAML loaders. `reader` records how the key was
interpreted and makes an extension-change reviewable. The key is within the
file's record, so `(canonical path, source key)` is unique by construction.
Neither unit nor a source-line location belongs here: units are item/calc
semantics, and source line numbers are unstable presentation details.

A fetch must collect all local `source()` uses from local items, validate that
each has its same-item citation, group requested keys by canonical citation path,
then read each file once. It must stage extraction in memory and atomically
replace that path's record only after **all** requested keys succeed. This avoids
writing a new file hash paired with an incomplete or mixed-generation value set.

### Command matrix

“Source resolver” below means the new calc-source lookup. Existing citation
verification has a related but important exception: today `_resolve_local()`
rehashes the live local citation during every build/check and reports a changed
file as a warning (or an error under `--require-citations`)
(`src/refdes/citations.py:417-468`; `citations.verify()`, lines 290-335). The
recommendation is to preserve that finding-25 behavior, but make the source
resolver itself lockfile-only: it never opens or parses the CSV/XLSX file. See
Open Question 1 for Jared's decision whether “builds read the lockfile only” is
intended to change the existing local-citation hash check too.

| Situation | `refdes fetch` | `refdes fetch --update` | `refdes check` | `refdes build` |
|---|---|---|---|---|
| Source value never extracted; cited file hash is already pinned and matches disk | Extract missing keys, add `values`, update timestamp; print `extracted path key = value` | Same | Source resolver errors: run `refdes fetch --path …`; no extraction | Same error; no source-file parsing |
| Source value never extracted; current local file differs from existing pin | Error; leave old record untouched and direct `--update` | Re-pin and extract all used keys if all succeed | Citation drift warning/error from existing verifier; source resolver still errors missing extraction | Same |
| Current file hash changed after a successful extraction | Existing default fetch skips an already-pinned citation today (`fetch_all()`, `src/refdes/citations.py:550-560`); preserve that policy and print it skipped | Read, hash, and re-extract all declared keys as one transaction | Existing local-citation drift diagnostic; source resolver reads the old locked value | Same: existing drift diagnostic plus calculation using old locked value |
| `--update` changes a value, e.g. `1.85` to `2.3` | N/A | Replace file hash and all values; print `analysis/power-budget.csv: rail_load: 1.85 -> 2.3` and make the same YAML change reviewable | After the fetch, use `2.3` | After the fetch, use `2.3` |
| Requested key vanished, duplicated, became blank/non-numeric, or a reader rejects it | If missing from an otherwise matching pin, error and preserve old record | Error and preserve old record -- **do not** update only the hash or delete the old key | Old lock entry still resolves; live-file drift remains visible if its hash differs | Same |
| Citation record absent altogether | Pin hash and extract values in one write | Same | Existing unpinned citation info/error plus source resolver error | Same |

`check` currently calls `build(..., seal_write=False)` and does not write
project state (`cmd_check()`, `src/refdes/cli.py:205-256`), while `build` calls
`build.run_calcs()` before checks and hashing (`build()`,
`src/refdes/build.py:1856-1860`). The implementation must keep both properties:
source lookup belongs in evaluation, but extraction belongs exclusively to fetch.

`fetch --no-write` already refuses because it writes the citation lockfile
(`cmd_fetch()`, `src/refdes/cli.py:490-515`; `tests/test_no_write.py:221-230`).
Keep that refusal. There is no dry-run extraction proposal: a parse result not
recorded is precisely the hidden state this design avoids.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Separate `.refdes/calc-sources.yaml` | Reject | Splits a single file's hash and extracted values across two review surfaces and creates update ordering. |
| Store only file hash, re-read source during every build | Reject | Reintroduces non-hermetic builds and hides extraction behavior from review. |
| Delete a prior record when `--update` cannot extract a key | Reject | A transient malformed edit should not destroy the last reviewable pin; fail atomically instead. |
| Treat changed local source data as immediate build failure | Defer | Existing local citations intentionally warn, then ask the user to review and re-pin. A new error would be safer but changes Part 25 semantics; Jared must choose it explicitly. |

---

## 6. Units and the 1000x trap

### Recommendation

The calc declaration owns the unit, and every `source()` assignment must have an
explicit annotation. CSV provides only a dimensionless decimal; XLSX likewise
reads a numeric cell only. The source reader neither accepts nor converts a cell
unit.

The visible authoring pattern is therefore:

```calc
load_power = source("analysis/power-budget.csv", "rail_3v3_power") | W
```

If the CSV contains `1850` because the spreadsheet is in mW, the calc table
shows `1850 W`, not an attractive but wrong implicit conversion. A cell containing
`1850 mW` is rejected during fetch, not silently interpreted. The required `: W`
is prominent in both source and rendered calc table; existing annotations already
convert/assert the computed `Value` and emit a dimensionality error on mismatch
(`calc.convert_value()`, `src/refdes/calc.py:831-842`; `docs/math.md:106-120`).

This cannot detect the semantic lie “a bare `1850` actually means mW.” No parser
can recover an omitted unit reliably. The design makes it as visible as possible:

1. Require `: unit` on every source line, including `: 1`.
2. Render source-derived rows with a `source(path, key)` provenance badge/link
   beside the ordinary expression and value; do not hide it in hover-only UI.
3. Store only the raw decimal in the lockfile, so `1850` is visible in the
   reviewed change next to the author-declared `W` in the item diff.
4. Include a fetch warning when a new/replaced magnitude differs by exactly a
   factor of 1000 or 0.001 from the previous lock value, but never suppress or
   rewrite it. This is an advisory clue, not a unit inference rule.

The last warning is useful only on a change. It must not fire on an initial
extraction, on zero, or on unrelated changes; the source annotation and review
remain the actual safety mechanisms.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Allow `100 mW` cells and compare to `: W` | Reject | Makes cell unit parsing/normalization authoritative and obscures the declared unit at the calculation site. |
| Require a CSV `unit` column | Reject | Repeats units in two sources of truth; disagreement becomes a policy puzzle instead of a loud parse failure. |
| Require a unit declaration in the citation entry | Reject | A file can supply values with different dimensions; dimensional meaning belongs to each named calc variable. |
| Infer SI prefixes from value magnitude | Reject | `1850 W` can be real. Guessing a prefix produces the exact silent wrong answer this feature must avoid. |

---

## 7. Reader extension seam

### Recommendation

Add a private, typed reader registry in `refdes.sources`; register only the V1
CSV reader. It is an internal extension point so CSV, XLSX, and EDA readers share
a contract without treating every future format as a calc special case.

```python
@dataclass(frozen=True)
class SourceRequest:
    path: str                 # canonical project-relative citation path
    key: str                  # source() key, opaque and exact

@dataclass(frozen=True)
class ExtractedSource:
    reader: str               # stable reader identifier, e.g. "csv"
    key: str
    value: Decimal            # finite, unitless scalar only

class SourceReader(Protocol):
    name: str
    extensions: tuple[str, ...]

    def extract(
        self, path: Path, requests: Collection[SourceRequest]
    ) -> Mapping[str, ExtractedSource]:
        """Return every requested key or raise SourceExtractionError.

        The reader opens `path` read-only; it cannot write, calculate, launch a
        subprocess, resolve paths, or update the lockfile. It includes the
        reader/key/source location in errors but never returns a fallback.
        """
```

The registry selects exactly one reader by case-insensitive filename extension.
No reader for an extension is an error at fetch time, not a fallback to CSV or a
best-effort text parse. A reader receives a `Path` already verified by the
citation layer; it receives only the exact requested keys. The fetch coordinator,
not a reader, owns hashing, lockfile mutation, lockfile canonicalization, output
diffs, and same-item-citation authorization.

**No third-party entry points in V1.** `importlib.metadata` plugins introduce
unversioned executable code into the one command intended to make provenance
reproducible, plus conflicts over extensions and error contracts. Ship an
internal registry and tests; add an entry-point API only after at least two
in-tree readers have demonstrated the stable interface. Third-party code can
meanwhile generate the fixed CSV export, which is a safer and interoperable
boundary.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| One `if suffix ==` chain in `citations.py` | Reject | CSV/XLSX/EDA parsing would entangle with citation hashing and expand the wrong module. |
| Reader returns a Pint quantity | Reject | Units are refdes-side by decision; readers return a finite scalar only. |
| Reader writes its own cache | Reject | Violates one lockfile/one writer and makes updates non-atomic. |
| Python entry-point plugins now | Defer | Enables arbitrary code and weakens reproducibility before the in-tree contract has evidence. |

---

## 8. Schematic and netlist sources: drift checks, not V1 calculators

### Recommendation

Do **not** ship an LTspice `.asc`, QSpice, Falstad, Altium, BOM, or netlist
reader in V1. V1's only built-in reader is CSV. A schematic reader's first use
should be an explicit **drift check** between an authoritative refdes
calc/decision value and an independently authored EDA value, not a calc source
that turns the schematic into hidden numeric authority.

For example, a later check declaration could say, conceptually:

```yaml
source_checks:
  - expected: CLR                 # calc value on this decision
    path: analysis/power.asc      # same-item local citation
    key: R1                       # LTspice component reference
```

It would fetch and pin the schematic's `SYMATTR Value` for `R1`, then at
build/check compare that pinned scalar with the calc value's declared unit. A
mismatch is a check violation: “schematic R1 is 2.2 kohm; `DEC-…` calculates
3.3 kohm.” It must never write the `.asc` file or decide which side to repair.
This is drift detection, not navigation, netlist browsing, or synchronization.

CSV BOM/netlist exports fit the same future check interface. They are preferred
over opaque vendor-binary schematic formats because an explicit export is
reviewable and can use the V1 CSV reader where its schema matches. An LTspice
`.asc` `SYMATTR Value` parser is an extension candidate only once a real project
needs a native reader. Altium binary `.SchDoc`/`.PcbDoc` remain out of scope;
export CSV/netlist first.

### Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Treat `SYMATTR Value` as a normal calc source in V1 | Reject | Makes an EDA representation hidden authority for a design decision and broadens V1 past a safely testable CSV contract. |
| Write calculation values back into a schematic/BOM | Never | Inverts authority, risks corrupting engineering files, and creates impossible round-trip rules. |
| Parse every EDA format as files become available | Reject | Commits a solo project to vendor-format maintenance. The CSV/netlist export boundary generalizes. |
| Schematic screenshots as provenance | Reject | A screenshot is hashable evidence but cannot compare `R1` against a calc value. |

---

## 9. Hashes, seals, baselines, imports, and equations

### Recommendation: source values enter the item content hash

Add the resolved `(canonical citation path, source key, locked numeric text)` for
every `source()` call to the owning local item's content-hash payload. Bump
`HASH_FORMAT` to the next **coordinated** format number and retain the existing
historical hash readers/migration posture. `HASH_FORMAT` is currently 3
(`c148896`); phase 4a also changes hash behavior for the type rename, so this
work must use whatever next number has landed rather than assuming 4.
The cited **file hash alone** must not be the item input: an unrelated edit to a
large budget spreadsheet should not invalidate a decision whose selected key did
not change, while a selected value changing under the same file must invalidate
it. The item source text alone is also insufficient: `source(path, key)` can stay
unchanged while `--update` deliberately changes its locked value.

Current hashing includes only fields whose `on_change` is `invalidate`, links,
and an invalidating body (`_hash_payload()`, `src/refdes/build.py:1023-1060`).
The current narrow `calc_hash_for()` deliberately hashes calc **source text**,
not evaluated values, so it cannot see an upstream input moving
(`src/refdes/build.py:1068-1091`). By contrast, content hashing this resolved
source input makes seals/baselines/suspect-link consumers notice a reviewed
source-value change as content. It is an intentional hash-format change, not an
incidental lockfile side effect.

This differs from ordinary citation provenance: current citation lockfile changes
do not alter an item content hash (`tests/test_citations.py:test_content_hash_unaffected_by_lockfile_changes`). The exception is justified because `source()` makes one lockfile scalar part of the item's arithmetic input. Do not hash fetch timestamps, full source-file SHA-256, reader implementation version, unreferenced lock values, citation publication fields, or other citation records.

### Seals and baselines

- New stamps/seals record the new format and resulting hash normally. Existing
  `HASH_FORMAT` is already per-baseline migration machinery
  (`src/refdes/build.py:1010-1020`). The implementation must add a historical
  payload builder that reconstructs the pre-source format without source input,
  exactly as the existing format machinery does for link/check changes.
- A value update changes the consuming item's content hash even when the calc
  block text stays identical. This is the desired signal for baselines and
  suspect links.
- Existing `calc_hash` remains source-text-only. It should **not** be repurposed;
  the stale-arithmetic feature intentionally asks a different question
  (`docs/design/stale-arithmetic-signal.md:79-100`). A later design may add a
  separate source-input fingerprint if that report needs it.

### `--no-write`

No new exception: `fetch --no-write` refuses, and check/build source resolution
writes nothing. The existing global no-write suite asserts project bytes remain
unchanged for read-type commands (`tests/test_no_write.py:188-200`). Add the new
source-bearing fixture to that contract. A normal build may still follow its
existing site/seal semantics; this feature must not add an unannounced lockfile
write to it.

### Imports

Imported items are read-only projections of an upstream `items.json`, not source
trees (`imports.load_imports()`, `src/refdes/imports.py:1-10`). The current
importer reconstructs fields, links, identity, and upstream content hash, but
not body, citations, calcs, or calc values (`_absorb()`,
`src/refdes/imports.py:61-122`). `run_calcs()` and `compute_hashes()` likewise
iterate `project.local_items` only (`src/refdes/build.py:863-897, 1185-1215`).

Therefore V1 source extraction applies only to local items. An importing project
must not reopen an upstream source file or lockfile; it consumes the upstream
item's already-exported hash/version exactly as it does today. Once V1 adds
source values to content hashes, an imported upstream item naturally carries the
changed upstream hash in its artifact. No import-format extension is needed for
correct hash propagation. Exposing source provenance in exported JSON is a later
presentation/API question, not required for calculation.

### Finding 27 equations

Project equations already exist: `calc.Equation`, `set_equations`, and
`validate_equations` are the current project namespace (`src/refdes/calc.py:179-293`;
backlog finding 27, `docs/design/backlog.md:831-836`). `source()` is an
item-contextual builtin and **must not be callable inside an equation**. Equations
are project-wide formula definitions; allowing a path/key there would either
require a defining item/citation owner or turn a project setting into ambient
file access. Keep source calls in item calc blocks. An equation may consume a
source-derived `Value` passed as an ordinary argument.

---

## 10. Implementer checklist and required tests

### V1 scope

- [ ] Add `source(path, key)` as item-calc-only syntax: exactly two string
  literals, same-item local citation required, explicit unit assertion required.
- [ ] Add `refdes.sources` internal protocol/registry and only the stdlib CSV
  reader.
- [ ] Extend fetch discovery, per-file atomic extraction, lock serialization,
  `--update` value diff output, and source-specific diagnostics.
- [ ] Make check/build resolve values from lockfile only; never parse a reader
  input during evaluation.
- [ ] Preserve current local citation hash-drift verification unless Jared
  decides otherwise in Open Question 1.
- [ ] Add selected locked source values to the owning content hash; coordinate
  the next `HASH_FORMAT` number with phase 4a and migrate it deliberately.
- [ ] Render source provenance beside calc rows.
- [ ] Keep source files strictly read-only; do not add navigation, formula
  calculation, reader plugins, xlsx, EDA readers, EDA checks, or write-back.

### Later

- [ ] Optional `xlsx` extra using workbook- and sheet-scoped, one-cell defined
  names and cached values only.
- [ ] Separate `source_checks:` drift-check contract and first LTspice/CSV
  BOM/netlist reader where a real project provides fixtures.
- [ ] External reader entry points only after two in-tree readers stabilize the
  protocol.
- [ ] Export/display source provenance in `items.json` only if a consumer needs
  it; do not invent it preemptively.

### Required named tests

The test names below are acceptance criteria, not a demand for one giant test
module. Tests must assert the selected numeric result or a specific diagnostic,
not reader internals.

1. `test_csv_source_selects_same_row_value_by_exact_key` — a real calc resolves
   the right scalar after fetch; a later-row reordering does not change it.
2. `test_csv_source_duplicate_key_errors_instead_of_first_or_last_wins` — two
   matching rows error even with identical values.
3. `test_csv_source_duplicate_header_errors_before_column_overwrite` — duplicate
   `value`/`key` headers cannot silently select a column.
4. `test_csv_source_missing_key_blank_value_and_non_numeric_value_error` — each
   fails loudly; `0` remains valid.
5. `test_csv_source_rejects_unit_suffix_grouping_locale_unicode_and_overflow` —
   `100 mW`, quoted/unquoted `1,000`, quoted `1,23`, `1_000`, Arabic-Indic and
   fullwidth digits, NBSP, a quoted trailing newline, and `1e999999` all fail
   before a wrong calc value.
6. `test_csv_source_handles_utf8_bom_and_standard_quoted_context` — BOM only at
   start works; valid quoted fields do not shift selection.
7. `test_csv_source_rejects_malformed_quote_and_ragged_row` — no best-effort
   recovery selects a number.
8. `test_source_requires_same_item_local_citation_and_explicit_annotation` — a
   remote path, absent citation, citation on another item, or missing `: unit`
   cannot resolve.
9. `test_source_build_uses_locked_value_without_opening_reader_file` — delete or
   make the reader unavailable after fetch and prove source evaluation's only
   failure/success derives from lock/citation policy, not reader execution.
10. `test_fetch_extracts_missing_value_from_matching_existing_pin` — adding a
    source to an already-pinned citation works without unnecessary `--update`.
11. `test_fetch_refuses_missing_extraction_when_file_hash_changed_without_update`
    — never associate an old hash with newly extracted current bytes.
12. `test_fetch_update_reports_value_diff_and_updates_hash_and_values_atomically`
    — assert visible `1.85 -> 2.3`, new scalar result, and no partial record.
13. `test_fetch_update_preserves_previous_record_when_named_key_vanishes` — this
    is the key disappeared/partial-write regression.
14. `test_source_value_hash_changes_when_locked_value_changes` — identical calc
    text plus an accepted source update changes `content_hash` and baseline/seal
    behavior; unrelated values in the same source file do not.
15. `test_source_lock_timestamp_and_unreferenced_values_do_not_change_hash` —
    validates the narrow hash input.
16. `test_source_no_write_never_creates_or_updates_lockfile` — extending the
    existing no-write snapshot fixture.
17. `test_xlsx_defined_name_requires_one_workbook_scoped_cell` — when XLSX ships:
    exactly one workbook-scoped, single-cell defined name resolves; missing names
    and external/multi-cell destinations error.
18. `test_xlsx_sheet_scoped_name_resolves_with_qualified_key` — `Sheet1!case_rise`
    reads the one cached cell; an unqualified key that is sheet-scoped in exactly
    one sheet also resolves.
19. `test_xlsx_unqualified_sheet_scoped_name_ambiguous_between_sheets_errors` —
    an unqualified key matching sheet-scoped names in two or more sheets is an
    ambiguity error naming every matching sheet; it never picks one.
20. `test_xlsx_formula_without_cached_value_errors` — fixture with formula XML
    `<f>…</f><v/>`; `data_only=True` `None` is never treated as zero.
21. `test_xlsx_error_string_and_boolean_cells_error` — no coercion.
22. `test_source_reader_cannot_write_source_file` — snapshot bytes before/after
    `fetch --update` for CSV and later XLSX/EDA fixtures.

---

## 11. Open questions for Jared

Jared answered these on 2026-09-19. Each answer is recorded under its question;
question 2 is the one he left open, with his reasoning recorded as the state of
the question.

1. **Does “builds read the lockfile only” supersede Finding 25 Part 2's current
   local-file hash verification?**
   - **A. Preserve current verification (recommended).** The new source resolver
     reads only the lockfile, but `citations._resolve_local()` continues hashing
     the local file to warn of drift. This minimizes semantic change and retains
     the recently landed finding-25 alarm.
   - B. Make all local citations lockfile-only during build/check; move hash
     drift detection to an explicit check/fetch command. This is more hermetic
     but weakens current automatic detection and changes finding 25.
   - **Decision (Jared, 2026-09-19): A.** Finding 25's current local-file hash
     verification is preserved.

2. **Should a changed source file make ordinary build/check fail, rather than
   retain citation warning semantics until `fetch --update`?**
   - **A. Warning, preserve existing local-citation posture (recommended).** The
     build reproduces the reviewed lock value while showing drift; CI can promote
     with existing `--require-citations` behavior.
   - B. New hard error for files that supply `source()` values. Stronger guard,
     but creates a source-specific citation severity and blocks builds before
     review can inspect the intended diff.
   - **STILL OPEN (Jared, 2026-09-19).** No option is picked and this is not
     decided. His reasoning, both halves: he can see a worksheet being used as
     an external form of calculation block, so editing it would be a natural
     progression of its use in refdes; but a file changing when you do not
     expect it to is also bad. He is deliberating.

3. **Is same-item citation ownership the desired provenance boundary?**
   - **A. Yes (recommended).** It matches item-local calcs and makes the decision
     state its own source.
   - B. Permit a project-global citation or `[[cite:id]]` owner. Less repeated
     metadata, but source authority becomes non-local and requires new lookup
     semantics.
   - **Decision (Jared, 2026-09-19): A.** Same-item citation ownership is the
     provenance boundary.

4. **Is fixed CSV `key,value` sufficient for the first real project?**
   - **A. Yes (recommended).** It is deliberately boring and makes every silent
     selection hazard testable.
   - B. Add per-citation column mapping now. More flexible, but it adds schema,
     lock, and wrong-column failure modes before any concrete need.
   - **Decision (Jared, 2026-09-19): A.** Fixed CSV `key,value` is sufficient
     for the first real project.

5. **Should `source()` accept an optional source-level tolerance?**
   - **A. No (recommended).** Put `±` on the assignment's right-hand result with
     existing calc semantics, e.g. `eff : 1 = source(...) ± 2 %`; this keeps one
     tolerance grammar.
   - B. Store source tolerance metadata. It risks treating spreadsheet
     presentation as a second unit/tolerance authority.
   - **Decision (Jared, 2026-09-19): source-level tolerance is allowed, and it
     is optional** — his words: optional, or a switch the user can change. Not
     option A as written. When a source carries a tolerance
     **and** the assignment's right-hand side also carries one, refdes
     **errors**: neither silently wins, and the author deletes one.
   - His leaning, recorded as context and not as the rule: he leans toward the
     assignment being the winner, but understands why that is undesirable.

6. **When XLSX lands, should sheet-scoped defined names be allowed through a
   qualified key such as `Sheet1!case_rise`?**
   - **A. No in first XLSX release.** Workbook-scoped names are unambiguous and
     make key syntax portable.
   - **B. Add qualification.** It handles some workbooks but introduces spelling
     and renaming rules; demand a real fixture first.
   - **Decision (Jared, 2026-09-16): B — sheet-scoped defined names are
     supported in the first XLSX release.** The key must name the sheet
     explicitly (`Sheet1!case_rise`); an unqualified name that exists only as a
     sheet-scoped name in exactly one sheet may still resolve, while an
     unqualified name matching sheet-scoped names in two or more sheets is an
     ambiguity error, never a pick. Sections 4 and 10 carry the corresponding
     rules and named tests. **Escape hatch:** if implementation shows this is
     much larger than it looks, it may be deferred out of the first XLSX
     release; the reason must be written down here before that deferral
     happens.

7. **When a source value changes by exactly 1000x, should fetch warn?**
   - **A. Yes, advisory only (recommended).** It makes the canonical mW/W trap
     conspicuous without guessing units or rejecting legitimate changes.
   - B. No special warning. Simpler, but leaves a well-known human-scale error
     less visible than it needs to be.
   - **Decision (Jared, 2026-09-19): A.** Advisory warning only on a 1000x
     change.

8. **Should source provenance appear in exported `items.json` in V1?**
   - **A. Rendered calc-row badge only (recommended).** The lock/hash contract is
     enough for correctness; adding a public artifact schema now commits a
     consumer API without a user.
   - B. Export path/key/locked value. Useful for tooling, but needs a versioned
     schema and decision about whether every citation or only source uses appear.
   - **Decision (Jared, 2026-09-19): A.** Rendered calc-row badge only in V1.

Question 6 was decided on 2026-09-16 (option B, sheet-scoped defined names) and
Jared confirmed on 2026-09-19 that it is answered; its decision block above
stands unchanged.

The requirement Jared raised on 2026-09-19 for a **picker** in the browser
editor when importing values from an outside file is recorded in section 1, next
to the syntax it serves.
