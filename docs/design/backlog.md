# Backlog — decisions on outstanding work

**This is a decision record, not a spec.** The other files in `docs/design/`
specify a mechanism in enough detail to implement from. This one instead
tracks *that a piece of work was decided on*, and what was decided, so that
agreement reached in conversation isn't stranded in a chat log the next
session can't see. An entry here earns its own `docs/design/<name>.md` (spec
detail, alternatives considered, a "what I'd prototype first" section) once
someone actually starts implementing it — until then, this is the whole
record.

Verified against the actual codebase as of commit `72ccf1d` (2026-09-13,
`main`). Re-check before trusting an "outstanding" or "done" mark that's more
than a few commits old — this file decays exactly like the implementation
status headers on the spec docs do.

## Source

Two documents, both GitHub attachments on issue #7, neither a file in this
repo:

- **Findings 12–24** come from the attachment that is the issue's *body*:
  <https://github.com/user-attachments/files/31488284/refdes-feedback.md>
  (fetched 2026-08-29).
- **Findings 25–28** come from a *second* attachment, posted as a **comment**
  on the same issue on 2026-09-01 under "More, newer suggestions added":
  <https://github.com/user-attachments/files/31711415/refdes-feedback.md>
  (read in full 2026-09-13). It is a fresh posting against 0.5.0 that retires
  the 0.4.0-era findings it verified as shipped and renumbers 1–28, so its
  1–24 are the findings already recorded above and only **25–28 are new to
  this file**. Where the two documents differ, the newer one is what the
  finding says now.

Read in full before writing this — summaries below are my own reading of those
documents, not a re-statement of anyone else's paraphrase; where a shorthand
I'd previously been given didn't match what the document actually says, that's
flagged inline in the entry.

## The local-model-suitability rule

Stated once here rather than repeated per entry: **hand out work where being
wrong is loud** — a failing test, a build that refuses to complete. This
project's characteristic bug is code that *reports success while doing
nothing* (silent coverage miscounts, a lint that never fires, a link that
resolves to the wrong thing without erroring) — exactly the failure mode a
smaller model is more likely to produce and less likely to notice it
produced. A finding with a sharp, mechanical acceptance test is a candidate;
a finding whose correctness depends on taste, on a design tradeoff, or on
noticing an absence (a case that silently doesn't fire) is not.

Two clauses, added after ten tasks were delegated to small/local models this
session and independently verified:

1. **Loudness is mostly a property of the task specification, not of the
   task.** Every delegation that went well this session named the quiet
   failure mode in the prompt and required a discriminating test for it —
   and the tests those prompts produced were what made the verdicts
   verdicts: a task told "an unknown tag must error, not silently render an
   empty table" produced a fixture built so an OR implementation would
   diverge from an AND one; a task told "prove the link RESOLVES, not just
   that it parses" asserted on backlinks, which only the resolver
   populates; a task told "a substring check would pass with the href
   untouched" asserted the whole attribute. So: a quiet failure mode
   disqualifies a finding only if it **cannot be made loud by the spec**.
   Most can.
2. **What actually stays off a smaller model is work whose design is
   unsettled** — taste, unresolved tradeoffs, no written spec — not work
   that is merely consequential. Consequence is what an acceptance test is
   for; unsettled design is the one thing a test cannot supply.

**The stance behind the revisions below:** prefer finding empirically where
a model breaks over pre-judging it. A wrong delegation costs a revert; a
wrong pre-judgment costs work never attempted, which leaves no trace and so
never gets corrected. Ten delegated tasks this session performed well above
what the verdicts below assumed — one local model reviewing another model's
work found a real XSS (an item title containing `</script>` breaking out of
the preview-data script element) that the human-facing orchestrator had
missed. The verdicts here were revised on that basis and may be revised
again.

Only entries where this was actually decided carry a **Local model:**
verdict. Where I've extrapolated the rule to an item nobody explicitly
ruled on, it's marked **(not decided — my read)** so it isn't mistaken for
settled.

---

## GitHub issue #7, findings 12–24

### 12 — Fix the `body:`-in-list-files rationale

Both `docs/authoring.md` and `parse.py`'s `RESERVED` comment justify steering
log entries into YAML list files with "avoids one file per entry" — a false
premise, since a markdown file already holds many items sharing one
`defaults:` block (verified in the finding with a working two-entry example).
The fix is a docs correction plus a comment fix, not a schema change: state
the real tradeoff (bare date+summary entries are fine as YAML; a log entry
carrying prose body belongs in `.md`), and say explicitly that markdown files
hold multiple items.

**Status: done.** Shipped in `8e33c08`. `docs/authoring.md`'s "Bodies in list
files" passage and `parse.py`'s `RESERVED` comment now state the real tradeoff
in the same words: a `.md` file already holds many items sharing one
`defaults:` block, so the question is not file count but whether the entry
carries prose — a bare date-and-summary log entry as a list entry, one with a
paragraph to it in `.md`, `body:` covering the middle. No schema change, as
scoped.

**Local model: suitable.** Scoped to two files, the wrong text and its
replacement are both given in the finding, and a reviewer can check the
result by eye — no design judgment involved.

### 13 — `{{index}}` needs a `tag=` filter parameter

`{{index}}` can filter by `board=` but not by `tag=`, even though `tags:` is
the field this project already uses for cross-cutting grouping that doesn't
follow board or type lines (finding 9's argument). Scoped deliberately as
one more fixed, named, single-valued parameter — not a query language — to
stay inside `blocks.py`'s own stated non-goal.

**Status: done.** Shipped in `1cf3e88`. `blocks.py`'s `index` `BlockSpec` is
now `optional=("board", "tag")`, and `_render_index` validates `tag` against
the tag set present on the project's local items with the same `_suggest` hint
`board=` uses, then ANDs it with `board=` in the single comprehension that
selects items — still one fixed named parameter, no query language.

**Local model: suitable.** One parameter added to one `BlockSpec`, one
filter clause in `_render_index`, validated against the project's known tag
values the same way `board=` already is. A wrong implementation either
filters incorrectly (test catches it) or crashes on an unknown tag (loud).

### 14 — A grouping/collection type

No way to name a collection of items as a thing (e.g. "the PCIe interface
spec," today nine separate requirement items with no unit to point at). A
link-to-a-whole-file mechanism is explicitly rejected — this repo has direct
history (`items/main-io/decisions.md`'s migration note on `DEC-IO-006`) of a
group-reference silently enlarging its own meaning as the file it pointed at
grew, which broke coverage. The proposed type is deliberately **not**
coverable and **not** a satisfaction target — `satisfies:` keeps requiring
individual items, membership is declared by members pointing at the group
(not the group listing members), and it's linkable/renderable via the
existing `{{cascade}}` mechanism.

**Decision — the membership verb.** The verb a member uses to declare
"I belong to this group" is **`part_of`**, not `shaded_by`. `shaded_by` was
considered and rejected: it sits one letter from `shadowed`, which the
schema already uses to mean "overridden," and a group does not override
anything its members declare. The "a group shades its members — it defines
what they're subject to without satisfying anything on their behalf"
framing is real and worth keeping, but as prose explanation of what the
group *means*, not as the verb's name. (This decision and its rationale
aren't in the GitHub finding — the finding proposes the type's properties
but not a verb name — so this is recorded from conversation, not from
issue #7.)

**Status: outstanding.** No grouping type exists in any bundled standard
version.

**Local model: suitable, IF the task specifies negative tests.** The whole
point of this type is what it must *not* do (not coverable, not a
satisfaction target), and the failure mode is a silently-too-permissive
implementation that looks like it works until someone accidentally claims a
group and coverage goes quiet about it. But that failure is directly
testable, and the task must name the tests: assert that a group is **not**
coverable, and assert that a group **cannot** be a `satisfies:` target.
Those two negative assertions turn "too permissive" from a silent outcome
into a failing test — under clause 1 of the rule above, that is the whole
difference between suitable and not. Without them named in the task, this
verdict reverts.

### 15 — A form-based authoring surface

The recurring friction across real authoring has been the authoring surface
itself, not the data model: refdes only ever validates after the fact
(`check` diagnostics, schema squiggles) and never offers structure up front.
Proposed: a VS Code `CustomTextEditorProvider` webview form over the same
plain YAML/markdown files — not a new format, not a database. `refdes new
<type>`'s generator already produces the correctly-shaped skeleton the form
would render; most of the remaining data the form needs is either already
exposed (`refdes index --compact`) or already requested by other findings.

**Decision — scope.** Explicitly a *view over plain text*, not a database:
the file stays the complete truth, `refdes check`/git diffs/CI/hand-editing
all keep working unchanged, and the CLI must remain able to do everything
the form can do. The finding's own dependency table lists **findings 8, 9,
10, and 13** (id completion by file/board, `refdes ls`, `next_ids` for id
pre-fill, and this backlog's own finding 13) as blockers. **That list is now
stale — all four have shipped**, verified against this tree: finding 8 in
`1044c96` (the extension's completion `filterText` now includes each item's
source file and board, `editors/vscode/extension.js`); finding 9 as
`refdes ls` (`cmd_ls` and its `ls` subparser in `src/refdes/cli.py`);
finding 10 as `next_ids` in the index payload (`payload["next_ids"]`,
`src/refdes/render.py`); and finding 13 in `1cf3e88`.

**Status: outstanding.** No `CustomTextEditorProvider` exists in
`editors/vscode/extension.js`.

**Local model: not suitable.** This one survives the revised rule unchanged:
it is design-judgment-heavy UI work with no mechanical acceptance test —
"does this feel like the right form" isn't something a failing test catches,
and no wording in a task spec makes it so. Its dependencies are no longer
the obstacle (all four blockers have shipped, above); what keeps it off a
smaller model is the unsettled design, not the waiting.

### 16 — `recorded_by: [log]` on `decision`

A sealed, append-only `log` can never link to anything created after it
(`compute_hashes()` folds every link into the content hash unconditionally,
with no `on_change` equivalent for links), so "write the log while
deliberating, decide afterward" is unauthorable in that order today. No new
verb needed — `schema.py` already resolves a link from either declared
direction (verified: `records`/`recorded_by` already exist as an inverse
pair at the `link_types:` level in every bundled version) — the fix is
declaring `recorded_by: [log]` on `decision`'s own `links:` block, verified
end-to-end against a real sealed log in the finding.

**Status: done.** Shipped in `3c52c4e`. `decision.links` (hardware@3) now
declares `recorded_by: [log]` alongside
`satisfies`/`constrained_by`/`supersedes`/`selects`/`blocked_by` — one line,
no new verb, exactly as scoped.

**Worth flagging: this may become moot.** `docs/design/threads.md` (design
only, not implemented — see its own status header) states explicitly that
if the thread model ever lands, "the observation that `records`/`recorded_by`
(finding 16) dissolves" — collapsing `log`/`decision` into one chained-item
type removes the append-only-can't-point-forward problem structurally,
rather than patching around it one verb at a time. Until threads.md moves
past design-only, finding 16 is still a valid, independent, one-line fix.

**Local model (not decided — my read): suitable.** One line in a bundled
standard file, with an end-to-end verification transcript already given in
the finding to check the result against; wrong output is either a schema
validation error or a link that doesn't resolve, both loud.

### 17 — Threads: superseded, with the model corrected

Finding 17 is a recorded design analysis, not a defect: could `log` and
`decision` collapse into one append-only "thread" type, current state
derived by folding? It was **considered and not adopted** in the finding
itself — the two live objections (link-target identity needing a two-tier
mutable-thread/immutable-entry scheme, and per-field folding rather than a
terminal-entry read for checks) were judged to make it "a different tool,
not a refactor."

**Status: superseded by `docs/design/threads.md`, with the model corrected.**
That document explicitly says the prior draft's model was wrong: it had
specced a thread as **one item containing a nested `entries:` list** — its
own sub-structure, its own key-minting scope, a two-hash model to separate
tamper-detection from fold-change-detection. `threads.md`'s model is
different and simpler: **each entry is a full, ordinary item**, parsed,
hashed, and sealed exactly like any other item today; an entry declares its
predecessor via an ordinary link (`follows:`, with computed inverse
`followed_by:`); the thread is not a container at all, it's a property of
the link graph. That resolves finding 17's own hardest objection (the
two-tier identity problem) for free — there's no separate "the thread as a
mutable whole" to name, only entries, which already have identity the same
way every item does under `docs/design/keys.md`.

`threads.md` is itself **design only** — nothing in it is implemented (see
its own status header). Finding 17 shouldn't be treated as a live task
distinct from that document; if this work happens, it happens as
`threads.md`, not as a resurrection of finding 17's original per-item
"folding" proposal.

**Local model: not applicable** — this is a design note, not an
implementation task.

### 18 — Calc lexer rejects `%` and `Ω` after an SI prefix

Two related lexer bugs in `calc.py`'s unit pattern, both confirmed against
pint (which handles both forms correctly, so this isn't a units-library
limit): (1) `%` is accepted only inside the `± N%` tolerance special case
(`PERCENT_RE`, pre-parse) and fails as `invalid syntax` everywhere else
(`85 %`, `100 V * 5 %`); (2) `Ω`/`µ`/`°` are permitted only as the *first*
character of a unit segment, which is backwards for `Ω` specifically since
resistances are almost always written with a prefix (`kΩ`, `MΩ`) — the one
spelling that works (bare `Ω`) is the one least used. Suggested fix: move
`Ω`/`µ`/`μ`/`°` into the continuation character class too, and admit `%` as
its own unit-run alternative rather than a `_SEGMENT` character.

**Status: done.** Shipped in `3a2fced`. `_SEGMENT`'s continuation class is now
`[A-Za-z0-9_Ωµμ°]*` (both mu codepoints), so `kΩ`/`MΩ` lex, and `_UNIT_RUN`
admits `%` as its own alternative — `(?:{_SEGMENT}(?:[/·]{_SEGMENT})*|%)` —
rather than as a segment character, so `%` cannot leak into the middle of an
ordinary unit. `PERCENT_RE`'s tolerance pre-parse still runs first, so `± 15%`
keeps its "15% of the value" meaning, and the parse failure that remains now
names the offending expression instead of a bare `invalid syntax`.

**Local model: suitable.** The fix site is two regex literals plus (at
minimum) a better error message; the finding gives exact repro strings and
exact expected failures/successes to turn into tests directly. A wrong regex
either fails those tests or produces a `SyntaxError` exactly as loud as
today's — there's no quiet-failure mode here.

### 19 — `[[ID#field]]` fragment references; citation identity

Two related, non-substitutable gaps: (a) no fragment syntax at all —
`EXPLICIT_REF_RE` admits `:` (which is what makes `[[fig:id]]` work) but not
`#`, so `[[EXP-CMP-001#part_number]]` doesn't match and silently renders as
literal text; and (b) even with fragments, a **citation** is a repeated
sub-entity inside a list-valued field (`datasheets:`), so a field fragment
can only point at the whole list, not at the one datasheet meant — citations
need their own declared `id:` and reference namespace (`[[cite:<id>]]`), the
same pattern figures already use. Both should follow the existing
declared-name-plus-build-time-validation precedent (`[[fig:id]]`,
`{{CLIM}}`), not a curated allowlist. `revise.py`'s `_stale_prose_references`
would need to learn about fragments too, or at least flag them as stale.

**Status: outstanding.** `EXPLICIT_REF_RE` (`build.py:28`) still has no `#`
in its character class; citations have no `id:` field or reference form.

**Local model: split — the fragment-syntax half suitable, the rest not.**
The `EXPLICIT_REF_RE` half is a regex change of exactly the shape finding 18
was (`3a2fced`), which a local model completed correctly this session: one
character class, with the finding's own repro strings
(`[[EXP-CMP-001#part_number]]` rendering instead of appearing as literal
text) turning straight into a discriminating test, and a wrong regex failing
either as a failed test or as today's visible literal text — loud either way.
The other two pieces stay **not suitable**: the citation-identity namespace
(a declared `id:` on citation entries plus a `[[cite:<id>]]` reference form)
is a new mechanism rather than a widened one, and the `revise.py`
`_stale_prose_references` wiring is the "did I actually wire every consumer"
problem `docs/design/keys.md` documents costing real, disclosed effort even
for its authors — an absence, which clause 1 only forgives when the spec can
make it fire, and here the spec would have to invent the mechanism first.

Two distinct, interacting mechanisms is the shape that stays in hand; only
the widened-regex half qualifies.

### 20 — Generate per-type item examples into the docs

The reference docs describe schema *abstractly* (field tables, "how to
declare a type") but never show a filled-in, valid instance of any type —
exactly the artifact `refdes new <type>` already generates from the
resolved schema, currently reachable only by someone who already knows the
command exists. Proposed: a docs-build step that runs the generator for each
type in the pinned standard and injects the output into the reference page,
labelled with the standard version. Deliberately *not* a `{{index}}`-family
block — `blocks.py` only ever renders items that already exist in a project,
and a schema skeleton isn't an item.

**Status: done.** `docs-site/gen_examples.py` injects live generator output
into `docs/schema-reference.md` (shipped in `1e997b8`), with
`tests/test_docs_examples.py` asserting the block matches live output and a
`python docs-site/gen_examples.py --check` step in `.github/workflows/docs.yml`'s
build job failing the docs deploy when the block goes stale.

**Local model (not decided — my read): suitable, IF the gate is specified.**
The finding itself flags the real wrinkle — `docs-site/refdes.yaml` pins no
`standard:`, so the generator has to run against a *different*,
standard-pinned project and get injected into docs built from `docs-site/`,
and getting that wiring subtly wrong produces docs that build successfully
while showing stale or wrong examples. That stops being quiet the moment the
task states its acceptance test: **assert that the injected example equals
`refdes new <type>` output for the pinned standard version.** With that
assertion in the task, stale-or-wrong wiring fails the build instead of
shipping; without it, the quiet failure stands and this verdict reverts.

### 21 — `extends:` — single-level type inheritance

`bound` is structurally "a `requirement` that carries a number" — the two
types duplicate nearly every field (`text`, `rationale`, the full `status:`
enum, `coverable`, `include:`, `body:`) for one real difference (`limit:`,
required). Proposed: single-level `extends:` with universal (Liskov)
substitution — any `[requirement]` link target accepts a `bound` too, no
opt-in marker — reasoned through at length in the finding, including
reversing its own earlier draft's opt-in-marker proposal once finding 22
established that `satisfies` excluding bounds was a defect, not a deliberate
boundary. Coverage grouping (bounds under requirements vs. their own
section) becomes a project setting, defaulting to current (separate)
behavior.

**Status: outstanding.** No `extends`/inheritance concept exists in
`schema.py`; `standards.resolve_schema()`'s layered merge is base → presets
→ project overlay only, with no type→type axis.

**Local model: not suitable to design, suitable to implement once specced.**
What was hard here was the judgement — whether universal (Liskov)
substitution is safe across every `[requirement]` target in the standard and
every preset, where getting substitution scope subtly wrong is a silent over-
or under-acceptance of link targets rather than a crash — and that judgement
is already made, in the finding, including the reversal of its own earlier
opt-in-marker draft. Per this file's own header rule, the entry earns a
`docs/design/` document first; once that document states the substitution
rule and the coverage-grouping default, the implementation is testable, and
link-target validation is already mechanically tested in this codebase.
Until the spec exists this is design-unsettled work under clause 2, and
stays off.

### 22 — Widen `satisfies` to `[requirement, bound]` — DONE

In hardware@2, nothing could satisfy a `bound`: `decision`/`component`'s only
bound-facing edge was `constrained_by`, which fed no coverage computation at
all (`constrained_by`/`constrains` appeared nowhere in `build.py`, only in
doc comments). A `bound` could be verified or addressed but never
*satisfied*, regardless of design work done against it — confirmed a
regression, not an intentional split, since this project's own pre-standard
hand-rolled schema already did it correctly. Fix: widen `satisfies` on
`decision` and `component` to `[requirement, bound]`; no new verb.

**Status: done.** Shipped in hardware@3 (`CHANGELOG.md`'s `[Unreleased]`
Breaking entry, point 2) — confirmed directly in
`src/refdes/standards/hardware/v3/base.yaml`:
`decision.links.satisfies: [requirement, bound]`,
`component.links.satisfies: [requirement, bound]`, plus `component` also
gaining `constrained_by: [bound]` and a `checks:` field per the same
changelog entry.

**Local model: not applicable** — already shipped.

### 23 — Wire `page:` into citation hrefs; PDF-outline `section:` resolution

Two independent parts sharing one motivation (a recorded page number that
currently goes nowhere): **Part 1** — `CitationSpec.page` is already
recorded and rendered into a table cell, but never appended to the link
itself as the standard `#page=N` PDF fragment (honoured by every major
viewer); cheap, no new dependency, no parsing. **Part 2** — for `vendor:
true` citations specifically (guaranteed present locally, so resolution
never depends on network access), a datasheet's own PDF outline could
resolve a human-written `section:` string to a page number at `fetch` time,
recorded in the lockfile alongside the sha256 — genuinely useful (a missing
outline entry on re-fetch means "the section you cited no longer exists,"
a sharper signal than a bare hash mismatch) but needs a new optional
dependency (`pypdf`, as `refdes[pdf]`) and must fail cleanly on PDFs with no
outline rather than crying wolf.

**Decision — the two parts are independent.** Part 1 should ship on its own;
it does not need Part 2's dependency or its fetch-time resolution machinery.

**Status: Part 1 done, Part 2 outstanding.** Part 1 shipped in `a077cb2`:
`item.html.j2` now appends `#page={{ c.spec.page }}` to *both* citation hrefs —
the upstream link and the published `local copy` link — guarded on `page` being
set, with the visible link text unchanged. Part 2 is neither built nor decided:
there is still no `section:` field, no outline-resolution code in
`citations.py`, and no `pypdf` extra in `pyproject.toml` (the only optional
extra is `dev`). `document.html.j2` and `references.html.j2` were deliberately
left alone — the latter groups by URL across citers, where a per-citation page
would be misattributed.

**Local model: Part 1 suitable, Part 2 not decided.** Part 1 is a template
change of the form "append `#page={{ c.spec.page }}` to an existing href,
only when `page` is set" — mechanical, and a wrong result is visibly a dead
or malformed link. Part 2 wasn't given a verdict; per the rule above, my
read is **not suitable**: "fails clean when the PDF has no outline" is
exactly the kind of no-op-that-looks-like-success case the rule warns about,
and getting the failure mode wrong means citations silently stop resolving
sections instead of erroring.

### 24 — Per-(item, board) coverage for cross-cutting contracts

A platform-wide contract (e.g. "all boards with an ARM MCU shall use the
standard 10-pin debug header") reports fully `satisfied` the moment *any one*
board complies, because coverage is computed per item, not per (item,
board) — verified directly in this project's own `IFC-DBG-001`, satisfied by
one main-io decision while the expansion board and tuner are invisible in
the result. Not a typing problem — a dedicated `contract` type would
duplicate `requirement` for no behavioral gain; the fix is a board-declared
`conforms_to:` list (mirroring the existing `boards:` registry, not a scope
list hand-maintained on the contract itself, and not pointed at a file for
the same file-membership-is-an-accident reason finding 14 rejects a
file-scoped grouping). Composes with finding 14's grouping type as the
`conforms_to:` target. An unregistered group named in `conforms_to:` should
be a hard error, mirroring the existing unregistered-board error.

**Status: outstanding.** No `conforms_to:` exists anywhere in `boards.py` or
`schema.py`'s `BoardSpec`; coverage in `build.py` is computed per item id
only, with no board dimension.

**Local model: suitable once finding 14 lands.** The dependency on finding
14 stands — there is no group to name in `conforms_to:` until the grouping
type exists, and coverage computation should not be touched before that
target's own negative tests do. What changed is the feared edge: an
unregistered group named in `conforms_to:` must hard-error, or a typo
silently discharges an entire board's obligations — which is the same shape
as finding 13's unknown-tag case, implemented correctly this session
precisely because the task named it ("an unknown tag must error, not
silently render an empty table"), with a fixture that made an AND
implementation diverge from an OR one. Naming that edge in the task makes it
loud, so consequence alone — coverage being the most consequential silent
wrong-answer place in this codebase, per finding 24's own framing ("the
failure mode is silent and optimistic") — is no longer disqualifying under
clause 1 of the rule above.

---

## GitHub issue #7 (second attachment), findings 25–28

### 25 — Citations belong in an includable field set; `url:` should become one `path:`

Two halves. **Part 1:** in hardware@2, `citations` is declared exactly once in
the whole standard — `component.datasheets` — so no other type can cite
anything, which means a *decision* cannot cite the document it was derived
from. The finding's own example is this repo's `DEC-IO-002`, which cites the
TPS1H200A datasheet at `page: "22"` (the page the current-limit equation its
calc block implements comes from) and can only do so because this project runs
a hand-rolled schema; migrating onto the bundled standard would drop that
citation with nowhere to put it. The proposed mechanism is the one the standard
already has — a third `field_sets:` entry pulled in per type by `include:` —
so any type, or a project overlay, opts in without the standard guessing who
needs it. **Part 2:** `CitationSpec` (`url`/`rev`/`page`/`part_number`/`vendor`
plus fetch-time provenance in the lockfile) models an *upstream*, so a
schematic PDF that lives in the repo and was never fetched has no
representation at all; this repo's workaround, `schematic_page: "7"`, is a bare
number with nothing to click and no way to know page 7 still shows what it
showed — finding 23's dead end minus even a document. The reason to make it a
citation rather than a markdown link is `citations.py`'s sha256 pin:
`site.assets:` already copies PDFs into `_site/assets/` and a prose link works
today, but a prose link keeps pointing at the new revision silently, while a
pinned citation reports `hash_mismatch` when the schematic moves. The finding
asks for **one** `path:` field, not `path:` alongside `url:` ("where the
document is" is one idea — two keys would be the synonym defect this document
keeps finding), dispatching on scheme: a URL scheme means fetched/hashed/
optionally vendored exactly as today, anything else means repo-relative, hashed
at build time by the `_sha256_file()` `citations.py` already has. Two explicit
rules: repo-relative means relative (absolute paths and drive letters rejected
— a Windows `C:\` vs `c:`-scheme ambiguity, and non-portable anyway), and
`vendor: true` on a local path is a hard error, not silently ignored. It also
flags a migration caveat: `revise.py`'s `Mapping.fields` renames item-level
fields only, so a `url:` → `path:` rename *inside* a citation entry is invisible
to it — as are the sub-keys of `options:` and `checks:`.

**Decision — one field name, not two.** The finding proposes a `references`
field set holding *two* fields, `datasheets` and `documents`. That was
considered and **rejected in favour of a single field name, `citations`**:
once citations are includable, a decision citing a schematic needs no
differently-named field than a component citing a datasheet, so two names would
be an arbitrary split kept forever. `citations` was chosen over `references`
because it matches the existing field *type* name and `citations.py` — the set,
the field, and the module are one concept with one spelling. (Not in the
finding — recorded from conversation, not from the document.)

**Decision — the breaking rename is accepted.** `component.datasheets` became
`component.citations`, with a `component: {datasheets: citations}` entry in
hardware v3's `migration.yaml` carrying hardware@2 content across. Accepted
deliberately: hardware@3 is unreleased, and existing hardware@2 content is
migratable by `refdes standard upgrade`, so this is the only point at which the
rename is cheap. (Not in the finding — recorded from conversation, not from
the document.)

**Decision — scope is v3 only.** `hardware/v1/base.yaml` and `v2/base.yaml` are
frozen, already-released shapes; the split is not retrofitted into them.
(Not in the finding — recorded from conversation, not from the document.)

**Decision — Part 2 is deferred, not rejected.** Replacing `url:` with a
scheme-dispatched `path:` that accepts repo-local files was set aside until
refdes' core is in better shape. **Finding 26 depends on it** — the finding
says so itself: a file has to be citable before a calc value can be drawn from
it — so 26 is parked for the same reason, not because it was judged wrong.
(Not in the finding — recorded from conversation, not from the document.)

**Status: Part 1 done, Part 2 deferred.** Part 1 shipped in `f8e7ee0`:
hardware@3's `field_sets:` has a third entry `citations: {citations: {type:
citations, on_change: invalidate}}`, and both `component` and `decision` now
`include: [provenance, stewardship, citations]`, with the `migration.yaml`
rename above and this repo's own `items/components/power.yaml` moved over.
Part 2 is unbuilt: `CitationSpec` still has `url`, no `path`, and the lockfile
is still keyed by url.

**Local model: Part 1 suitable (and shipped), Part 2 (not decided — my read)
not suitable.** Part 1 is a field-set declaration plus a rename entry, with a
migration test asserting the old key resolves to the new one. Part 2's edges are
the quiet kind: scheme dispatch that misclassifies a Windows path, `vendor:`
silently ignored instead of refusing, and — worst — the `revise.py` blind spot
the finding itself names, where a `url:` → `path:` migration that isn't
implemented simply *doesn't happen* and `standard upgrade` reports success.

### 26 — Calc values sourced from a repo-local file (spreadsheet, schematic, netlist)

Hardware arithmetic lives in spreadsheets — power budgets, thermal models,
tolerance stackups, derating tables — and refdes has no spreadsheet support of
any kind, so a value computed in a shared budget gets retyped into a calc block
and silently diverges the moment the model is updated. The objection the finding
sets itself is that a value pulled from `Sheet1!B14` is opaque — no visible
derivation, no unit checking — which is exactly the failure `DEC-IO-002`'s body
describes about its old Quarto python block. It clears that objection by
comparison, not assertion: `V_cl = 0.8 V` in that same calc block came from
page 22 of a datasheet, equally derivation-free, and is trusted because it is
cited and hash-pinned. A spreadsheet-sourced value with the same treatment is on
identical footing, and a spreadsheet committed to the repo is on *better*
footing than a fetched PDF because git history covers it too. Recording **both**
the file hash and the extracted value in the lockfile turns a row inserted
upstream into a visible value diff (`1.85 → 2.3`) rather than a silent
substitution — surfacing, not preventing, which is how this tool handles this
class of problem. Four constraints each do real work: **named ranges, not cell
addresses** (detection is the fallback, prevention is better where it's free —
the same lesson as named calc values, `[[fig:id]]`, and ids never derived from
position, learned three times over); **extraction at fetch time into
`.refdes/citations.yaml`, never during a build** (builds stay hermetic, and the
extracted value lands as a reviewable line in a git diff); **units stay declared
refdes-side** (a sheet in mW extracted into a `: W` declaration is a silent
1000× error, but identical to mistyping a datasheet figure — a reason to keep
the unit annotation prominent, not to refuse); and **CSV first, xlsx as an
optional extra** (`openpyxl` on top of the current four dependencies; CSV needs
nothing beyond the stdlib, and named ranges are an xlsx concept whose CSV
analogue is a header-keyed lookup). The reader is an extension point, not a
spreadsheet special case: an LTspice `.asc` `SYMATTR Value 10k` is plain text,
QSpice's `.qsch` likewise, Falstad encodes a whole circuit in its URL fragment,
and Altium's binary `.SchDoc`/`.PcbDoc` are deliberately excluded in favour of
the CSV BOM/netlist exports — which generalises to any EDA tool that can export,
and keeps a solo project from signing up to track three vendor formats
indefinitely. The point of a schematic reader is **drift detection, not
navigation**: comparing the simulation's `R1` against a decision's
`CLR = 3.3 kohm` catches the value-changed-in-one-place failure a hashed
screenshot cannot. And **read-only is a hard boundary, not a first-release
limit** — writing values back inverts the authority direction (the schematic
becomes derived, which is backwards, and round-trips the moment an engineer
edits it) and changes the failure class from "the document is wrong" to
"refdes corrupted my schematic."

**Status: outstanding — and parked behind finding 25's Part 2.** No `xlsx`/`csv`/
`openpyxl` reference exists anywhere in the package, and the lockfile records
hashes only, never extracted values. The finding states the dependency itself: a
citation has to be able to name a repo-local file before a calc value can be
drawn from one.

**Local model (not decided — my read): not suitable.** The mechanical parts
(a CSV reader, a lockfile field) are easy, but the correctness claim is "the
value extracted is the value that was in that named range," and a reader that
extracts the *wrong* cell does so with a hash that matches and a build that
passes — a wrong answer with no failing test anywhere, which is this project's
characteristic bug. The pluggable-reader boundary is also a design decision
about what third parties will maintain, not a thing to get right by analogy.

### 27 — Project-defined reusable equations callable from any calc block

The same expression gets retyped across items — a current limit per output, a
thermal rise per rail, a divider ratio per input — each copy an independent
typos opportunity, with no single place to correct a formula that turns out to
be wrong. Most of the machinery already exists: `calc.py` has a function
registry and full call support, and `_eval_node`'s `ast.Call` branch already
resolves the name, rejects keyword arguments, checks arity against `MULTI_ARG`,
evaluates arguments through the same `Value` arithmetic as everything else, and
produces a proper diagnostic for an unknown name. What's missing is any way for
a project to add an entry. Implementation is small because `evaluate(expression,
env)` is already parameterised on its environment — a user equation is "bind the
parameters into an env, `evaluate` the stored expression," no new evaluator and
no new parser. Proposed shape is an `equations:` map of `params`/`expr`/`note`
called as `current_limit(2500, 0.8 V, 3.3 kohm) ± 15%`. Two properties come free
from building on the existing evaluator and are worth stating so they aren't
reinvented: units flow from the arguments, so parameters need no declared
dimensions and passing `3.3 kg` where a resistance belongs is an ordinary
dimensionality error at the call site; and tolerance propagates automatically,
because `Value` arithmetic already does it. Three rules to fix early: shadowing
a built-in (`sqrt`, `min`, …) is a hard error rather than a silent override; an
equation referring to another equation is allowed but cycle-checked, the way
`blocked_by` already is; arity is already enforced by the existing call path.
Definitions belong in **project settings alongside `units:`** — not an item type
(calc values are item-local today, so equations-as-items means opening that
boundary, and Ohm's law isn't a design record; a `note:`/`source:` on the
definition covers provenance), and not a per-board file (math isn't
board-specific, and two boards defining `current_limit` differently creates a
resolution question that needn't exist). One project-wide namespace. Which file
that is, is finding 28's question.

**Status: outstanding.** `calc.py`'s registry is still the built-in set, and no
`equations:` key exists in project settings or the schema.

**Local model (not decided — my read): suitable.** The evaluator work is
"bind params, recurse," and the failure modes the finding names are all loud by
construction — unknown function, wrong arity, wrong dimensions at the call site,
a cycle reported the way `blocked_by` reports one. The two rules that are *not*
loud if skipped (silent built-in shadowing, an equation cycle) are exactly the
two a test can pin, and the finding states them as rules rather than
preferences.

### 28 — Make the config split honest: project settings in one file, schema overlay in another

The complaint that started this was "`refdes.yaml` isn't immediately clear what
it means," and the cause turns out not to be the name. There are already two
config files, and `refdes-project.yaml`'s own header states the intended
division — "Presentation and behaviour, not schema — refdes.yaml defines item
types, links, and change-tracking policy; this file is process policy and
formatting preference" — while the contents contradict it in both directions:
`site:`, `units:`, `id:` and `boards:` sit in `refdes.yaml` (presentation,
formatting preference, behaviour, structure — all project settings by the
stated rule), and `item_layout:` sits in `refdes-project.yaml` despite being
schema-adjacent structure. `history:` is the one key correctly placed. So
`refdes.yaml` reads as unclear because it holds two unrelated things while a
sibling file claims to own half of them, and renaming it alone would not fix
that. The proposal is one honest line with both files named for their contents:
**`refdes-project.yaml`** holds *all* project settings — everything in it today
plus `site:`, `id:`, `boards:`, `units:`, `history:`, `workspaces:`,
`standard:` — and becomes the project-root marker; **`refdes-schema.yaml`**
holds *only* the project's own overlay (`types:`, `link_types:`, `field_sets:`)
and is **optional**, absent from most projects; **`refdes.yaml`** is retired.
`standard:` goes with project settings rather than with schema because it
declares *which* schema the project uses, not what the schema is — putting it
in the schema file would force every standard-library project to carry a schema
file solely to say "I use hardware@2," and the common case now is a dozen lines
of `site:`/`standard:`/`id:` with no `types:` block at all. Cost, honestly: the
config filename is referenced in fifty-one places across thirteen modules (the
six the estimate named — `CONFIG_NAME`/`find_config()` in `schema.py`,
`revise.py`, `scaffold.py`, `schema_json.py`, plus five diagnostic
`file="refdes.yaml"` strings in `imports.py` and `build.py` — and also `cli.py`,
`calc.py`, `pages.py`, `workspaces.py`, `boards.py`, `model.py`,
`standards.py`), all of them source references — which was the estimate's
mistake: it stopped at the source tree, and any finding that touches a
widely-used filename or field name should count the test suite too, because
that is where the footprint actually lives. The suite held 489 references
across all 32 test files; 10 of those files define a `types:`/`link_types:`
overlay, so they needed a two-way fixture split rather than a rename, and
because 27 files under `tests/` import `helpers.py`, a shared conftest helper
had to land before any parallel batch could run — the fixture migration had to
be phased. The rename is still mechanical; the hard part is that every existing
project needs its config split in two and `refdes revise` cannot help, because
it rewrites item files, not config layout — so this needs a dedicated one-shot
migration command or a documented manual procedure, and it is a breaking change
that belongs at a version boundary. Finding 27 needs this settled first, to
know which file `equations:` belongs in.

**Status: outstanding.** `schema.py` still names its two files `CONFIG_NAME =
"refdes.yaml"` and `PROJECT_SETTINGS_NAME = "refdes-project.yaml"`, with the
same split (and the same contradiction) as when the finding was written.

**Local model (not decided — my read): not suitable.** The fourteen rename sites
are mechanical, but the acceptance condition is "every existing project still
loads, with every setting still read from the file it now lives in," and a key
left behind in the retired file is a setting that silently stops applying —
`site.out`, `id.width`, a board registry going quiet, not an error. That, plus
the migration command for other people's projects, is the no-op-that-looks-like-
success case the rule above is written to keep away from a smaller model.

---

## Internal review, findings 29–32

Recorded from this session's code review — unlike findings 12–24 and
25–28, these come from no GitHub attachment; the source note in each entry
says so.

### 29 — Figure references never resolve inside log entry bodies

**Source: internal review, not issue #7.** `log.html.j2:42` renders
`entry.body_html | safe` bare, while the other three body-rendering sites
wrap in `figured()`: `item.html.j2:62` (`figured(item.body_html)`),
`document.html.j2:78` (`anchored(figured(item.body_html))`), and
`page.html.j2:19` (`figured(page.body_html)`). `figured()` is the
per-document figure pass (`_figured`, `render.py:44-52`): it numbers every
`{id="..."}` figure across the document's bodies, then substitutes the two
deferred markers `resolve_figures` consumes (`build.py:1143-1177`) — the
`<span class="fig-num" data-fig="...">` number placeholder emitted by
`_apply_figure_attrs` (`build.py:1080`) and the
`<span class="fig-ref-pending" ...>` that a `[[fig:id]]` becomes in
`_linkify` (`build.py:905-910`). A log entry's body runs through
`_apply_figure_attrs` and `_linkify` like every other item's, so
`entry.body_html` carries both markers — the log template just never runs
the substitution that resolves them. The reader sees an empty spot where
"Figure N" should be (a caption that reads "— text", the number never
filled) and an invisible span where a `[[fig:id]]` link should be —
unresolved, unbeknownst to the author or the build. The fix spans two lines
like the other three sites, plus one wiring detail: the log page write
(`render.py:731-737`) passes no `figured` closure at all, so it would need
one built over the log entries' bodies the way the document page's is
(`render.py:777-779`) — numbering is per-document, and a figure in a log
entry is only "rendered on this page" if its body is in the closure's list.

**Status: outstanding.** `log.html.j2:42` still renders `entry.body_html |
safe` with no `figured()` call, and `render.py:731-737` still passes no
`figured` closure to the log page.

**Local model (not decided — my read): suitable.** The failure is visible in
the output (empty number, no link), not a silent wrong answer, and a test
asserting the log page renders the resolved "Figure N" link flags both
halves of the missing wiring at once — nothing unsettled in the design, it
is the same mechanism the other three sites already use.

### 30 — `_esc` does not escape single quotes

**Source: internal review, not issue #7.** Both `_esc` helpers —
`build.py:864-871` and `blocks.py:70-77` — escape `&`, `<`, `>`, and `"`
but not `'`. Latent, not a live bug: every generated attribute in these two
modules is double-quoted today — the `data-*` attributes on the
`fig-ref-pending` and `fig-num` markers (`build.py:905-909,1080`), the
`style=`/`id=` attributes `_apply_figure_attrs` emits (`build.py:1062,1079`),
and in `blocks.py` every `_esc` call lands in a text node, never an
attribute. A `'` inside double quotes is harmless HTML, and the escaping
hole opens only for a single-quoted attribute — but a bare apostrophe in
ordinary prose is all it takes, so the moment anyone adds a single-quoted
generated attribute the breakout exists with no warning at build time. The
fix is one more `.replace("'", "&#39;")` line in both helpers.

**Status: outstanding — latent, not a live bug.** Both `_esc` helpers still
omit `'`, and every generated attribute is still double-quoted.

**Local model (not decided — my read): suitable.** Two one-line
replacements, and a test asserting `'` escapes in the same spot `"` already
does makes the regression loud; nothing about this depends on taste or
unsettled design.

### 31 — No test covers the text-node XSS case

**Source: internal review, not issue #7.** Escaping is on and does handle
this case today — this is a coverage gap, not a live vulnerability. Jinja
autoescaping was silently off (`select_autoescape(["html"])` matches the
template-name suffix and every template is `*.html.j2`, so it returned
False for all of them) until this session's `render.py:600-608`
(`autoescape=True`, commit `5a1f212`), and the preview-data payload — the
one remaining `| safe` sink (`base.html.j2:60`) — was separately hardened
with `<`/`>` escaped to `\u003c`/`\u003e` at dump time (`render.py:629-639`,
commit `b88f2f1`). The two regression tests pin exactly those two contexts:
`test_citation_page_value_is_html_escaped` (`tests/test_citations.py:723-745`),
an attribute-context breakout of a citation `page:` value, and
`test_preview_data_escapes_script_close` (`tests/test_render_assets.py:517-559`),
the JSON payload. Nothing exercises the plain text-node case — an item
title like `T<script>alert(1)</script>` rendered where
`{{ item.title }}` appears (`index.html.j2:54,81`, `coverage.html.j2:48`).
That site is precisely where a future `| safe` addition would silently
reopen an escaping hole with no failing test to catch it.

**Status: closed.** `tests/test_text_node_escaping.py` renders an item titled
`T<script>alert(1)</script>` and asserts on both `index.html` and
`coverage.html` that the escaped `&lt;script&gt;` form appears and the raw
`<script>alert(1)</script>` does not. Sabotage-checked: adding `| safe` to
the `item.title` renders in `index.html.j2` makes the index test fail.

**Local model (not decided — my read): suitable.** The task is its own
acceptance test — render an evil-titled project and assert both that the
escaped form appears in `index.html`/`coverage.html` and that the raw
`<script>` never does. The quiet-failure mode this gap warns about is made
loud by the test itself; nothing unsettled in the design.

### 32 — Log entries sort by raw string, not by date, so mixed date formats silently produce a wrong chronological order

**Source: internal review, not issue #7.** Three sort sites order `log` items
by the same key, `(str(i.fields.get("date", "")), i.id)`: `render.py:82`
(`_document_sections`, the linear-reading grouping), `render.py:118`
(`_log_entries`), and `render.py:249` (`summary_payload`'s log list, sorted
`reverse=True`). That is a lexicographic *string* sort, not a date sort. ISO
format (`2026-03-16` — what every example in this project's own docs and item
files already uses, e.g. `docs/authoring.md:45`, `docs/design-log.md:24`,
`items/board-a/log.yaml:29`) happens to sort correctly as a string, because
ISO is designed for that: fixed-width, most-significant field first, so year
outranks month outranks day. Any other format does not: `03/16/2026` written
for a March log entry sorts *before* `2026-01-05` written for a January entry
that is chronologically earlier, because '0' < '2' at the first character, so
the January entry lands below the March one regardless of actual chronology.

No date parsing, coercion, or format validation exists anywhere in the
schema/parse layer — verified against `src/refdes/schema.py`,
`src/refdes/parse.py`, and `src/refdes/model.py`. `FieldSpec` records a
field's `type:` as declared and never touches its values
(`schema.py:518-526`); `parse.py` hands a `date:` value through unchanged as
the raw string it was written in; and the one pass that validates values per
type, `build.validate_items()` (`build.py:135-183`), dispatches on `enum`
(choice membership), `limit` (parsing), and `citations` (shape) — `date` has
no branch at all. A `type: date` field is accepted as an arbitrary string
today with zero format checking; verified, not assumed.

**Decision — `date_format:` is a top-level project setting.** Declared in
`refdes-project.yaml` alongside the existing `units:` (`refdes-project.yaml:28-36`),
`history:` (`refdes-project.yaml:24-26`), and `id:` (`refdes-project.yaml:20-22`)
settings, which are the precedent for shape; its validation belongs in
`_validate_settings()` (`schema.py:100`), and the key must be added to
`_KNOWN_SETTINGS` (`schema.py:68`) or the settings file's unknown-key check
(`schema.py:107-119`) will refuse to load it. (Not in the finding — recorded
from conversation.)

**Decision — the default is strict ISO.** If `date_format:` is never declared,
refdes defaults to `YYYY-MM-DD` and rejects anything else. This is not a
breaking change for a project already following the documented convention —
only for one already silently mixing formats, which was already broken and
just didn't know it. (Not in the finding — recorded from conversation.)

**Decision — `-`, `/`, and `.` are interchangeable separators.** For whichever
format is configured, all three are accepted (e.g. `date_format: MM/DD/YYYY`
also accepts `MM-DD-YYYY` and `MM.DD.YYYY`), so the separator is not part of
the declared format. (Not in the finding — recorded from conversation.)

**Decision — a non-conforming date is a hard build error.** A value that does
not match the effective format (declared or default) fails the build — never a
silent accept, never a silent mis-sort — matching this project's existing
"refuse rather than guess" posture (an unregistered board, an unknown
`{{index}}` tag, and `vendor: true` on a local citation path are all hard
errors for the same reason). Auto-detecting the format instead was explicitly
rejected: a value like `01/02/2026` is genuinely ambiguous (Jan 2 or Feb 1)
with no safe guess. (Not in the finding — recorded from conversation.)

**Decision — the three sort sites sort on a parsed date.** Once a value is
known to conform to the effective format, `render.py:82`, `render.py:118`, and
`render.py:249` sort on that parsed date, not the raw string. (Not in the
finding — recorded from conversation.)

**Status: outstanding.** All three sites (`render.py:82,118,249`) still sort on
the raw string; a search of the whole tree finds no `date_format:` key
anywhere; and `build.validate_items()`'s per-type dispatch (`build.py:157-183`)
still has no `date` branch.

**Local model (not decided — my read): suitable.** The bug itself is this
project's characteristic failure — a build that reports success while ordering
the log wrongly — but the spec makes it loud, exactly as the rule above
requires: the negative test (a non-conforming date value must be a hard build
error) is sharp, mechanical, and nameable, and the discriminating sort test is
equally concrete (two dates in the same declared format whose string and
parsed orders diverge — `01/05/2027` vs `03/16/2026` under `date_format:
MM/DD/YYYY` sorts one way as strings and the opposite as dates). The fix is
bounded — one new setting validated in `_validate_settings()`, one conformance
check, three sort-key changes — and the design is settled (the five decisions
above): nothing here depends on taste or an unsettled tradeoff.

---

## Surrogate keys — remaining layers

`docs/design/keys.md` §1 (key format), §2 (minting), §3 (composite expansion
and key-based resolution), §5 (hashing on the key, plus the baseline/seal
hash-format migration), and §6 Layers 1-3 (well-formedness, uniqueness, and
unknown-key resolution) are implemented — see that document's own
implementation-status header for the module list.

**Status: partially implemented.** §6 Layers 1-3 are implemented. What's
decided but not yet built:

- **The remaining corruption lint (§6 Layers 4-5)** — the baseline lint that
  catches a changed-but-still-present key by cross-referencing the most recent
  baseline, plus the informational audit of older baselines.
- **`refdes keys adopt` (§7)** — one explicit, transactional command for an
  existing project: mint every key, expand every link reference to
  composite form, re-key baselines and seals under §5(c)'s conditional
  carry-forward rule, reusing `revise.apply`'s existing compute-in-memory/
  verify/write-or-roll-back safety model wholesale.
- **The display-half refresh-on-rename mechanism (§3)** — when a display id
  changes, rewriting the readable half of inbound composites on the next
  writable command, with the three-way distinction from §3 (ordinary rename:
  silent; label now matches a *different* live item: warn, don't
  auto-refresh; key doesn't resolve: error, no display-id fallback).
- **The subtractive cleanup in `revise.py`/`former_ids.py` (§4)** — roughly
  166 lines of `revise.py`'s prefix-rename machinery (`_rewrite_reference_ids`,
  `_rewrite_block_sequence`, `_rewrite_id_tokens`, `_rename_prefix`,
  `_relabel_id`, `_relabel_ledger`, `_restore_ledger`) delete outright once
  keys make a prefix rename non-transactional; `former_ids.propose`'s
  similarity-scoring/confidence/`--confirm` machinery shrinks to just the
  external-citation case, since the internal "which new item replaced this
  old id" question becomes a lookup instead of a guess.

**Two disclosed gaps, not fixed by any of the above, and not scheduled:**

- **`checks: [{value, against}]` still resolves `against:` as a bare display
  id.** It isn't a `links:` reference at all — it's a field entry inside
  `checks:` — so `links.expand_missing()` never sees it and it is not
  rename-safe under the current implementation. Keys.md calls this "a real,
  disclosed gap, not an oversight."
- **Imported cross-project links carry no key.** `imports.py`'s payload has
  no `key` field today, so a link to an item from another, imported project
  can never be composite-expanded. Closing it means extending the
  cross-project export/import contract — "a separate change with its own
  collision considerations," per keys.md, not attempted here.

**Local model: not assessed for any of the above.** All four remaining
layers touch identity/correctness machinery directly (the corruption lint
*is* the mechanism that catches identity corruption; the adoption command
rewrites every item file and baseline in one transaction; the two disclosed
gaps are already-known correctness holes). None of this was discussed
against the suitability rule in conversation, and I'd rather leave it
unmarked than guess at a rule this consequential.
