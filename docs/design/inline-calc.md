Status: **Proposed -- design only.** No code is scoped or written.

# Inline calc: evaluate-in-place math for engineering notes

## Decision recap (Jared, 2026-10-15)

The three decisions below are recorded verbatim in
`in-prog-logs/design-inline-calc.txt` and in PR #250. They govern everything in
this doc.

- **D1. Results are stored in the file text and verified by check/build.**
  The owner sketched this as `Vout = 0.8 V*(1+Rtop/Rbot) = 4.436 V`; the
  concrete grammar in §3.2 expresses it as
  `Vout := 0.8 V*(1+Rtop/Rbot) = 4.436 V`. The `= 4.436 V` is real text the
  editor (or a fill command) writes. If inputs change later, check/build report
  the stale number (`says 4.436 V, now computes 4.52 V`) instead of silently
  changing it.
- **D2. The preview pane stays**, as an optional `as published` view.
- **D3. No code execution.** The existing restricted calc evaluator
  (`src/refdes/calc.py`) is the only evaluator. The editor gets live results
  from `refdes serve` (which already runs calc for the preview), never from a
  JavaScript copy of the evaluator.

These decisions are not reopened here. Everything else is a proposal with
options and a recommended default.

## 1. Problem

Today refdes math is a separate step from writing. You write a ```` ```calc ````
fence, and the result shows up in a different place -- the rendered table on the
item page, or the editor's preview pane (`docs/math.md`;
`docs/design/browser-editor.md:417-431`). `source()` values are pinned and
verified, but the line that uses them is still inside a fenced block
(`docs/design/calc-sources.md:1-34`). Calcpad has the same friction. The request
is Mathcad's model: type an equation *in the notes*, and have it evaluated (and,
where asked, solved) in that exact spot, as part of writing.

This document proposes a syntax, a verification model, a fill command, live
editor support, one-unknown solving, reusable calculators, and an editor form
panel. It also says what this does **not** change: ```` ```calc ```` fences stay,
`{{name}}` prose references stay, per-item variable scope stays, named calc
blocks stay rendering-only labels, `source()` keeps its citation/lockfile rules,
and the workbench preview pane stays the published view.

## 2. What already exists and is not changed

These are the load-bearing precedents. Where this design contradicts one, it
says so explicitly; otherwise it builds on them.

- **No code execution.** `docs/concepts.md:146-148` says the calc DSL has no
  loops, conditionals, imports, or attribute access. Inline calc is still that
  DSL.
- **Per-item variable scope.** `docs/math.md:30-32`: calc variables are visible
  to later lines in the same item, across multiple blocks. Inline assignments
  would join that same scope.
- **Unit assertions and tolerances.** `docs/math.md:336-354`:
  `name = expression | unit` pins the display unit and asserts dimensionality.
  The same evaluator, units, and tolerance propagation apply to inline
  expressions; where the `| unit` assertion itself goes in an inline span is
  open (Q17).
- **Cross-item value references.** `docs/math.md:95-128`:
  `DEC-PWR-001.V_in` is a real dependency evaluated in dependency order and
  stored expanded as `DISPLAY-ID@key`. The resolved values are captured in the
  baseline snapshot via `calc_reference_snapshot` (`src/refdes/build.py:2085`)
  and contribute to the referring item's content hash via
  `_calc_refs_hash_value` (`src/refdes/build.py:2103-2116`). These references
  can appear inside inline expressions.
- **`source()` lockfile semantics.** `docs/design/calc-sources.md:1-34, §5`:
  `source(path, key)` is item-local, citation-owned, pinned by `refdes fetch`,
  and resolved from the lockfile at build time. Nothing here changes that.
- **Named calc blocks are labels, not scopes.**
  `docs/design/named-calc-blocks.md` §3.5, §4: block names identify a rendering,
  never a value namespace. Inline spans are not blocks and have no block name.
- **No keyword arguments in calc calls.** `src/refdes/calc.py:436-438` rejects
  keyword arguments for project equations. Calculator calls proposed in §8 use
  positional arguments only; keyword arguments are not added.
- **Preview pane is the published view.**
  `docs/design/browser-editor.md:417-431` already runs the full calc/render
  pipeline on a candidate body served by Python. Inline calc live updates would
  reuse that path, not replace it.
- **Workbench W5a/W5b assumptions.** `docs/design/thread-workbench.md:268-289`
  treats the preview pane as the interaction surface for tasks and values.
  Inline calc adds a *second* interaction surface -- the body editor itself --
  while leaving the pane as the `as published` view (D2).

## 3. Inline syntax

### 3.1 The ambiguity we have to solve

Prose already contains `=` (`x = 5 in the datasheet`). Existing documentation
also contains many single-backtick code spans of the form `NAME = value`, e.g.
`docs/math.md` uses `` `V_in = LOG-PWR-001.V_in | mV` ``, `docs/design/backlog.md`
uses `` `V_cl = 0.8 V` `` and `` `CLR = 3.3 kohm` ``, and `docs/design/editor-image-upload.md`
uses `` `MAX_BODY_BYTES = 1 MiB` ``. A trigger rule that fires on any `NAME = value`
code span would misclassify all of these as inline math.

I checked single-backtick spans in `docs/` and `tests/` for a simple
`NAME = value` pattern, excluding this design doc, spans inside fenced code
blocks, and spans with more than one `=`. The count is **39 spans in existing
`docs/` and 0 in `tests/`** (the exact command and its output are recorded in
`in-prog-logs/design-inline-calc.txt`). None of them contain `:=`, and none of
them should be evaluated. Requiring `:=` is therefore the safest trigger.

**Trigger rule (recommended).** A single backtick code span is interpreted as
inline math only when its content contains `:=` and matches the grammar in §3.2.
Ordinary spans like `Rtop/Rbot`, `foo()`, `V_cl = 0.8 V`, and
`MAX_BODY_BYTES = 1 MiB` are untouched.

**Alternative trigger rules.**
- (b) Explicit opt-in per item, e.g. a field `inline_calc: true` in item front
  matter. This is safe but adds friction; it is a fallback if the recommended
  rule ever proves too aggressive.
- (c) Mandatory leading marker at the start of the span, such as
  `` `= 0.8 V * (1 + Rtop/Rbot) = 4.436 V` `` or
  `` `:= Vout = 0.8 V * (1 + Rtop/Rbot) = 4.436 V` ``. This is unambiguous but
  noisier than `:=` and does not remove the ambiguity for `NAME = value` spans
  unless the marker is required.

### 3.2 Grammar

A single backtick span is one of:

```text
basic       = name " := " expression [ " = " result ]
solve       = name " := " solve-result " where " expression " = " target
              [ " from " quantity " to " quantity ]
multi-out   = name-list " := " call [ " = " result-list ]

name          = calc assignment name  ([A-Za-z_][A-Za-z0-9_]*)
name-list     = name *(", " name)
expression    = any existing calc expression
call          = equation-name [ "::" version ] "("
                [ expression *(", " expression) ] ")"
equation-name = name
version       = 1*DIGIT
result        = calc quantity literal (may be dimensionless)
result-list   = result *(", " result)
solve-result  = "?" | quantity
target        = calc quantity literal with unit
quantity      = calc quantity literal
```

Rules:

- `:=` **defines** one or more names in the item's calc scope. Every evaluable
  inline span must contain `:=`; without it, the span is ordinary code.
- In **basic** and **multi-out** spans, the **stored result** is the value after
  the **last** ` = `.
- In a **solve** span, the stored result is the `solve-result` before `where`.
  It is `?` before solving and a quantity after the fill command writes the root.
- A span that matches the grammar but has no stored result (basic or multi-out
  without `= result`) is verified as a definition; the build warns that the
  result is missing and the fill command can add one.
- A span that matches the grammar but is semantically invalid (for example, a
  solve with no `from .. to ..` bracket, or a calculator call naming an
  undefined equation) produces a build **error**, not an ordinary code span.
- Any code span whose content does **not** match this grammar is treated as an
  ordinary inline code span.

The grammar has no slot for a `| unit` display assertion: in a calc block the
assertion is split off the *line* before the assignment grammar sees it
(`src/refdes/calc.py:1349-1357`), so it is not part of `expression` either.
Where a basic span's unit assertion goes is open (Q17).

Examples (every one parses under the grammar above):

```markdown
`Vout := 0.8 V * (1 + Rtop/Rbot) = 4.436 V`       # basic, defines Vout
`I_load := 1.2 A`                                  # basic, no stored result
`Rbot := ? where Vout = 3.3 V from 1 kohm to 1 Mohm`   # solve, unsolved
`Rbot := 3.2 kohm where Vout = 3.3 V from 1 kohm to 1 Mohm`  # solve, solved
`Vout, ratio := divider(0.8 V, 10 kohm, 2.2 kohm) = 4.436 V, 4.545`  # multi-out
`Rtop/Rbot`                                        # ordinary code span
`foo()`                                            # ordinary code span
`V_cl = 0.8 V`                                     # ordinary code span (no :=)
```

Why a code span works:

- Markdown already treats backtick content as distinct from prose. Prose like
  `x = 5 in the datasheet` is not inside a code span, so it is never interpreted
  as math.
- The same backtick envelope is what authors already use for values and
  expressions in documentation.
- The build already processes the body before Markdown-it sees it
  (`src/refdes/build.py:3126-3144`), so scanning for backtick spans is no new
  parsing stage.

### 3.3 Two rejected alternatives

| Option | Shape | Why it is not recommended |
|---|---|---|
| **A. `{{= ...}}` directive** | `{{= Vout = 0.8 V * (1 + Rtop/Rbot)}}` | Reuses the `{{...}}` envelope that already renders calc values (`docs/math.md:245-265`; `src/refdes/build.py:75-77`), but the result is not stored visibly in the source unless the directive text also contains it. That makes the directive either violate D1 or require an unreadable hybrid like `{{= ... -> 4.436 V}}`. It also overloads the same braces that currently mean `reference an existing value` with `evaluate a new expression`. |
| **B. Fenced inline block** | ```` ```inline-calc Vout = ... = ... ``` ```` inside a paragraph | Clear, but it is not inline -- it breaks paragraph flow and looks like a mini fence. It also duplicates the fence machinery without the block-level rendering that justifies a fence. |

The recommended code-span shape is kept because it stores the result in the
file text, is visually distinct from prose, and needs no new Markdown construct.
The `:=` trigger makes it unambiguous with existing `NAME = value` code spans.

## 4. Stored-result format and verification

### 4.1 What is stored

The `= result` text is literal source. It is not a comment, not hover-only, and
it is **never silently rewritten by `check` or `build`**. In the recommended Q8(a)
live-editor mode the editor rewrites stale results automatically as the author
types; in the explicit-button mode it rewrites only when the author asks; the
fill command rewrites only when invoked. `check`/`build` never rewrite results.
Example:

```markdown
`Vout := 0.8 V * (1 + Rtop/Rbot) = 4.436 V`
```

If `Rtop` later changes and the same expression now computes `4.52 V`, the build
says:

```
WARNING inline-calc Vout at DEC-PWR-001.md:23: stored result says 4.436 V, but the expression now computes 4.52 V
```

The check compares:

1. The expression evaluated by the existing calc evaluator
   (`src/refdes/calc.py:683-688`, `1301-1380`).
2. The `result` parsed as a quantity by the same `parse_quantity`
   (`src/refdes/calc.py:589-594`).
3. Unit dimensionality enforced by `convert_value`
   (`src/refdes/calc.py:1287-1300`).

How tightly the two must match is an open question (Q2). The conservative
starting point is: format the computed value with `project.sigfigs`
(`src/refdes/calc.py:981-984`) and require the stored text to represent the same
value within its own stated precision. A result written by the tool always
matches; a hand-edited result that is merely rounded differently is allowed up
to its last significant digit.

### 4.2 Where verification happens

Inline calc spans are evaluated during the existing calc pass. They are parsed
from the item body outside of ```` ```calc ```` blocks, in source order, and fed
into the same per-item `env` that the blocks use
(`src/refdes/calc.py:1301-1319`). Only spans that match the §3.2 grammar are
evaluated; all other code spans are left alone. An assignment (`:=`) adds a name;
a trailing `= result` is verified. The outcome produces a diagnostic at the
item's source line, just like a calc block error.

### 4.3 Interaction with hashes, seals, and upstream changes

- **Content hash.** The inline span is body text, and the content-hash payload
  includes the body text of items whose body has `on_change: invalidate`
  (`src/refdes/build.py:1858-1907`). A block rename moves `content_hash` while
  leaving `calc_hash` untouched (`docs/design/stale-arithmetic-signal.md:82-84`);
  the same applies to renaming an inline result. Changing the result text
  therefore marks the item changed.
- **`calc_hash` / stale-arithmetic signal.** The existing `calc_hash_for()`
  hashes only ```` ```calc ```` block contents
  (`docs/design/stale-arithmetic-signal.md:79-85`). Inline math is arithmetic in
  the body, so the probe should be extended to hash the inline expression text
  as well, excluding the stored result. This keeps the signal's meaning: `the
  verdict moved, the arithmetic didn't`.
- **Upstream changes.** A cross-item reference inside an inline span is captured
  by `calc_reference_snapshot` (`src/refdes/build.py:2085`) for the baseline and
  by `_calc_refs_hash_value` (`src/refdes/build.py:2103-2116`) for the content
  hash. When an upstream value moves, the dependent item is marked changed; on
  the next build, the stored inline result is also checked and may be reported
  stale.
- **Sealed entries.** A sealed/append-only entry keeps the stored number that was
  true when it was written. If upstream inputs make that number stale, the build
  reports it as a warning; the fill command refuses to rewrite a sealed entry.
  The author appends a new entry or reseals after review.

### 4.4 Diagnostic wording and severity

```
WARNING inline-calc Vout at DEC-PWR-001.md:23: stored result says 4.436 V, but the expression now computes 4.52 V
```

By default the stale result is a **warning**, not an error. Append-only logs are
*expected* to keep old numbers that no longer match current inputs -- that is
the point of D1. Ordinary `refdes check`/`refdes build` therefore keep running.

The warning is promoted to a **gate failure** for non-sealed items when
`release_gate.inline_calc_results` is enabled. This rule covers **both stale
results and missing stored results** -- a span that defines an evaluable inline
calculation but has no `= result` is unverified and fails the gate the same way a
stale result does. Sealed items are excluded from this gate: a sealed append-only
entry cannot be edited without resealing, and history-backed resealing has not
yet landed (`src/refdes/build.py:1505-1510`).

The release gate is the existing mechanism that `refdes revision` /
`refdes release` use to decide whether a baseline can be stamped
(`src/refdes/model.py:101-113` for defaults;
`src/refdes/lifecycle.py:783-794` for evaluation;
`refdes-project.yaml:109-120` for the configuration shape). The proposed default
for the new rule is `{release: true, revision: false}`, so an unverified inline
result on an editable item blocks a release but not an ordinary build or a
revision stamp. Projects can opt in to the stricter `{release: true, revision: true}` if
they want.

Messages reuse existing calc phrasing where possible:

- Unit mismatch: `declared as V but the expression evaluates to A`.
- Undefined name: `unknown name 'Rtop'`.
- Missing stored result (new): `inline calc has no stored result; run 'refdes inline-calc fill' to add one`.

## 5. CLI fill/refresh command

A command for people not using the editor. It is modeled on `refdes calc-rewrite`
(`src/refdes/cli.py:2212-2246`): a transactional pass that loads the project,
evaluates every inline calc span, rewrites the bodies, reloads, and verifies
that every calc still evaluates to the same value/unit.

Proposed command shape (name is open -- Q6):

```bash
refdes inline-calc fill          # write missing/stale results
refdes inline-calc fill --check  # report stale/missing results, do not write; non-zero if any
refdes inline-calc fill --path items/decisions/dec-pwr-001.md
```

Behavior:

- Walks every local item body for inline calc spans that match the §3.2 grammar.
- Evaluates them in source order, using the same per-item env as blocks.
- For spans with no stored result or a stale stored result, rewrites the source
  text with the formatted result.
- Leaves sealed/append-only entries untouched (reports them).
- Prints one line per change: `DEC-PWR-001.md:23: Vout 4.436 V -> 4.52 V`.
- If any evaluation errors, aborts before writing anything.
- Carries baselines and seals forward the same way `calc-rewrite` does.

## 6. Live editor updates

### 6.1 What already works

The browser editor body control is a plain `<textarea>`
(`src/refdes/serve/static/editor.js:190-211`). On input it sends the candidate
body to the server, which overlays it in memory and runs the same calc/render
pipeline used by a build (`docs/design/browser-editor.md:423-431`). That path is
reused; no JavaScript evaluator is added (D3).

### 6.2 What P2 adds

After a debounced round-trip, the server returns a list of replacement ranges
for stale/missing inline results. The client applies the smallest safe change:
it selects the `= result` text inside the code span and replaces only that text,
working from the end of the body backward so offsets stay valid. It preserves
the caret by recording `selectionStart`/`selectionEnd` before the update and
adjusting them by the net length change before the cursor.

### 6.3 Caret, selection, undo, and erroring states

- **Caret inside a result being rewritten.** If the caret is inside the
  `= result` region, that replacement is skipped for this update. The user is not
  interrupted while editing the very number the tool wants to change.
- **Half-typed or erroring expression.** If a span does not parse or evaluates to
  an error, the server returns no replacement for that span and a diagnostic.
  The client leaves the text alone and shows the diagnostic via the existing W2
  squiggle overlay (`docs/design/thread-workbench.md:271-275`). It never injects
  error text into the body.
- **Undo.** The default is live auto-update while typing, but the replacement
  must use a browser-native text-insertion path that preserves undo.
  `document.execCommand('insertText')` after selecting the result range is the
  widely used, undo-preserving path in Chromium and Firefox (it is deprecated but
  still functional). `setRangeText` does **not** reliably preserve native undo
  across browsers and is not asserted to do so. A browser test is required before
  P2 ships to confirm undo behavior on the supported browsers. The explicit
  `Fill inline results` button remains the fallback if the live path does not
  preserve undo. See Q8.

## 7. Solve in place for one unknown

### 7.1 Syntax

```markdown
`Rbot := ? where Vout = 3.3 V from 1 kohm to 1 Mohm`
```

Meaning: define `Rbot` as the value in the range `1 kohm .. 1 Mohm` that makes
`Vout` evaluate to `3.3 V`, using the rest of the item's calc scope. The unknown
is the name on the left-hand side; the `where` clause is the constraint
expression and target value; the `from .. to ..` clause gives the explicit
bracket the solver needs.

### 7.2 Evaluation

The build evaluates the constraint expression as a function of the unknown over
the supplied interval, using the existing calc evaluator with the unknown
substituted by a trial `Value`. It finds a root with a standard 1-D
bracketing/Brent method. Domain errors (`sqrt()` of negative, division by zero,
etc.) inside the interval are treated as `no root in this interval` rather than
crashing the solver. If no root is found, or if the author omits the `from ..
to ..` clause, the build reports an error naming the missing bracket.

After solving, the stored result is the root value. The fill command writes it
just like any other inline result.

A constraint written as a bare name (§7.1's `Vout`) needs that name defined
earlier in the item, and to be solvable at all its definition must depend on
the unknown -- which is a forward reference under source-order evaluation. How
a span that uses a name a later solve defines is treated is open (Q14).

### 7.3 E-series suggestion

Using the divider from §8.1 (`Vref = 0.8 V`, `Rtop = 10 kohm`) and the solve
target `Vout = 3.3 V`:

```
Rbot = Rtop / (Vout/Vref - 1)
     = 10 kohm / (3.3 V / 0.8 V - 1)
     = 10 kohm / 3.125
     = 3.200 kohm
```

The exact answer, 3.200 kohm, is exactly halfway between two E96 values: 3.16
kohm and 3.24 kohm (both are 0.04 kohm away). The two candidates give:

```
Rbot = 3.16 kohm  ->  Vout = 0.8 V * (1 + 10 kohm / 3.16 kohm) = 3.332 V
Rbot = 3.24 kohm  ->  Vout = 0.8 V * (1 + 10 kohm / 3.24 kohm) = 3.269 V
```

For a 3.3 V supply rail, undershoot is usually the unsafe direction, so the
tie-break rule is: **prefer the standard value whose resulting Vout is not below
the target**. In this case that is 3.16 kohm. The tool still shows both
candidates; the author can pick the other one if the application cares more
about overshoot.

For comparison, the nearest E24 value is 3.3 kohm:

```
Rbot = 3.30 kohm  ->  Vout = 0.8 V * (1 + 10 kohm / 3.30 kohm) = 3.224 V
```

Accepting a suggested value replaces the solved value in the source with the
chosen standard value and recomputes the resulting Vout. Symbolic solve stays
out of scope, matching the existing limitation in `docs/math.md:498`.

## 8. Reusable calculators

### 8.1 Extending project equations

`equations:` in `refdes-project.yaml` currently declares single-expression,
single-output formulas (`docs/math.md:413-461`;
`src/refdes/schema.py:393-455`). This design extends it to **calculators** that
can have multiple inputs, defaults, multiple outputs, validity warnings,
tolerance-corner tables, and version pinning.

A calculator keeps the same spirit: calling it is not new code execution; the
body is evaluated by the existing calc evaluator exactly as if written inline
(`docs/math.md:436-447`).

Today's equation shape is `params:` + `expr:` (+ `note:`), enforced key by key
(`EQUATION_KEYS` at `src/refdes/configcheck.py:121`, checked at
`src/refdes/schema.py:419`), so the calculator keys below are rejected by the
current validator. How calculators coexist with existing `params:`/`expr:`
equations is open (Q15).

Proposed shape:

```yaml
equations:
  divider:
    inputs:
      Vref: { default: 0.8 V }
      Rtop: {}
      Rbot: {}
    outputs:
      Vout: Vref * (1 + Rtop/Rbot)
      ratio: Rtop / Rbot
    valid_if:
      - Rbot > 0 ohm
    note: simple resistive divider
```

### 8.2 Validity conditions

The `valid_if:` list contains **comparison constraints**, not general boolean
expressions. Each entry has the form `expression op quantity`, where `op` is one
of `< <= > >= ==` and `quantity` is a calc quantity. The calculator splits the
entry at the operator, evaluates the left-hand expression, and checks the result
against the right-hand limit using the same worst-case logic that `checks:`
already use (`src/refdes/calc.py:732-759` for `Limit.check`;
`src/refdes/calc.py:834-859` parses the limit side). A violation produces a
warning, not an error, because a calculator can describe a design intent that
the author knowingly pushes outside the recommended region.

This deliberately does **not** add general comparison operators to calc
expressions. There are no `and`/`or`, no conditional evaluation, and no
control flow; only a small, safe constraint check on each calculator call.

### 8.3 Variable-length inputs

```yaml
equations:
  parallel_r:
    inputs:
      R: { list: true }
    outputs:
      Rtotal: 1 / sum(1 / R)
```

This requires a small, safe aggregation builtin (`sum`) that operates on a list
of `Value`s. No loops, no conditionals, no user-defined functions.

### 8.4 Inputs from items or sources

Calculator inputs are ordinary calc expressions, so they can already contain:

- Cross-item references: `Rtop: CMP-RES-001.R_value`
- `source()` calls: `Vref: source('analysis/bandgap.csv', 'vref_25c') | V`

The same citation ownership and lockfile rules apply
(`docs/design/calc-sources.md:1-34`).

### 8.5 Outputs feeding checks/bounds

A calculator call in an inline span can define one or more names. Calls are
positional, in the order declared by the calculator's `inputs:`. Inputs with a
`default:` may be omitted only from the end; you cannot skip a positional
argument in the middle.

```markdown
`Vout, ratio := divider(0.8 V, 10 kohm, 2.2 kohm) = 4.436 V, 4.545`
```

In this example `Vref` has a default, but because it is the first input, the
full call must provide it. To use the default, reorder the calculator's inputs
so that `Vref` is last:

```yaml
equations:
  divider:
    inputs:
      Rtop: {}
      Rbot: {}
      Vref: { default: 0.8 V }
```

```markdown
`Vout, ratio := divider(10 kohm, 2.2 kohm) = 4.436 V, 4.545`   # Vref uses default
```

Each output name is available to later lines, `{{name}}` references, and
`checks:` the same way any calc assignment is. The exact syntax for multi-output
calls is open (Q11), and so is what a call that binds fewer names than the
calculator has outputs does (Q16).

### 8.6 Version pinning per call

To keep an old log's result from changing when a calculator is fixed, a call can
be pinned. The separator is `::` rather than `@`, because `@` is already the
repo-wide `DISPLAY-ID@key` composite separator:

```markdown
`Vout, ratio := divider::1(0.8 V, 10 kohm, 2.2 kohm) = 4.436 V, 4.545`
```

Unpinned calls use the current calculator definition. Pinned calls use the named
version. The project keeps a history of calculator versions in project config or
a lockfile. How versions are named and stored is open (Q12).

### 8.7 Shipped library

No equations ship in the bundled standard today
(`src/refdes/standards/hardware/v3/base.yaml` contains none; verified by
inspection). A later standard preset could ship a library of common calculators
(voltage dividers, RC time constants, parallel resistors, etc.). Adding that
preset is P4; it does not gate P1.

## 9. Editor form panel

A panel beside the body editor lets an author pick a calculator, fill inputs,
see the result live, and insert the inline call.

It reuses the pattern from the source-value picker
(`docs/design/editor-source-picker.md:104-125`):

1. The panel lists the project's calculators/equations.
2. Picking one shows input fields, pre-filled with defaults.
3. Inputs can be plain quantities, `{{name}}` references to existing calc
   values, cross-item references, or `source()` calls composed by the source
   picker.
4. The server evaluates the calculator live as the author types.
5. **Insert** writes the full inline span into the body draft, including the
   stored result, so the diagnostic gate can pass on save.

The Insert is a text edit, not a save. The author can still edit the inserted
line before saving.

## 10. Interaction with existing pieces

| Existing piece | Interaction |
|---|---|
| ```` ```calc ```` fences | Stay unchanged. Inline spans and blocks share the same per-item env and are evaluated in source order (`docs/math.md:30-32`). |
| `{{name}}` prose references | Can reference names defined inline, because they read the same `item.calc_values` / `_env` (`src/refdes/build.py:3091-3121`). |
| Per-item variable scope | An inline `:=` and a block assignment of the same name is the ordinary `assigned twice` error (`src/refdes/calc.py:1301-1319`; `origins`). |
| Named calc blocks | Inline spans are not blocks and have no block name. They can appear before or after named blocks. |
| `source()` / calc-sources | Valid inside inline expressions; same-item citation rule and lockfile pinning unchanged (`docs/design/calc-sources.md:1-34, §5`). |
| W5a task pane / W5b plan | The preview pane stays the published view (D2). Inline calc adds a second interaction surface: the body editor. The task pane and value decorations continue to live on the preview (`docs/design/thread-workbench.md:268-289`). |

## 11. Phasing

| Phase | Deliverables | Dependencies |
|---|---|---|
| **P1** | Inline syntax, stored-result verification, `calc_hash` extension, CLI fill command | Q1 (trigger rule), Q2 (tolerance), Q3 (scope), Q4 (calc_hash extension), Q5 (severity/gate), Q6 (command name), Q7 (sealed behavior), Q17 (inline `| unit` slot) |
| **P2** | Live editor fill button, then debounced auto-update with caret/undo handling | P1, plus Q8. |
| **P3** | One-unknown solve (`:= ? where ... from ... to ...`), E-series suggestions | P1, plus decisions on Q9-Q10 and Q14 (solve ordering). |
| **P4** | Multi-input/output calculators, version pinning, editor form panel, shipped-library preset | P1, plus decisions on Q11-Q13, Q15 (equations compatibility), and Q16 (single-name binding). |

Each phase is independently shippable and independently testable once its
dependencies are answered.

## 12. Open questions

**Q1 -- Trigger rule for inline math.** What tells the build to treat a code
span as inline math rather than an ordinary code span?
- (a) **Require `:=` in the span** (recommended). A single-backtick span that
  contains `:=` and matches the §3.2 grammar is inline math; all other spans are
  ordinary code. This is safe because a grep of single-backtick spans in `docs/`
  (excluding this design doc, fenced code blocks, and spans with more than one
  `=`) found **39 existing `NAME = value` spans** (e.g.
  `docs/math.md`: `` `V_in = LOG-PWR-001.V_in | mV` ``,
  `docs/design/backlog.md`: `` `V_cl = 0.8 V` ``,
  `docs/design/editor-image-upload.md`: `` `MAX_BODY_BYTES = 1 MiB` ``) and
  **0 spans containing `:=`** outside this design doc. Requiring `:=` therefore
  avoids misclassifying existing documentation.
- (b) **Explicit opt-in per item**, e.g. `inline_calc: true` in item front
  matter. Safe, but adds friction for every item that uses inline math.
- (c) **Mandatory leading marker** at the start of the span, such as
  `` `= ...` `` or `` `:= ...` ``. Unambiguous if required, but noisier than the
  `:=` rule and must avoid clashing with existing spans that happen to start with
  `=`.
- *Recommended default: (a).* It is the lightest rule that survives the existing
  corpus.

**Q2 -- Verification tolerance.** How tightly must the stored result match the
computed value?
- (a) Exact formatted text as produced by the tool (safe, but rejects intentional
  rounding).
- (b) Match within the stored result's own significant digits, so a hand-rounded
  `= 4.4 V` still passes if the computed value is `4.436 V` (recommended).
- (c) Match within project `sigfigs` always.
- *Recommended default: (b).* It lets authors intentionally round while still
  catching real input changes.

**Q3 -- Inline assignments in scope.** Should an inline `:=` define a variable
visible to later ```` ```calc ```` blocks and `{{name}}` references in the same
item?
- (a) Yes, full per-item scope (recommended).
- (b) No, inline spans are isolated; only blocks define variables.
- *Recommended default: (a).* It matches the existing `later lines in the same
  item` rule and makes inline math a first-class part of the calculation.

**Q4 -- `calc_hash` extension.** Should the stale-arithmetic probe hash inline
calc expression text as well as ```` ```calc ```` block contents?
- (a) Yes (recommended).
- (b) No, keep the probe block-only and add a separate inline-calc probe later.
- *Recommended default: (a).* Inline math is arithmetic; the signal should see
  it.

**Q5 -- Severity for unverified inline results.** A stale stored result is
expected for append-only log entries whose inputs moved. How should unverified
results (stale or missing) be reported?
- (a) Warning by default; promoted to a release-gate failure for non-sealed
  items when `release_gate.inline_calc_results` is enabled
  (orchestrator recommendation). Sealed items are excluded from the gate because
  they cannot be rewritten without resealing
  (`src/refdes/build.py:1505-1510`).
- (b) Error by default.
- *Recommended default: (a).* Old log entries are *supposed* to keep the number
  that was true when written; failing every ordinary build would punish that
  design intent. Blocking a release is the right place to enforce freshness.
  The gate covers both stale results and missing stored results. The proposed
  default gate rule is `{release: true, revision: false}`
  (`src/refdes/model.py:101-113`; `src/refdes/lifecycle.py:783-794`).

**Q6 -- Fill command name.** What should the CLI command be called?
- (a) `refdes inline-calc fill` (recommended).
- (b) `refdes calc-fill`.
- (c) `refdes fill-calc`.
- *Recommended default: (a).* It groups with the feature name and leaves room
  for future `inline-calc` subcommands.

**Q7 -- Fill command and sealed entries.** Should the fill command refuse to
rewrite sealed entries, or should it offer to append a corrected continuation?
- (a) Refuse and report (recommended for P1).
- (b) Offer an `--amend` mode that appends a new entry with corrected inline
  results.
- *Recommended default: (a).* Appending is a larger feature that overlaps with
  W5b continuation work.

**Q8 -- Live editor undo.** Native `<textarea>` undo is lost when JavaScript
replaces the whole `value`. Which approach do you want?
- (a) Live auto-update while typing, using `document.execCommand('insertText')`
  after selecting the result range; this is the documented undo-preserving path
  in Chromium and Firefox (deprecated but still functional). `setRangeText` is
  not asserted to preserve undo because its behaviour differs by browser. A
  browser test is required before P2 ships (orchestrator recommendation).
- (b) Explicit `Fill inline results` button only; no auto-update.
- (c) Auto-update plus a managed JS undo stack.
- *Recommended default: (a).* It preserves the live authoring feel while using
  the only path that is widely known to keep native undo. The explicit Fill
  button stays as the fallback if the browser test shows undo is not preserved.

**Q9 -- Solve bracket syntax.** Should the author provide explicit bounds?
- (a) Required `from ... to ...` (recommended).
- (b) Optional bounds, with a heuristic positive bracket as fallback.
- *Recommended default: (a).* Bracketing is the only honest way to know the
  search space, and it avoids hidden heuristic failures.

**Q10 -- E-series interaction.** Where do E24/E96 suggestions appear?
- (a) In the editor form panel and CLI output only (recommended).
- (b) Also inline in the source as alternative results stored in a comment.
- *Recommended default: (a).* Keep the source line simple; suggestions are
  presentation.

**Q11 -- Multi-output calculator syntax.** How are multiple outputs written in
an inline call?
- (a) `Vout, ratio := divider(...)` with a comma-separated result list
  (recommended).
- (b) One output per inline call: `Vout := divider(...).Vout`,
  `ratio := divider(...).ratio`.
- (c) Calculator call defines a pseudo-item and outputs are referenced as
  `divider.Vout`.
- *Recommended default: (a).* It is explicit and matches how a multi-return feels
  in prose.

**Q12 -- Calculator version pinning.** How are pinned calculator versions kept?
- (a) In a `.refdes/equations.yaml` lockfile that records each equation's
  history (recommended).
- (b) Inline in `refdes-project.yaml` as named versions under each equation.
- (c) No history; pinning is by SHA of the equation text.
- *Recommended default: (a).* A lockfile keeps project config readable and the
  history reviewable.

**Q13 -- Shipped calculator library.** Should the bundled standard grow a preset
of common calculators?
- (a) Yes, but only after P1-P3 are proven in real projects (recommended).
- (b) Ship a small library as part of P4.
- *Recommended default: (a).* The project currently ships no equations
  (`src/refdes/standards/hardware/v3/base.yaml`); let user calculators prove the
  shape first.

**Q14 -- Solve spans and source order.** A solve's constraint must reference
the unknown (§7.2 substitutes a trial value for it). Under per-item
source-order evaluation, a span that uses a name a later solve defines
(`Vout := 0.8 V * (1 + Rtop/Rbot)` written above
`Rbot := ? where Vout = 3.3 V ...`) hits `Rbot` before it is defined. How
should that be treated?
- (a) **Strict source order.** A use before the solve is the ordinary
  `unknown name` error (`src/refdes/calc.py:613-615`); solves appear before
  their uses, and a constraint that depends on the unknown spells the
  expression out in its `where` clause.
- (b) **Solve-first pass.** Solve spans are evaluated before ordinary inline
  spans in the same item, so a later solve can define a name an earlier span
  uses.
- (c) **Two-pass evaluation.** One pass collects solve roots, a second
  evaluates every span in source order with the roots available.
- *Neutral note:* (a) keeps reading order equal to evaluation order, but the
  natural write-the-equation-then-solve-below-it sheet must inline the
  expression in the `where` clause; (b) and (c) remove that friction but make
  an earlier span's stored result depend on text below it, against the
  later-lines-only scope rule (`docs/math.md:30-32`).
- *Suggested default: (a).*

**Q15 -- Calculators and the existing `params:`/`expr:` shape.** `equations:`
entries today are `params:` + `expr:` (+ `note:`), and the validator rejects
every other key (`EQUATION_KEYS` at `src/refdes/configcheck.py:121`, enforced
at `src/refdes/schema.py:419`). The calculator shape in §8.1 uses
`inputs:`/`outputs:`/`valid_if:`. How do the two coexist?
- (a) **A new equation kind, side by side.** An entry with `params:`/`expr:` is
  the existing single-output equation and keeps working unchanged; an entry
  with `inputs:`/`outputs:` is a calculator. The validator accepts either
  shape per entry and rejects mixtures.
- (b) **One kind.** The old shape is re-expressed as a one-output calculator
  (`inputs:` with the same names, one output), and existing project files are
  migrated or aliased so nothing breaks.
- (c) **Extend the old keys.** Calculators reuse `params:` -- its entries
  gaining defaults and list flags -- plus a new `outputs:`, with no `inputs:`
  key.
- *Neutral note:* (a) leaves two shapes to validate and document; (b) unifies
  but touches the validation every existing project already passes; (c)
  avoids a new key but makes a `params:` entry mean two different things.
- *Suggested default: (a).*

**Q16 -- Binding fewer names than a calculator has outputs.** §8.5 binds one
name per output. What does `Vout := divider(0.8 V, 10 kohm, 2.2 kohm)` mean
when `divider` has two outputs?
- (a) **The counts must match.** The number of names must equal the number of
  outputs; a mismatch is a build error, the way call arity is already checked
  against `params` (`docs/math.md:456-457`).
- (b) **Bind the first output.** A single name binds the calculator's first
  output; the rest are evaluated but not bound.
- (c) **Bind one selected output.** A single name binds a chosen output via a
  selector such as `divider(...).Vout` (the Q11(b) shape).
- *Neutral note:* (a) is explicit but forces authors to bind outputs they do
  not use; (b) is convenient but lets a reader assume an output was verified
  when it was only evaluated; (c) overlaps the Q11 alternative that was not
  recommended.
- *Suggested default: (a).*

**Q17 -- The `| unit` assertion in a basic span.** In a block, `name =
expression | unit` pins the display unit and asserts dimensionality
(`docs/math.md:336-354`), and the assertion is split off the line before the
assignment grammar sees it (`src/refdes/calc.py:1349-1357`) -- it is not part
of an expression, so the §3.2 basic form has no slot for it. Where does a
basic span's unit assertion go?
- (a) **After the expression, before the stored result:**
  `Vout := 0.8 V * (1 + Rtop/Rbot) | V = 4.436 V`. Same shape as a block line;
  the assertion checks dimensionality, pins the display unit, and the stored
  result is written and verified in that unit.
- (b) **No inline unit slot.** The stored result's own literal carries the
  unit, dimensionality is checked against it, and display formatting follows
  the result literal.
- (c) **Result-side pinning.** The unit is pinned by requiring the stored
  result to be written in the chosen unit (`= 4436 mV`), with no new syntax.
- *Neutral note:* (a) adds a grammar slot and a second thing to verify (the
  stored result against the declared unit); (b) is smaller but leaves a
  definition-only span (no `= result`) with no unit check at all, losing the
  use-it-where-getting-the-dimension-wrong-is-expensive guardrail
  (`docs/math.md:351-354`); (c) needs no new syntax but has no error path
  independent of the stored text.
- *Suggested default: (a).*

## 13. Alternatives considered

- **Silent auto-update of stored results.** Rejected by D1. The whole point of
  the design is that a stored number is verified, not silently refreshed.
- **A JavaScript calc evaluator in the browser.** Rejected by D3. The editor
  round-trips to `refdes serve`; Python remains the only implementation
  (`docs/design/browser-editor.md:423-431`).
- **A separate file format for inline math.** Rejected. Source files are the
  product in refdes (`docs/design/thread-workbench.md:31`); splitting math into
  another file would recreate the `edit -> build -> look over there` friction.
- **Making inline spans auto-render as live values in the published site.**
  Rejected for P1. The source already contains the result text; rendering can
  show the code span as-is. Rich overlays belong to the preview pane (D2).
