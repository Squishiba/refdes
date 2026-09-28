# `check_severity` docs gap — work log

Task: the two follow-on gaps left open by
`in-prog-logs/getting-started-green-f4.md` (§ "Not done, deliberately", items
1 and 2). Docs only: `docs/checks.md`, `docs/schema-reference.md`, and
`docs/getting-started.md` only if its link target moves.

## Environment

`refdes` not on PATH; same workaround as the F4 log — a venv:

```bash
python3 -m venv /tmp/opencode/csvgap
/tmp/opencode/csvgap/bin/python -m pip install -q -e .
/tmp/opencode/csvgap/bin/refdes --version   # -> refdes 0.5.0
```

Scratch project: `.scratch/csvgap/proj/` (gitignored). A `BND-DEN-001` bound
(`limit: "<= 0.15 W/in^2"`) and two items that fail it, each with its own calc
block (`P_dens = P_in * (1 - eff) / A_brd | W/in^2`, `P_in = 5.0 W`,
`A_brd = 3.0 in^2`):

- `DEC-PWR-001`, a `decision`, `status: accepted`, `eff = 0.88` → 0.2 W/in²
- `CMP-TPS62913`, a `component`, `eff = 0.88` → the same 0.2 W/in²

### Baseline (no overlay, nothing mapped)

```
$ refdes check
ERROR   items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — P_dens violates BND-DEN-001: worst case 0.2 W/in² vs <= 0.15 W/in^2
WARNING <project> — 1 item(s) with no coverage — see coverage.html
2 items, 1 errors, 1 warnings
[exit=1]
```

## Correction to the task brief: gap 2 is one file, not two

The brief says `docs/checks.md` (around line 177) *and*
`docs/schema-reference.md` (around line 341) both still claim `check_severity`
"must be `error`, `warning`, or `info`". Verified by grep:

```
$ grep -rn "must be \`error\`" docs/
docs/schema-reference.md:341:`check_severity` must be `error`, `warning`, or `info`. It only changes how a
```

**One** hit, in `schema-reference.md:341`. `checks.md` has no such sentence.
What `checks.md:177` actually says is `Set \`check_severity: info\` on the type
to change what a failing check is reported as:`, followed by the
`error`/`warning`/`info` table at 186-190 — an example plus a scalar-only
level table, not a false claim of exhaustiveness. So gap 2 is a true blanket
error in `schema-reference.md` only, and `checks.md` is gap 1's missing
reference material (a scalar-only level table with no pointer to the mapping
form). Line numbers otherwise confirmed as the brief stated: `lifecycle.md:68`
is the one-sentence mention, `candidate-parts.md` §4 is at line 289.

## Placement: `checks.md` § "Candidates vs. decisions", as a `###` subsection

`docs/index.md`'s nav lists Checks (line 26), Project lifecycle (line 32),
Schema reference (line 39) — and no design page, so `docs/design/candidate-parts.md`
is confirmed not linked from user-facing pages. Its §4 is the only place the
mapping form is written down, and its own docs-plan (line 775) already names
this destination: "`docs/checks.md` §Candidates vs. decisions: the mapping form
of `check_severity`, the exhaustive-or-`default:` rule, and the gate
consequence."

Read the section first. It opens "A failing check being a build error assumes
the item is a decision" — status-driven severity is the same question one level
deeper, and the existing `This only changes the diagnostic for a check that *ran
and failed*` paragraph applies verbatim to both forms. New `###` subsection
placed after that paragraph and before `## Checks that cannot be evaluated`, so
the "always errors regardless of `check_severity`" caveat stays last and still
reads as the exception to everything above it. `schema-reference.md` gets the
corrected sentence plus a link here, not a second copy.

## Verification (all run, not recalled)

### 1. `default:` is mandatory — exact wording

```
$ cat refdes-schema.yaml
types:
  decision:
    check_severity:
      superseded: info
      rejected: info

$ refdes check
configuration error: types.decision.check_severity does not cover status 'proposed'. Add it, or add default: <level>.
[exit=2]
```

Matches `schema.py:508` and the design doc's §4.3 table. Note it names the
*first* uncovered status in the field's declared choices order (`proposed`),
not the first key you happened to omit.

### 2. An unmapped status falls through to `default:`

Same overlay, now with `default: error`, `DEC-PWR-001` left at
`status: accepted` (unmapped):

```
$ refdes check
ERROR   items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — P_dens violates BND-DEN-001: worst case 0.2 W/in² vs <= 0.15 W/in^2
2 items, 1 errors, 1 warnings
[exit=1]
```

Still an error. Set it to `status: superseded` (mapped to `info`), overlay
untouched:

```
$ refdes check
WARNING items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — status is 'superseded' but nothing supersedes it ...
2 items, 0 errors, 2 warnings
[exit=0]

$ refdes check -v | grep DEC-PWR-001
INFO    items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — P_dens violates BND-DEN-001: worst case 0.2 W/in² vs <= 0.15 W/in^2
```

Demoted, not deleted. The overlay is not blanket suppression.

### 3. The shipped `component` mapping — works with **no overlay at all**

`src/refdes/standards/hardware/v3/base.yaml:259` reads
`check_severity: { candidate: info, selected: error, rejected: info, obsolete: info }`.
`refdes-schema.yaml` deleted for this test, so this is the bundled standard
alone:

```
$ refdes check                      # CMP-TPS62913 at status: candidate
ERROR   items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — ...
2 items, 1 errors, 1 warnings       # CMP-TPS62913: absent — candidate: info

$ refdes check -v | grep CMP-TPS62913
INFO    items/decisions/cmp-tps62913.md:2 [CMP-TPS62913] — P_dens violates BND-DEN-001: worst case 0.2 W/in² vs <= 0.15 W/in^2

$ sed -i 's/candidate/selected/' ... # same item, same numbers, no config change
$ refdes check
ERROR   items/decisions/cmp-tps62913.md:2 [CMP-TPS62913] — P_dens violates BND-DEN-001: worst case 0.2 W/in² vs <= 0.15 W/in^2
ERROR   items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — ...
3 items, 2 errors, 2 warnings
```

A one-word status edit moves the same failure from hidden to build-blocking.
(This is the `lifecycle.md:68` claim, confirmed by running it.)

### 4. The other three validation errors, since the page mentions the rules

```
$ # key that is not a declared status
configuration error: types.decision.check_severity key 'choosen' is not a declared status. Declared choices: proposed, in_progress, accepted, on_hold, rejected, superseded.   [exit=2]

$ # value outside the three levels, on a status key
configuration error: types.decision.check_severity[superseded] must be one of error, warning, info, got 'note'   [exit=2]

$ # mapping on a type with no status field
configuration error: types.group.check_severity is a mapping but type 'group' declares no 'status' field. Write check_severity: error, or declare status.   [exit=2]

$ # default: itself is validated like any other key
configuration error: types.decision.check_severity[default] must be one of error, warning, info, got 'shout'   [exit=2]
```

All four are load-time `SchemaError`s at exit 2 (`schema.py:462-511`).

### 5. An overlay replaces a shipped mapping wholesale

Asserted in the page, so checked rather than quoted from
`candidate-parts.md:340-342`. Overlay `component: {check_severity: info}`
(scalar) on top of the shipped mapping, with `CMP-TPS62913` at
`status: selected` — the status the standard maps to `error`:

```
$ refdes check
ERROR   items/decisions/dec-pwr-001.md:2 [DEC-PWR-001] — P_dens violates BND-DEN-001: ...
WARNING items/decisions/cmp-tps62913.md:2 [CMP-TPS62913] — status is 'selected' but nothing selects it ...
3 items, 1 errors, 3 warnings
```

CMP-TPS62913's failure is gone from the default output — the scalar replaced the
mapping, it was not merged with it. Confirmed.

### 6. `option` is not a hardware@3 type

Worth recording: the page's existing scalar example
(`types: { option: { check_severity: info } }`, `checks.md:181-184`) names a
type that `refdes new option` rejects under `standard: hardware@3`. Pre-existing
and out of this task's scope — the brief said not to restructure the page — but
it is why the sentence I added after the level table avoids naming `option` and
reads "every item of the type fails the same way" instead.

## What I wrote

- `docs/checks.md`: new `### Severity per status` in § "Candidates vs.
  decisions" — the mapping shape, the mandatory-`default:` rule with the real
  error line, the fall-through semantics, and the shipped `component` mapping
  as the worked example. A closing pointer to
  `lifecycle.md#the-readiness-gate` for the gate consequence, which
  `lifecycle.md:68` already states.
- `docs/schema-reference.md`: the `must be error, warning, or info` sentence
  corrected to name the mapping form and link to the new subsection; the table
  row's `see` target left pointing at the same section.

`docs/getting-started.md` needed no edit — it already links
`checks.md#candidates-vs-decisions`, and the new `###` subsection lives inside
that `##`, so the anchor is unchanged. Re-checked after writing, along with
every other `checks.md#` reference in `docs/` (`schema-reference.md:332` and
`:501`, plus my new `:346`) — all still resolve.

## Reading it back

Re-read the section end to end (`checks.md:168-256`). The scalar table and the
mapping subsection read as one explanation: the sentence I added right after
the table ("That is one level per *type*") names the limit the table imposes,
which is what the subsection then generalizes, so it opens by referring to that
limit rather than starting a second topic. The "Checks that could not be
evaluated at all (below) are always errors, regardless of `check_severity`"
paragraph stayed last, immediately above the `##` section it forwards to, so it
still reads as the exception to everything above it — which is correct, and now
correctly scoped over both forms rather than only the scalar one.

## Status

Complete. Two files edited, one `changelog.d/` fragment, this log. Nothing left
undone inside the brief's scope.

## Note for the report (not a task change)

1. `docs/standard-library.md:475-487` already describes `component`'s shipped
   mapping in hardware@3 terms, so the mapping form now has a user-facing home
   in two senses: how to write one (`checks.md`) and what the bundled standard
   ships (`standard-library.md`). The F4 log's item 2 is closed. I did not
   cross-link `standard-library.md` — that page is about what a version of the
   standard changed, not about the key, and `checks.md` is where the key is
   documented.
2. `changelog.d/getting-started-superseded-check-severity.fixed.md` (merged by
   the F4 task) still says "the check records what was true when the decision
   was made". That is the wording trap its own log §4b caught and avoided in
   the page; the bound is re-read live, only the decision's own calc values are
   frozen. `release.py` will fold that sentence into `CHANGELOG.md` as written.
   Not my file and not my brief, so left alone.
3. `docs/checks.md:181-184`'s scalar example uses an `option` type, which
   hardware@3 does not declare (see verification 6). Pre-existing.
