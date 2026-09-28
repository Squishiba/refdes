# docs accuracy nits — work log

Task: two small, independently-flagged doc corrections.

1. `docs/checks.md`'s scalar `check_severity` example names a type that
   hardware@3 does not declare (`option`).
2. `changelog.d/getting-started-superseded-check-severity.fixed.md` overstates
   what a superseded decision's check result freezes.

Both were side findings in `in-prog-logs/check-severity-docs-gap.md` (§6 and
§ note 2) and `in-prog-logs/getting-started-green-f4.md` (§4b). Both read in
full first. Neither taken on trust — everything below was re-run.

## Environment

`refdes` **is** on PATH here, but `pip show` says it is an editable install
pointing at a *different* worktree:

```
$ pip show refdes | grep -i editable
Editable project location: /home/jorb/.paseo/worktrees/16msma8v/user-sim-release-gate-run2b
```

So the PATH `refdes` is another session's checkout. Made a venv here instead,
same workaround as the F4 and csvgap logs:

```bash
python3 -m venv /tmp/opencode/dan
/tmp/opencode/dan/bin/python -m pip install -q -e .
/tmp/opencode/dan/bin/refdes --version   # -> refdes 0.5.0
```

Scratch: `.scratch/dan/` (gitignored) and `/tmp/opencode/{super,cmpcheck,optcheck}`.

---

## Fix 1 — `option` is not a hardware@3 type

### The type list, from two independent places

`src/refdes/standards/hardware/v3/base.yaml:174` `types:` — seven keys, at
lines 175, 192, 218, 240, 253, 278, 289: `requirement`, `bound`, `decision`,
`test`, `component`, `group`, `log`. No `option`.

`refdes schema` in a fresh `refdes init` project (pinned `standard: hardware@3`):

```
$ refdes schema | python -c "... d['$defs'] ..."
TYPES: ['bound', 'component', 'decision', 'group', 'log', 'requirement', 'test']
option present: False
```

The brief's list is right.

### What the `option` example actually did to a reader

Worth recording, because it is worse than "a type that does not exist" — it is
a *silently loadable* one. An overlay naming an undeclared type is not
rejected; it synthesises a bare, fieldless type:

```
$ printf 'types:\n  option:\n    check_severity: info\n' > refdes-schema.yaml
$ refdes check
0 items, 0 errors, 0 warnings            [exit=0]
```

and `refdes schema` grows `option__bare` / `option__entry` defs with no
`fields`, no `status`, `additionalProperties: true`. So a reader who copies
`checks.md:180-184` verbatim gets a config that loads clean, passes CI, and
changes nothing — a new inert type, not an overlay of the candidates they were
aiming at. That is worse feedback than a load error, and it is a good argument
that the name had to be a real one.

### `component` is the right name, and the snippet works verbatim

`component` is the only hardware@3 type with a `candidate` status
(`base.yaml:264`, choices `candidate, selected, rejected, obsolete`), so it is
the only one the surrounding prose can be about. The section opens on
"comparing several microcontrollers against a shared `BND-IO-008 (>= 2 DACs)`"
— a part comparison, i.e. `component`, not a hypothetical type.

Wrote the exact snippet I intended into the doc, verbatim, and ran it —
`.scratch/dan`-adjacent `/tmp/opencode/cmpcheck`: `CMP-TPS62913`, a `component`
at `status: candidate`, failing `BND-IO-008 (>= 2 count)` with `n_dac = 0`:

```
$ refdes check
WARNING <project> — 1 item(s) with no coverage — see coverage.html
2 items, 0 errors, 1 warnings                                  [exit=0]

$ refdes check -v | grep CMP-TPS62913
INFO    items/decisions/cmp-tps62913.md:2 [CMP-TPS62913] — n_dac violates BND-IO-008: worst case 0 count vs >= 2 count
```

The example does what the page says it does.

### The one thing that did need adjusting

Naming `component` couples this example to the `### Severity per status`
subsection 20 lines below, which says "The bundled standard ships exactly this
for `component` — under `standard: hardware@3`, with no overlay of your own"
and shows its mapping. Under the fictional `option` those were unrelated; under
`component` the reader has just written an overlay of the same type and would
hit that as a non-sequitur.

Worse, it is a real behavioural trap, confirmed by running it: `component`
ships `check_severity: { candidate: info, selected: error, rejected: info,
obsolete: info }` (`base.yaml:259`), and a **scalar** overlay replaces that
mapping wholesale — it is not merged. So the doc's scalar example, if copied
verbatim, silently drops the standard's `selected: error` and demotes
*selected* parts too. Verified by flipping `CMP-TPS62913` to `status: selected`
with the overlay in place: still `0 errors`, no build break.

So I added one clause to the existing "That is one level per *type*" sentence
pointing at `#severity-per-status`. The page already states the replacement rule
at line 246; the clause makes the reader meet it as a consequence of the
example they just read rather than as a surprise 40 lines later. Nothing else
in the section needed touching — the prose already calls the items *candidates*
and says "a candidate that fails a criterion", which is `component` throughout.

**The clause names `hardware@3`, not "the bundled standard", deliberately.**
`check_severity` across the three shipped standards:

```
v1/base.yaml:76:   check_severity: error
v2/base.yaml:122:  check_severity: error
v3/base.yaml:224:  check_severity: error          # decision
v3/base.yaml:259:  check_severity: { candidate: info, selected: error, rejected: info, obsolete: info }   # component
```

`component`'s *mapping* ships only in `hardware@3`; v1 and v2 ship a scalar. So
"replaces the mapping the standard ships" would be false for a v2-pinned
project — there is no mapping to replace, only a scalar to overwrite. The page
already qualifies its one version claim this way at line 235 ("under `standard:
hardware@3`"), so the clause matches the page's own convention.

### Reading it back

Re-read `checks.md:168-259` end to end. The new clause lands the reader at
`### Severity per status` already expecting to be told that a scalar overlay
wins over the shipped mapping, so line 246 ("An overlay that names `component`
replaces that mapping wholesale — it is not merged with it") now reads as the
second half of a setup rather than an isolated warning. `grep -n option
docs/checks.md` → no hits; the section's only type names are now `component`,
`decision` and `group`, all declared.

---

## Fix 2 — the bound is re-read live; only the decision's numbers are frozen

The brief's claim, verified end to end in `/tmp/opencode/dan/super` (mirrors
the F4 walkthrough: `BND-THM-001 (limit: "<= 0.15 W/in^2")`, `DEC-PWR-001` with
the `P_dens = P_diss / A_board | W/in^2` calc, then `DEC-PWR-002` superseding
it).

**A — `DEC-PWR-002` supersedes `DEC-PWR-001`, but 001 is still `accepted`:**

```
$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING items/decisions/dec-pwr-002-regulator.md:2 [DEC-PWR-002] — supersedes DEC-PWR-001, but that item's status is 'accepted', not 'superseded' ...
3 items, 1 errors, 2 warnings                                   [exit=1]
```

**B — `DEC-PWR-001` set to `status: superseded`. Still an error, as the
fragment says:**

```
$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
3 items, 1 errors, 1 warnings                                   [exit=1]
```

**C — the whole point. Edit *only* `BND-THM-001`'s limit, `0.15` → `0.13`.
The decision file is not touched:**

```
$ grep -n 'limit' items/bounds/thermal.yaml
    limit: "<= 0.13 W/in^2"

$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.13 W/in^2
3 items, 1 errors, 1 warnings                                   [exit=1]

$ grep -n 'eff\|status' items/decisions/dec-pwr-001-regulator.md
6:status: superseded
18:eff              = 0.93
```

The reported limit moved `0.15` → `0.13` for a decision whose file did not
change. The **value** stayed `0.2366` — that is the decision's own frozen calc
result. So the split is exactly as claimed: the item's numbers are on the
record, the bound is re-read.

**D — and the outcome is not frozen at all, only the numbers.** Loosen the
bound past the old decision's margin and its failure disappears entirely:

```
$ # limit: "<= 0.30 W/in^2"
$ refdes check
WARNING items/bounds/thermal.yaml:6 [BND-THM-001] — body: is empty ...
3 items, 0 errors, 1 warnings                                   [exit=0]
```

No `DEC-PWR-001` line anywhere. A superseded decision is re-evaluated against
the current bound, every run. "The check records what was true when the
decision was made" is false in both directions — the margin, the pass/fail,
and even whether the item is reported at all are all live.

The doc text this fragment describes already has it right
(`docs/getting-started.md:279-280`): "the decision's own numbers stay on the
record". The fragment is the drifted copy; the fragment is what
`release.py:283` will paste into the released `## [Unreleased]` body verbatim
(it replaces the whole region between the `## [Unreleased]` heading and the
next `## `), so the correction has to land here.

Fragment is still pending, confirmed: `grep -c "Superseding" CHANGELOG.md` → `0`.
Safe to edit directly, no correction entry needed.

---

## Verification

- `refdes schema` (clean `hardware@3` project) and `base.yaml:174` both give
  `bound, component, decision, group, log, requirement, test`. No `option`.
- The fix-1 snippet, verbatim, run against a real failing `component`:
  `0 errors, exit 0`, and `check -v` shows the demoted `INFO`. Correct.
- The fix-2 repro (steps A-D above) pasted inline; the tightened bound changes
  the old superseded decision's reported limit `0.15` → `0.13` with the
  decision file untouched, and loosening it past the margin removes the
  finding entirely (`exit=0`). So neither the margin nor the pass/fail is
  frozen — only the item's own calc values are.
- `pytest tests/ -q` → **2736 passed, 2 skipped** (191s). Needed
  `pip install -e ".[dev]"`; a bare venv has no pytest and the suite's
  `test_citation_sections.py` / `test_schema_json.py` need `pypdf` /
  `jsonschema` from the `dev` extra.
- Doc/link tests re-run in isolation after the anchor was added:
  `pytest -k "link or doc or anchor or nav"` → 332 passed.
- `grep -n option docs/checks.md` → no hits. `grep -c Superseding CHANGELOG.md`
  → 0, so the fragment was still pending when edited.
- Both edited passages re-read in full for internal consistency (above).

## Status

Complete. Two files edited as scoped, plus this log. No `changelog.d/` fragment
added — this is a correction to an unreleased fragment plus a doc-accuracy fix,
not new user-visible behavior.
