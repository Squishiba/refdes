# getting-started green-build signpost (F4) — work log

Task: `docs/getting-started.md` only. Add a short, clearly-marked explanation
of why the walkthrough's build stays red after the reader supersedes the
failing decision, plus the `check_severity` overlay that turns it green.

Source finding: `in-prog-logs/user-sim-release-gate-run1.md` §2 F4, read in
full. The task text's summary was not trusted; F4 verified end to end below.

## Environment

`refdes` was not on PATH. Worked around the editable-install issue the way
`in-prog-logs/user-sim-release-gate-run1.md` did — a venv with
`pip install -e .`:

```bash
python3 -m venv /tmp/opencode/f4venv
/tmp/opencode/f4venv/bin/python -m pip install -q -e .
/tmp/opencode/f4venv/bin/refdes --version   # -> refdes 0.5.0
```

Then `export PATH="/tmp/opencode/f4venv/bin:$PATH"` in each command below.
Scratch project: `.scratch/f4/my-board/` (gitignored). Nothing outside
`.scratch/`, `docs/getting-started.md`, `in-prog-logs/`, and a
`changelog.d/` fragment was touched.

## Pre-work: does a `check_severity` reference already exist?

`ls docs/*.md` then `grep -rn check_severity docs/*.md`. Findings:

| file:line | what it covers |
|---|---|
| `docs/checks.md:177-199` (§ "Candidates vs. decisions") | the **scalar** form, and the level table. The anchor `checks.md#candidates-vs-decisions` is what `docs/schema-reference.md:332` already points at. |
| `docs/schema-reference.md:332, 341-344` (under `## types`) | the type-key reference row for `check_severity`, states the default is `error`. |
| `docs/lifecycle.md:68-70` | one sentence: "`check_severity:` may be written as a mapping from `status` to level (docs/design/candidate-parts.md §4), and this rule resolves it per item, not per type." |
| `docs/standard-library.md:475-487` | what `component`'s shipped mapping is, in hardware@3 terms. |
| `docs/design/candidate-parts.md:289-345` | the design doc for the **mapping** form, including the error strings. |

So: a user-facing reference **exists** for the scalar form, and the mapping
form is documented in full only in `docs/design/` (plus a one-line mention in
`lifecycle.md`). My page adds no new reference material — it points at
`checks.md#candidates-vs-decisions` and `schema-reference.md#types`.

Gap noted but **not** fixed here (would be a second docs task): `checks.md:177`
and `schema-reference.md:341` both still say `check_severity` "must be
`error`, `warning`, or `info`", which is the scalar-only rule. That is now
wrong for a type whose `check_severity` is a status mapping. Both are
out of scope for a one-file task on `getting-started.md`.

## Step 1 — walk steps 1-7 verbatim; confirm the red build

Authored exactly as the page shows: `refdes init` (generated
`refdes-project.yaml` matched the page's fenced block character for character),
`items/requirements/power.yaml`, `refdes id`, `items/bounds/thermal.yaml`,
`items/decisions/dec-pwr-001-regulator.md`, then the build, then
`items/tests/power.yaml` and `items/log/board.yaml`. All seven steps' content
was in place before the build below, so this is the reader's end state.

```
$ refdes build
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
build completed with errors (use --keep-going to exit 0)
WARNING <project> — 1 requirement(s) satisfied but not verified — see coverage.html
6 items, 1 errors, 1 warnings
site written to .../my-board/_site
[exit=1]
```

Still red with the test and the log entry added. F4's claim confirmed.

## Step 2 — supersede the failing decision; still red

Added `items/decisions/dec-pwr-002-regulator.md` (passes: `eff = 0.98` gives
`P_dens` well under the 0.15 W/in² limit) carrying `supersedes: [DEC-PWR-001]`,
and set `DEC-PWR-001`'s status to `superseded`.

**BEFORE the overlay:**

```
$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING <project> — 1 requirement(s) satisfied but not verified — see coverage.html
7 items, 1 errors, 1 warnings
[exit=1]
```

The superseded decision's original failure is still a build error. Confirmed.

## Step 3 — the overlay

`refdes-schema.yaml`:

```yaml
types:
  decision:
    check_severity:
      default: error
      superseded: info
      rejected: info
```

**AFTER the overlay:**

```
$ refdes check
WARNING <project> — .refdes/schema.json was older than refdes-schema.yaml -- refreshed. If your editor's completion looked stale, it should catch up now.
WARNING <project> — 1 requirement(s) satisfied but not verified — see coverage.html
7 items, 0 errors, 2 warnings
[exit=0]

$ refdes build
WARNING <project> — 1 requirement(s) satisfied but not verified — see coverage.html
7 items, 0 errors, 1 warnings
site written to .../my-board/_site
[exit=0]
```

Green, and the finding is still there — demoted, not deleted:

```
$ refdes check -v | grep DEC-PWR-001
INFO    items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
```

(The `.refdes/schema.json was older` warning is a one-off from adding the
overlay; it does not recur.)

## Step 4 — the guard rails, verified

**`default:` is mandatory** — omitted it, exactly the error the task described:

```
$ refdes check
configuration error: types.decision.check_severity does not cover status 'proposed'. Add it, or add default: <level>.
[exit=2]
```

**A live failure still fails the build.** Put the overlay back and set
`DEC-PWR-001` back to `status: accepted`:

```
$ refdes check
ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2
WARNING ... supersedes DEC-PWR-001, but that item's status is 'accepted', not 'superseded' ...
7 items, 1 errors, 3 warnings
[exit=1]
```

So the overlay does not blanket-suppress decisions; only the statuses it maps.
Worth one clause in the page — a reader who assumes "overlay = no more red"
would be wrong.

**A typo'd status key is caught** (not needed for the page, checked anyway):

```
configuration error: types.decision.check_severity key 'choosen' is not a declared status. Declared choices: proposed, in_progress, accepted, on_hold, rejected, superseded.
[exit=2]
```

## Step 4b — a wording trap I nearly walked into

My first draft of the page said the check "records what was true when the
decision was made". That is only half true, and a reader would hit it:

```
# no overlay, DEC-PWR-001 superseded, BND-THM-001 tightened 0.15 -> 0.13
$ refdes check | grep DEC-PWR-001
ERROR   ... [DEC-PWR-001] — P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.13 W/in^2
```

The calc values are the decision's own (frozen in the item), but the *bound* is
re-read live. A superseded decision is re-evaluated against the current
limit. So the page says "the decision's own numbers stay on the record"
instead — true, and it does not promise the bound is frozen.

## Step 5 — the standard's own defaults, from source

Read rather than recalled, per AGENTS.md:

- `src/refdes/standards/hardware/v3/base.yaml:224` — `decision` ships
  `check_severity: error` (scalar), so nothing is status-mapped.
- `src/refdes/standards/hardware/v3/base.yaml:259` — `component` ships
  `{ candidate: info, selected: error, rejected: info, obsolete: info }`.

`decision.status` choices, same file, line 227:
`[proposed, in_progress, accepted, on_hold, rejected, superseded]` — which is
why `superseded` and `rejected` are the two that can be demoted meaningfully.

## What I wrote to the page

A single short block appended to §7, immediately before "Where to go next" —
i.e. at the point the reader finishes the walkthrough and next runs a build
and finds it red. Deliberately **not** a new `##` section (the brief asked for
a paragraph plus a fenced example, not a section), and deliberately not a
re-teaching of the feature: two sentences of why, the minimal overlay, the
mandatory-`default:` gotcha, one clause on why it isn't blanket suppression,
and links out to `checks.md#candidates-vs-decision` and
`schema-reference.md#types`.

## Placement reasoning

The brief suggested "after the point where the reader supersedes the
decision". Having read the page: **there is no supersede step in
`getting-started.md`.** §5 builds and fails; §6 adds a test; §7 adds a log
entry. Nothing supersedes anything. So the end of §7 is the correct home —
it is the last thing before the reader's next `refdes build`/`refdes check`,
which is the red one. Placing it after §5 instead would put a
`refdes-schema.yaml` overlay in the reader's way mid-walkthrough, before they
have a reason to want it.

## Status

Complete. One file edited (`docs/getting-started.md`), one
`changelog.d/` fragment, this log. Nothing left undone inside the brief's
scope.

## Not done, deliberately (for the report, not for this task)

1. The stale scalar-only `check_severity` wording in `docs/checks.md:177`
   and `docs/schema-reference.md:341` (see "Pre-work" above).
2. No user-facing reference page for the **status-mapped** form of
   `check_severity`. It is in `docs/design/candidate-parts.md` §4 and gets one
   sentence in `lifecycle.md`, but a newcomer has no page that shows the
   mapping form. The task said to say so rather than write it, so: saying so.
3. The walkthrough still does not reach a literal green build. That was the
   owner's explicit call (restructuring the page is a bigger, riskier change).
