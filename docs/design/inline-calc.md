Status: **Proposed, design only; open questions decided.** This document
specifies the first inline-calc slice. No parser, evaluator, CLI, or editor
implementation is in this PR. The owner decided the four open questions on
2026-10-17; the decisions are recorded under each question below. Later
directions are parked in [inline-calc-later.md](inline-calc-later.md).

# Inline calc: stored results in item prose

## Owner decisions

- **D1:** The result is source text. `refdes check` and `refdes build` verify it
  and report a stale value ("says 4.436 V, now computes 4.52 V"); neither
  silently rewrites it.
- **D2:** The preview pane remains an optional "as published" view.
- **D3:** Evaluation uses only the restricted Python calc evaluator in
  `src/refdes/calc.py`; an item cannot execute code.

## Current baseline, verified for this proposal

- Probe: in a fresh `refdes init` project holding one `log` item whose body
  is the single-backtick span `` `Vout := 2 V * 2 = 5 V` ``, `refdes check`
  reported 0 errors despite the deliberately wrong result. Inline-calc
  evaluation is therefore **proposed**, not current behavior.
- `src/refdes/build.py:_run_item_calcs` evaluates calc fences with one item
  environment and one duplicate-name registry. `src/refdes/calc.py:evaluate_block`
  handles assignment, `| unit`, tolerances, cross-item value references, and
  `source()` with their existing restrictions. `docs/math.md` describes the
  author-facing forms. This proposal reuses those paths; it adds a code-span
  input to them.
- `docs/math.md` and `docs/design/named-calc-blocks.md` document the landed
  `id="name"` calc fence, `[[ID#calc:name]]` link, and `{{calcblock}}` page
  directive. Their block names label renderings, not value scopes. Inline
  spans do not acquire block names.
- `src/refdes/build.py:_hash_payload`, `calc_hash_for`,
  `_calc_reference_values`, and `_calc_refs_hash_value` currently inspect body
  text and/or calc **fences** as described below; none discovers inline
  assignments. `src/refdes/lifecycle.py:_stale_arithmetic` compares
  `calc_hash` only for its verdict-change signal, not for stored-result
  verification.
- `refdes check --help`, `refdes build --help`, `refdes release --help`, and
  `refdes revision --help` confirm the present commands. Their proposed
  behavior below is not yet shipped. `refdes schema` emitted the current
  project's merged JSON Schema; no new field or gate rule is assumed to exist.

## 1. Source form and trigger

The first slice recognizes a single-backtick Markdown code span in a **local
item body**, outside fenced code. It is inline calc if its content contains an
unquoted `:=`. **Recommended** (open question 4): once triggered, a malformed
span is an error at its source line; it cannot fall back to ordinary code. A
span without `:=`, such as `` `V_cl = 0.8 V` ``, remains ordinary code.
Multi-backtick spans and page bodies are outside this slice. This trigger is
proposed; the probe above shows it is not implemented today. Existing
item-body examples that literally use `:=` in a single-backtick span need a
multi-backtick span to stay ordinary code when this syntax lands.

```text
span          = "`" name wsp ":=" wsp rhs [wsp "|" wsp unit]
                wsp "=" wsp result "`"
name          = [A-Za-z_][A-Za-z0-9_]*
rhs           = one existing calc assignment right-hand side
unit          = one existing calc unit assertion
result        = one numeric quantity literal, optionally with unit
wsp           = one or more spaces or tabs
```

The `= result` delimiter is the final top-level ` = `: the parser must ignore
`=` inside quoted `source()` arguments or parentheses. The right side of that
delimiter must be a **literal**, not another expression. The result stores the
nominal value; uncertainty stays in the evaluated value and is rendered by
existing calc presentation. The evaluator accepts exactly the existing RHS
forms and restrictions; this slice adds no solve operator, comparison,
function, or executable language (`src/refdes/calc.py:evaluate_block`,
`evaluate_assignment`, `_evaluate_source_line`).

```markdown
`Vout := 0.8 V * (1 + Rtop/Rbot) | V = 4.436 V`
`I_load := 1.2 A = 1.2 A`
`V_cl = 0.8 V`                 <!-- ordinary code: no := -->
```

The unit assertion belongs between the expression and stored result, mirroring
`name = expression | unit` in `docs/math.md` and
`src/refdes/calc.py:evaluate_block`. It checks dimensionality and pins the
evaluated value's display unit. The stored literal may use any compatible
unit; verification converts it before comparing. For `source()` the assertion
is mandatory, as in `src/refdes/calc.py:_evaluate_source_line`; there, per that
function's comment (`src/refdes/calc.py:1616-1618`) and `docs/math.md`
("Reading a value from a source file"), the unit **labels** the file's bare
number -- no dimensionality check runs on the file's value.

An inline `:=` assigns into the same item-wide environment as calc fences, in
**source order across spans and fences**. A later fence can use the inline
name; a later inline span can use an earlier fence name. A duplicate assignment
is an error citing both lines; a forward use is an ordinary unknown-name error
(`src/refdes/build.py:_run_item_calcs`, `src/refdes/calc.py:evaluate_block`).
`{{name}}` can render the assigned value after evaluation, as it already does
for fence values (`src/refdes/build.py:render_bodies`). A span remains the
literal code span in published Markdown; it does not become a second calc
block or a `{{calcblock}}` target.

## 2. Verification and diagnostics

Every triggered span requires a stored result. `check` and `build` evaluate the
RHS with `src/refdes/calc.py` and parse the stored literal as a standalone
quantity (`parse_quantity`). They compare **nominal values** after converting
to compatible units; the RHS tolerance interval remains on the assigned value
and is not a license for the stored nominal to drift. `check` and `build` do
not edit the source (D1). The ordinary calc failures, including undefined
name, incompatible unit, invalid `source()` pin, and duplicate assignment,
remain errors at the span's file and line
(`src/refdes/calc.py:evaluate_block`; `src/refdes/build.py:_run_item_calcs`).

**Recommended numeric tolerance:** use the stored literal's last written
place, including trailing zeros and any decimal exponent. Accept a computed
nominal within half one unit of that place after unit conversion. Thus
`4.4 V` accepts `4.436 V` (half-place is `0.05 V`), while `4.436 V` rejects
`4.52 V` (half-place is `0.0005 V`). Dimensionless results use the same rule.
Compare numerically, never by formatting text with `project.sigfigs`: that
setting controls display formatting (`src/refdes/calc.py:format_value`) and
must not change whether stored source is true. A malformed or nonfinite
stored literal is an error. **Recommended tie rule:** at a boundary tie, round
the computed nominal to the stored literal's last written decimal place on the
decimal text, rounding halves away from zero, and accept only when the rounded
value equals the stored literal; carry tests at the half-place boundary.

| Condition | Proposed severity and message shape |
|---|---|
| Missing `= result`, malformed triggered span, evaluation failure, incompatible unit | **Error**, file:line plus name and specific fix; ordinary `check`/`build` fail. Example: `inline calc Vout: stored result missing; write '= <quantity>'`. |
| Parsed result outside its precision window | **Warning** at `check`/`build`; by default `release_gate.inline_calc_results` also fails a release for an editable item. Example: `inline calc Vout: stored result says 4.436 V, now computes 4.52 V`. |
| Result within its precision window | No diagnostic. |

A stale value is reported on every verification run, including an old
append-only entry; that historical text is not rewritten (D1). The
`release_gate.inline_calc_results` rule fails a **release** for stale
editable items, with default `{release: true, revision: false}`. An item the
build locks as a seal, and an item whose live content still matches an
unedited capture
(`capture_index[key][1] is False`), is exempt from this freshness gate, while
its warning remains visible. The capture exemption follows the entry's captured
text, not the upstream inputs it referred to; a later upstream move can make
the frozen prose describe a different calculation, and the gate remains silent.
A post-capture edit leaves the live item
editable, so the exemption does not apply to the edited entry. Landed:
`src/refdes/model.py:RELEASE_GATE_DEFAULTS` lists it,
`src/refdes/lifecycle.py:_rule_inline_calc_results` reads the build's stale
warning (tagged `model.INLINE_CALC_STALE`), resolves it by display id and,
for permanently id-less continuations whose diagnostic has an empty id, by
the body range containing the span (with a list-file entry-line fallback),
fails closed if a coded stale warning resolves to no local item, and exempts entries
`seal.is_sealed` and `history.capture_index` report. With a stale span in
play, the rule deliberately fails closed on an unreadable history store and
names that
store: a release cannot stamp a readiness claim while the tool is unable to
prove the frozen-text exemption. The store's read failure has its existing
ordinary `check`/`build`
warning posture, while the release gate refuses the unprovable exemption.
The rule reports the warning's own source line: the span line in Markdown,
falling back to the item's entry line for a list-file `body:` key.
`refdes release --help` lists the rule. Missing results and calc errors enter
the ordinary build error floor. `refdes revision --help` describes the
revision as unconditional apart from that floor; the revision half defaults
false.

## 3. Hashes, dependencies, and historical entries

| Concern | First-slice behavior |
|---|---|
| Item content hash | The authored span, including stored result, is body text. When the type's body `on_change` mode is `invalidate`, an edit to it changes the item hash under `src/refdes/build.py:_hash_payload`; other modes keep their existing meaning. A result correction is a real source edit, not a hash-neutral rewrite. |
| `calc_hash` | Extend `src/refdes/build.py:calc_hash_for` to include inline **name, RHS and unit assertion in source order**, excluding the stored result. An inline-only item then has a `calc_hash`; changing only the result leaves that probe fixed. Preserve today's block-only hash value for an item without inline spans, so old baselines do not churn. `src/refdes/lifecycle.py:_stale_arithmetic` can then use the same verdict-change signal for inline arithmetic. A stale-result warning comes from direct verification, regardless of baseline or verdict. |
| Cross-item inputs | An inline RHS may use an existing cross-item value reference under the same restrictions as a fence line. Extend the dependency scan, composite-key refresh, baseline snapshot, and content-hash input collection to those spans. Today the relevant scans cover fences (`src/refdes/build.py:_calc_reference_targets`, `_calc_reference_values`, `run_calcs`); omitting this extension would evaluate the wrong order or miss an upstream change. An upstream value change can move the dependent hash and produce a stale-result warning even when its authored text is untouched. |
| `source()` inputs | If used as the whole RHS with `| unit`, extend the `refdes fetch` discovery and source-value hash input collection to inline spans. Keep the existing same-item citation and lockfile rules (`src/refdes/calc.py:_evaluate_source_line`, `src/refdes/citations.py:collect_source_uses`, `src/refdes/build.py:_source_inputs_hash_value`; `docs/math.md`, "Reading a value from a source file"). No new file reader is introduced. |
| Seals and captured history | Verification is read-only for both. A changed stored literal in a build-sealed entry remains subject to the existing seal check (`src/refdes/seal.py:verify`); a history-backed entry keeps the existing capture/edit signal (`src/refdes/history.py`, `src/refdes/build.py:warn_edited_after_captured`). No automatic reseal or recapture is part of this slice. |

The authored span already enters the body hash where body invalidation is on.
Adding its resolved cross-item or `source()` inputs changes the **item** hash
definition for affected items and needs a new hash-format version (current
`HASH_FORMAT` is 5 in `src/refdes/build.py`). Reconstruct old hashes through
`src/refdes/build.py:hash_payload_builder` and `src/refdes/lifecycle.py` when
comparing existing baselines and seals. Existing no-inline items should retain
their old item hash. The `calc_hash` extension is separate: old baselines
without that probe stay silent in the verdict-change signal
(`src/refdes/lifecycle.py:_stale_arithmetic`).

## Open questions for this slice (decided by the owner, 2026-10-17)

1. **Precision (was Q2):** Is half of the stored literal's last written place the right
   acceptance window, including coarse literals such as `4 V`? **Recommended
   default:** yes; authors choose visible precision, and `4.0 V` tightens it.
   **Decided (2026-10-17):** the recommended default is accepted.
2. **Freshness gate (was Q5):** Should stale editable results fail release while old
   sealed or captured results only warn? **Recommended default:** yes, using
   `release_gate.inline_calc_results` with `{release: true, revision: false}`.
   **Decided (2026-10-17):** the recommended default is accepted.
3. **Unit slot (was Q17):** Should `| unit` precede `= result`? **Recommended default:**
   yes; it matches the landed calc line and keeps assertion independent of
   stored presentation (`docs/math.md`, "Display units").
   **Decided (2026-10-17):** the recommended default is accepted. Calcpad
   writes the unit after the number and `expression|unit` converts the result
   to that unit before `= result` (e.g. `1.23 m + 35 cm + 12 mm|cm` gives
   `159.2 cm`; <https://calcpad.eu/help/64/units>), the same slot as this
   design's `name := expression | unit = result` with the same conversion
   meaning. The two `|` are not identical: refdes's `|` also asserts
   dimensionality and pins the display unit (`docs/math.md`, "Display units").
4. **Triggered incomplete text (was Q1):** Should a span with `:=` but no valid result
   be an error? **Recommended default:** yes; D1 requires a verified stored
   result. This reverses the old draft's Q1(a), which left spans not matching
   the grammar as ordinary code; this slice treats `:=` as declared intent
   that must never be silently ignored. The editor may show this as an
   in-progress diagnostic, but no editor behavior is specified here.
   **Decided (2026-10-17):** the recommended default is accepted; the
   reversal of the old draft's Q1(a) default stands.

Implementation and review of solving, suggestions, fill/refresh tooling,
live editor changes, calculator definitions and lockfiles, and the form panel
are deferred to [direction notes](inline-calc-later.md).
