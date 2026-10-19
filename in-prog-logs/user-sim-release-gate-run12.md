# User-simulation release gate, run 12

Acting as a hardware-author user of the shipped docs on branch
`user-sim-run12` (base `12bbf6b` history, HEAD `e2d497b`). The in-scope
source commits since run 11:

- `81ea38a` feat(check): warn on an unclosed fenced code block (R11-F1) (#337)
- `c389669` fix: init gitignore honesty and create-preview board gate (R11-F2..F4) (#336)
- `e2d497b` feat(calc): inline calc slice 1 -- evaluate and verify stored results (:= spans) (#333)

Judged against `docs/math.md` (Inline calc, lines 270-315; calc-line grammar
around 390-400), `docs/authoring.md` fence rules, the CLI help text, and the
three changelog fragments. `docs/design/inline-calc.md` was used for intent
only. Findings are reported, not fixed.

## 0. Headline

All three shipped surfaces do what their changelog fragments promise, and all
four run-11 findings (R11-F1..F4) are verified fixed. The inline-calc sweep is
the deep one: the evaluation, window, scope, and round-trip behavior matches
`docs/math.md` closely enough to ship. Seven findings, one Medium; the sweep
3 cosmetic nit flagged in the task brief (three-character naming in the
unclosed-fence message for `~~~`) did **not** reproduce -- the shipped message
is generic and correct.

| # | Sev | Surface | One-line summary |
|---|-----|---------|------------------|
| F12-1 | Medium | inline calc | triple-backtick code spans trigger; docs say the trigger is a single-backtick span |
| F12-2 | Low | inline calc | a span inside an HTML comment is validated (commented-out math still errors) |
| F12-3 | Low | inline calc | filenames containing `:=` (`src=a:=b.csv`) trigger the grammar and become parse errors |
| F12-4 | Low | inline calc | result separator needs literal spaces: `1 V*4\|V=4 V` reports "stored result missing" |
| F12-5 | Low | inline calc | stale warning's displayed computed value is rounded to look accepted (3.4495 shown as "3.45 V") |
| F12-6 | Low | inline calc | cross-item span-only gap error blames the target ("it defines no calc values") when the target defines it in a fence |
| F12-7 | Low | inline calc | span-form `source()` advice "run 'refdes fetch'" leads to a dead end after fetch |
| -- | -- | init gitignore | zero findings: all 9 shapes match the fragment, checked against `git check-ignore -v` |
| -- | -- | create/preview | zero findings: R11-F4 gate fires with the exact `/api/items` message |
| -- | -- | unclosed fence | zero findings: fires on every unclosed shape, silent on every closed one, lines correct |

## 1. Harness

- `refdes` 0.5.0 from this worktree (`PYTHONPATH=<worktree>/src`, venv python),
  standard `hardware@3`, Python 3.13.
- One helper `.scratch/rr <proj> <args...>`; all projects under
  `.scratch/run12/`. No git commands in sweep dirs; the gitignore shapes live
  in dedicated `git init` repos (`g1..g9`) under `.scratch/run12/`, with
  `git check-ignore -v --no-index` as ground truth.
- `refdes serve` run with `--no-open --port 8731 --token-file tok6`
  (PID recorded, killed at the end, no `pkill -f`).

A harness note that is itself the first piece of #336 evidence: `refdes init`
inside `s1` (nested in this repo, whose root `.gitignore:51` has `.scratch/`)
printed **no** `wrote .gitignore` line at all -- the project's ignore file
wasn't written because every entry was already covered. That is the new,
honest behavior.

## 2. Sweep 1 -- inline calc spans (#333)

Fixture project `s1`: 28+ shapes, one span per item, verified individually.
`refdes check` mints keys on first load ("minted 28 key(s) while loading"), so
byte baselines were taken after that first run.

### 2.1 Verified-correct core (no finding)

Docs promises from `docs/math.md:281-315`; all held:

- Correct span accepted; stale span warns **at the span's line** with the
  exact documented shape:
  `WARNING items/pwr/SHAPE-A2.md:8 [LOG-A2] — inline calc Vout: stored result says 4.52 V, now computes 4.436 V`.
- Editing the *inputs* of a stale-free span re-triggers it: after editing a
  fence input a span reads, check says `stored result says 24 W, now computes
  10 W`; editing a span's own inline input warns likewise. Source never rewritten.
- Window rule: stored `4.4 V` accepts computed 4.436 (half a place in the last
  written digit); trailing-zero `4.0` and exponent `1.2e3` tighten the window
  as documented; `3.5 V` vs computed 3.45 is the tie and is **accepted** --
  and the tie companion (stored `4.0`, computed 4.05) **warns**, i.e. ties
  round away from zero, matching the design doc's decided rule.
- Errors at the span's line, with actionable text: missing result
  (`stored result missing; write '= <quantity>'`), unparseable expression
  (`could not parse expression '1 V *': invalid syntax`), unit assertion
  failure (`declared as V but the expression evaluates to A⋅W`), incompatible
  stored unit (`stored result '3 W' is not compatible with the calculated
  units (V/Ω)`), duplicate name (`'a' is assigned twice in this item -- first
  at line 8, again at line 8 ... rename one of them, e.g. 'a' -> 'a_2'` --
  the two-spans-one-line case cites the same line twice, correctly),
  forward reference from a fence to a later span is an ordinary unknown-name
  error (`calc 'W2': unknown name 'Vlate'`), matching
  "evaluated in source order across both".
- Non-triggers per docs: span without `:=` is ordinary code; ``double-backtick``
  span never triggers (the documented escape hatch) -- verified inert; a span
  whose `:=` is quoted (`t = "q:=1"`) is inert; spans inside ```` ```text ````
  fences are inert; a span inside a blockquote, a list item, link text, and a
  list-file (`items:` mapping in YAML) all fire, with the list-file diagnostic
  carrying file, line, and item id:
  `WARNING items/pwrl/logs.yaml:2 [LOG-L1] — inline calc x: stored result says 99 V, now computes 2 V`.
- Scope: inline names and fence names share the item scope (`{{Vout}}`
  renders the span's value; a fence can read a *later* span only in source
  order, as documented).
- Release gate: `refdes release --help` lists
  `draft_items, unpinned_citations, missing_kept_copies, uncovered_requirements,
  unverified_requirements, info_check_failures, unaccepted_board_moves,
  unaccepted_workspace_moves, open_tasks, captured_edits` -- no inline-calc
  rule, consistent with `docs/math.md` promising a warning, not a gate. Not a
  finding; noted as an observation.
- Round-trips are byte-clean: after keys exist, `check`, `id`, `build` leave
  every item file md5-identical; `refdes rename` (prefix mapping `CON: BND`,
  applied and reversed on a custom-schema project) is byte-identical end to
  end with the span line untouched; `refdes rename` refuses an out-of-standard
  type rename with the rewritten project left valid (its documented
  refuse-and-rollback). The serve editor's `set_body` with the exact text from
  `GET /api/item/LOG-A1` leaves the file md5-identical.
- Rendering: `build` and serve `/preview/` both keep the span literal as
  `<code>` ("The span itself stays literal code in the published page"), with
  the full text preserved:
  `Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.436 V`.

### 2.2 F12-1 (Medium) -- triple-backtick spans trigger

Docs, `docs/math.md:297-299`: "The trigger is a **single-backtick** code span
whose content contains `:=`... a wider ``double-backtick`` span is never
triggered -- the escape hatch when you want the literal text."

Repro (`s1/items/pwr/SHAPE-E7.md`): a span delimited by triple backticks,

```
The doc says ```` ``` ````Vout := 1 V * 2 = 99 V```` ``` ```` literally.
```

(fixture content: ``` ```Vout := 1 V * 2 = 99 V``` ```) fires the full
validation: `inline calc Vout: stored result says 99 V, now computes 2 V`.
CommonMark treats `` ``` `` as a valid code-span delimiter, so the parser's
reading is defensible, but the docs' two named escapes (single=trigger,
double=never) leave triple undefined, and an author who reaches for a
wider fence-style span to *show* a span's text verbatim gets a validation
error on it. The docs promise a boundary the parser does not enforce.

### 2.3 F12-2 (Low) -- commented-out spans are validated

Repro (`SHAPE-E4.md`): `<!-- Vout := 1 V * 2 = 99 V -->` -- the span inside
the HTML comment is evaluated and warns at the comment's line. An author
disabling a math sentence with a comment (a normal "keep the text, stop the
build" reflex) gets a warning they cannot silence without deleting the line.
No docs sentence addresses comments; the docs describe the trigger purely as
"its content contains `:=`", so this is letter-compliant, spirit-violating.

### 2.4 F12-3 (Low) -- filenames containing `:=`

Repro (`SHAPE-Q1.md`): `` `src=a:=b.csv` `` triggers the grammar and dies with
`inline calc Vout: ... stored result missing; write '= <quantity>'` (the span
names no calc value, so the diagnostic is doubly confusing). Quoted `:=` is
inert (verified: `` `t = "q:=1"` `` is ordinary code), so the parser honors
the "unquoted `:=`" grammar exactly -- the friction is that a bare
`name:=value`-style filename is a realistic thing to put in a code span, and
the only escape is the double-backtick hatch, which the docs introduce for a
different purpose.

### 2.5 F12-4 (Low) -- `= result` requires surrounding spaces

Repro (`SHAPE-R3.md`): `` `x := 1 V*4|V=4 V` `` (tight, fence-style spacing)
reports `inline calc x: stored result missing; write '= <quantity>'`. The
expression half parses (tight `|V` is accepted), so only the spaceless `=`
separator is the problem. `docs/math.md:398` promises "Whitespace around `|`
is optional" for the shared calc-line grammar, and the inline section says the
right-hand side *is* that grammar; the result separator is the one place where
inline spacing is stricter, and the docs example uses ` | V = 4.436 V` with
spaces everywhere without calling the requirement out. Advice is actionable,
so: Low.

### 2.6 F12-5 (Low) -- the stale warning displays a computed value that looks accepted

Repro (`SHAPE-C2.md`): `x := 6.899 V / 2 = 3.5 V`. Raw computed 3.4495 V,
stored literal `3.5 V`; the message is
`stored result says 3.5 V, now computes 3.45 V`.
The *displayed* number, 3.45, sits exactly on the boundary of the window the
author computes from the displayed literal (3.5 ± 0.05, and 3.45 is accepted
in the adjacent tie fixture `SHAPE-C1.md`: `x := 6.9 V / 2 = 3.5 V` passes
with the same displayed pair). The violation is real (3.4495 < 3.45), but the
warning's own rounded display hides the reason. Showing more digits when the
computed value is near the boundary (or showing the raw value) would make the
warning self-explanatory.

### 2.7 F12-6 (Low) -- cross-item span-only gap message blames the target

`s3c` reproduces the documented slice-1 gap (math.md:313-315): a cross-item
reference used *only* in an inline span, reader-first load order, fails
loudly -- good. The message is
`cross-item reference 'LOG-B.V_in': LOG-B does not define 'V_in' (it defines no calc values)`.
LOG-B *does* define `V_in`, in a calc fence -- the fence form of the same
fixture (`s3d`) builds clean. Telling the author the target defines nothing
sends them to the wrong file; the gap note's "keep such uses in a fence" is
the actual fix and the message doesn't say it.

### 2.8 F12-7 (Low) -- `source()` span-form advice dead-ends

`s3` (span-only `source('analysis/bud.csv', 'k1')`, unfetched CSV): check
errors with `source('analysis/bud.csv', 'k1') has no locked value -- run
'refdes fetch --path analysis/bud.csv'`. Running exactly that advice pins the
file (`refdes fetch` reports `hash-only` -- 0 keys, consistent with key
discovery reading fences only) and the span-form check **still** fails,
forever; the fence form (`s3e`) pins `k1 = 5.0` and is clean. The advice is
correct for the fence form and a dead end for the span form; the docs' gap
note (keep `source()` in a fence) belongs in the diagnostic.

## 3. Sweep 2 -- init gitignore honesty + create-preview board gate (#336)

Nine shapes, each compared against `git check-ignore -v --no-index` ground
truth. Every printed state matched git's verdict; zero findings.

| Shape | Printed | Ground truth |
|---|---|---|
| g1: `.gitignore` = `.vscode/*` + `!.vscode/*` | `wrote .vscode/settings.json (NOT gitignored -- the yaml.schemas path in it names one checkout, and git does not ignore the file; committing it hands every other clone a schema that resolves to nothing)`; no `.vscode` line appended | negation wins (`!.vscode/*`), file untracked in `git status` -- R11-F2 fixed |
| g2: `.vscode/` | `(gitignored -- ...)` | ignored |
| g3: `/.vscode` | `(gitignored -- ...)` | ignored |
| g4: `core.excludesFile` (global file) | `(gitignored by a machine-local rule only -- the .gitignore line init added makes it ignored for every clone; ...)`; line appended | machine-local; project line now covers |
| g5: excludesFile file literally named `.gitignore` | same machine-local message; line appended | global file named `.gitignore` is machine-local, not the project's -- read correctly |
| g6: git unrunnable (stub exits 127) | literal list written: all five entries incl. `.vscode/settings.json` | matches fragment ("a git that can't run ... answers as before") |
| g7b: repo root `.gitignore` = `.refdes/`, project in subdir | wrote `.gitignore` with only `.vscode/settings.json` + `.refdes-write.lock` | the three `.refdes/...` entries are covered by the root and were omitted -- R11-F3 fixed |
| g8: re-init g1/g4 | zero `wrote` lines | idempotent |
| g9: all five entries present | no `.gitignore` write | idempotent |

Create-preview board gate (serve on `s6`, boards `board-a`/`board-b`):
`GET /api/create/preview?type=log&board=nosuchboard` →
`{"error":"board: no such board 'nosuchboard' in this project; known boards:
board-a, board-b"}` [400], byte-identical to `/api/items?board=nosuchboard`
-- R11-F4 fixed. Registered board → 200 with real destination
(`items/board-a/SHAPE-A1.md`). The R9-F3 workspace gate still fires with the
same shape (`known workspaces: ` -- correctly empty, s6 registers none).
Nit-grade observation only: when *both* facets are bogus, `/api/items` names
the board and `/api/create/preview` names the workspace (each endpoint checks
in its own order); both refuse with the list route's own message shape.

## 4. Sweep 3 -- unclosed fence warning (#337)

17 fixtures in `s5`, one shape each. Fires on: plain unclosed ```; unclosed
`~~~`; unclosed 4-backtick; opener indented 3 (a fence); fence inside a list
item; an unclosed fence in the *second* item of a multi-item file (line
pointed at the fence inside that item); a multi-item file whose first item is
unclosed (the second item's `---` still splits -- R10-X1 split behavior
unchanged, 19 items parsed, warning at the opener's line). Silent on: closed
fences of all kinds, opener with trailing space, closer with a longer run
closes, 4-space-indented fence-like lines (indented code, not a fence),
`~~~` fences legitimately containing ``` lines, and a fence line inside front
matter (opaque). All line numbers = the opener's line.

The R11-F1 heuristic works as promised: a body ending with a closer-like
line carrying an info string
(```yaml ... ``` yaml`) warns at the opener **and names the cause**:
`the file ends with '``` yaml' (line 14), which carries an info string after
its ``` run -- a closing fence carries no info string, so that line is the
closing fence this file is missing.`

The task brief's known cosmetic nit -- the message naming three characters /
the wrong closing character for `~~~` fences -- did **not** reproduce: the
shipped advice is "close the fence with a line of the same character, at
least as long, with nothing after it", which is correct for every fence
character. Zero findings.

## 5. Spot re-checks -- the run-11 fixes

| Fix | Re-check | Result |
|---|---|---|
| R11-F1 (#337) | `s5/items/f/F-C2.md` check | fixed: warning + names the closer line carrying an info string (§4) |
| R11-F2 (#336) | `g1` init with `.vscode/*`+`!.vscode/*` | fixed: NOT-gitignored announcement, no line written (§3) |
| R11-F3 (#336) | `g7b` nested project under root `.refdes/` | fixed: written `.gitignore` holds only uncovered entries (§3) |
| R11-F4 (#336) | `GET /api/create/preview?board=nosuchboard&type=log` | fixed: 400, message identical to `/api/items` (§3) |

## 6. Observations (not findings)

- Release gate has no inline-calc rule (the ten-rule list, §2.1). Stale spans
  warn; they never block `refdes release`. `docs/math.md` promises exactly
  that, and the design doc's gate rule is not in the shipped fragment -- slice
  1 scope as advertised.
- Ties: stored `4.0` vs computed 4.05 warns; stored `4.0` vs computed 3.95
  accepts (4.0); stored `4.05` vs computed 4.05 accepts. Away-from-zero,
  consistently.
- A tolerance in a span's result (`= 4 ± 0.1 V`) is refused with a good
  message (`... is not a quantity literal; write a number with an optional
  unit, e.g. '4.4 V' -- not an expression`).
- `refdes rename` refuses a type rename that produces an unknown type and
  leaves the project files untouched (refuse-and-rollback as documented in
  `docs/cli-reference.md`).
- The serve API takes the launch token in `X-Refdes-Token` (docs-conformant);
  `/preview/` needs the cookie. `set_body` with identical text is byte-clean
  (§2.1 round-trips).

## 7. Status and limitations

Finished: sweeps 1-3, spot re-checks, report. Not done, deliberately: no
browser DOM interaction (serve exercised over its documented HTTP API +
cookie surface); the "init outside any repo" shape can't exist inside this
worktree (every `.scratch` path is repo-nested), so the git-stub proxy (g6)
stands in for "a git that can't answer"; design-doc behaviors not in the
shipped docs (gate rule) were noted, not asserted.

Findings: 7 (1 Medium, 6 Low). Fixes verified: R11-F1..F4.
