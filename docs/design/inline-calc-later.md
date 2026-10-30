# Inline calc later: not under review; direction notes only

**Not under review; direction notes only.** These are the deferred ideas from
the earlier 839-line proposal. None is implemented or required to ship the
[first slice](inline-calc.md) — with one exception since: the *Live editor
updates* note has been implemented, and its status line below records the
decisions it landed with. Syntax, defaults, and examples here are leads for
later design, not decisions made by that slice.

## Result-writing command

A possible `refdes inline-calc fill` command writes missing or stale stored
results after evaluating the whole project. Candidate options were `--check`
(report only, nonzero for missing/stale) and `--path` (one item file). The pass
would be transactional: abort all writes on an evaluation error, reload and
verify results afterward, print each changed file:line and old/new quantity,
and refuse to rewrite build-sealed or captured historical entries. The older
proposal borrowed the rollback idea from the existing `refdes calc-rewrite`
(`refdes calc-rewrite --help`). A command name, historical-entry policy, and
baseline/seal handling need a separate review; result-writing is not needed
for hand-authored first-slice spans.

## Live editor updates

**Status: implemented 2026-10-30** — PRs #386 (the read-only
`POST /api/item/<ref>/calc` route), #387 (field references in calc spans)
and #388 (panel, auto-fill and Fill in the browser editor), designed in
`in-prog-logs/inline-calc-live-editor-design-20261020.md`. The owner
decisions it landed with (§6 of that design): evaluation is keystroke-driven
on a 400 ms debounce, with a flush on blur and on focus; the panel sits
under the body textarea, beside the pickers; auto-fill fires on the
checker's `stale` verdict only (never on every computed/stored difference),
default ON behind a per-browser `localStorage` toggle
(`refdes.live-calc.autofill`); the manual Fill button stays as the fallback
and is idempotent; native undo rides `document.execCommand('insertText')`,
browser-tested on Chromium and Firefox — where it proves unavailable, the
panel says native undo may not cover the fills and auto-fill stands down
for the session; the preview pane keeps the as-published view of saved text
(owner D2), and `check`/`build` remain the verdict. The direction text
below stands as the record of what was proposed.

The possible editor flow is a debounced request to the Python server for
replacement ranges, never a browser copy of the calc evaluator (owner D3).
Apply replacements from the end of the body, adjust selection offsets, and
skip any result the caret is inside. Half-typed or failing expressions leave
the draft unchanged and show a diagnostic. Native undo is the unresolved
constraint: the previous proposal suggested `document.execCommand('insertText')`
for the selected range, with a browser test before shipping and a manual Fill
button if undo cannot be preserved. `setRangeText` was not assumed to preserve
undo. The preview pane remains the optional "as published" view (owner D2).

## One-unknown solving and E-series

A candidate solve span was
`` `Rbot := ? where 0.8 V * (1 + 10 kohm/Rbot) = 3.3 V from 1 kohm to 1 Mohm` ``.
The unknown is the assigned name; explicit bounds give a one-dimensional root
search.

**Range symbol, DECIDED 2026-10-17 (owner): `…`, with ASCII alias `..`, as
recommended below; the rest of the solve design is not under review.** The
owner wanted a symbol for the range, not the words
`from ... to ...` — e.g. something like `1k ~ 10k ohm` — and asked what math
normally uses. Weighing the candidates: refdes already prints tolerance
intervals as `11.4 V … 12.6 V` (`docs/math.md`, "Tolerances"), and its
tolerance sign already has an ASCII alias pattern (`±` / `+/-`,
`src/refdes/calc.py:689`); `~` is common on datasheets ("1k~10k") but also
reads as "approximately", and no calc-syntax use of it exists in
`src/refdes/calc.py` today; `[a, b]` is math's closed-interval notation. The
choice is `…` with ASCII alias `..`, mirroring the
`±` / `+/-` alias pattern and the existing interval display. This supersedes
the earlier `from ... to ...` spelling above (old Q9); the explicit bracket
itself stays required. A trial value would be passed to the existing restricted evaluator,
with domain errors and absent roots reported, not crashed. Source-order use
before a solve remains open; the earlier default was strict order, so the
constraint spells out the expression instead of referencing a forward-defined
`Vout`. A root would become the stored result through a later writing path.

The earlier divider example gives an exact `Rbot = 3.200 kohm`. Its E96
neighbors are `3.16 kohm` (`Vout = 3.332 V`) and `3.24 kohm`
(`Vout = 3.269 V`); E24's nearby `3.30 kohm` gives `3.224 V`.
The suggested tie break was to show both E96 neighbors and prefer the one
whose output does not undershoot the 3.3 V target. Suggestions would appear
in editor/CLI presentation rather than be stored as alternate source values.
Whether that tie break fits other circuits needs review. Symbolic solve was
never proposed.

## Reusable calculators and pins

A later calculator could extend project `equations:` from today's
`params:`/`expr:` single-result entries (`docs/math.md`, "Project equations";
`src/refdes/schema.py` equation validator). This is a **proposed new shape**:

```yaml
equations:
  divider:
    inputs:
      Rtop: {}
      Rbot: {}
      Vref: {default: 0.8 V}
    outputs:
      Vout: Vref * (1 + Rtop/Rbot)
      ratio: Rtop / Rbot
    valid_if:
      - Rbot > 0 ohm
    note: simple resistive divider
```

An inline call might bind both outputs:
`` `Vout, ratio := divider(10 kohm, 2.2 kohm) = 4.436 V, 4.545` ``.
Inputs were positional, with optional defaults only at the end; output-name
count matching output count was the recommended default. Outputs would feed
later calc, `{{name}}`, and checks. Calculator inputs could be ordinary calc
expressions, cross-item values, or pinned `source()` values under their
existing citation rules (`docs/math.md`, "Referencing another item's values"
and "Reading a value from a source file").

`valid_if` meant a list of comparison limits checked at tolerance corners,
producing a warning on violation, without adding general boolean expressions
or control flow. Variable-length inputs would need a restricted list value and
aggregation such as `sum`; that is an evaluator extension to review, not a
promise that current equations accept it. A project equation could call
another, while a future calculator could return multiple values.

A call-specific pin was sketched as `divider::1(...)`, with a proposed
`.refdes/equations.yaml` lockfile recording equation versions. Unpinned calls
would use the current definition; pinned calls the recorded one. The `::`
separator avoids the existing `DISPLAY-ID@key` spelling. The earlier draft
suggested a shipped standard calculator library only after project-defined
calculators prove the API. The current bundled standard is `hardware@3` and
is unreleased (`CHANGELOG.md` [Unreleased]; a fresh `refdes init` in an empty
directory printed `standard: hardware@3`).

## Editor form panel

A later panel beside the body editor could list project calculators, show
inputs with defaults, accept quantities, existing calc values, cross-item
references, and source-picker results, ask the Python server for a preview,
and insert a complete span with a stored result into the draft. Insert would
be a text edit, not a save. This was modeled on
`docs/design/editor-source-picker.md`; its exact UI and update behavior need
their own review.

## Deferred decisions from the earlier draft

| Earlier question | Direction recorded, still open |
|---|---|
| Q3, inline scope | Not deferred here: resolved into the first slice — its section 1 assigns inline `:=` into the item-wide calc scope in source order (old Q3(a)). |
| Q4, `calc_hash` | Not deferred here: resolved into the first slice — its section 3 `calc_hash` row extends the probe over inline name, RHS and unit (old Q4(a)). |
| Q5, severity | Not deferred here: resolved into the first slice — its section 2 severities and its open question Q2 (was Q5). |
| Q6-Q7, command | `refdes inline-calc fill`; refuse historical edits and report them. |
| Q8, editor undo | Try native text insertion, test undo in supported browsers; retain manual Fill fallback. |
| Q9-Q10, solve | Require explicit bracket; its spelling is a range symbol, `…` (ASCII `..`), decided by the owner 2026-10-17, not the words `from ... to ...` — see the note in "One-unknown solving and E-series". Keep E-series suggestions in UI/CLI. |
| Q11, Q16, outputs | Comma-separated names/results; require output count match. |
| Q12-Q13, versions/library | Separate equation-history lockfile; delay bundled presets. |
| Q14, solve ordering | Strict source order until a later design justifies another pass. |
| Q15, equation coexistence | Keep `params:`/`expr:` entries and add a separate calculator shape; reject mixed keys. |

The old P2-P4 sequence was editor updates, then solving/E-series, then
calculators, their pins/library, and the form panel. That sequence is a
planning note only; the first slice has no dependency on it.
