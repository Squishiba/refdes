# Backlog — decisions on outstanding work

**This is a decision record, not a spec.** The other files in `docs/design/`
specify a mechanism in enough detail to implement from. This one instead
tracks *that a piece of work was decided on*, and what was decided, so that
agreement reached in conversation isn't stranded in a chat log the next
session can't see. An entry here earns its own `docs/design/<name>.md` (spec
detail, alternatives considered, a "what I'd prototype first" section) once
someone actually starts implementing it — until then, this is the whole
record.

Verified against the actual codebase as of commit `cd6bf4a` (2026-08-29,
`main`). Re-check before trusting an "outstanding" or "done" mark that's more
than a few commits old — this file decays exactly like the implementation
status headers on the spec docs do.

## Source

Findings 12–24 below come from GitHub issue #7, whose body is a fetched
attachment, not a file in this repo:
<https://github.com/user-attachments/files/31488284/refdes-feedback.md>
(fetched 2026-08-29). Read in full before writing this — summaries below are
my own reading of that document, not a re-statement of anyone else's
paraphrase; where a shorthand I'd previously been given didn't match what
the document actually says, that's flagged inline in the entry.

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

**Status: outstanding.** Both the `docs/authoring.md` passage and the
`parse.py:30` comment still state the false rationale verbatim, unchanged.

**Local model: suitable.** Scoped to two files, the wrong text and its
replacement are both given in the finding, and a reviewer can check the
result by eye — no design judgment involved.

### 13 — `{{index}}` needs a `tag=` filter parameter

`{{index}}` can filter by `board=` but not by `tag=`, even though `tags:` is
the field this project already uses for cross-cutting grouping that doesn't
follow board or type lines (finding 9's argument). Scoped deliberately as
one more fixed, named, single-valued parameter — not a query language — to
stay inside `blocks.py`'s own stated non-goal.

**Status: outstanding.** `blocks.py`'s `index` `BlockSpec` still declares
only `optional=("board",)` — no `tag`.

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

**Local model: not suitable.** The whole point of this type is what it must
*not* do (not coverable, not a satisfaction target) — the failure mode is a
silently-too-permissive implementation that looks like it works until
someone accidentally claims a group and coverage goes quiet about it. That's
the "reports success while doing nothing" failure this project is
characteristically bad at catching, and exactly what the suitability rule
above says to keep off a smaller model.

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
the form can do. **Depends on findings 8, 9, 10, and 13** (id completion by
file/board, `refdes ls`, `next_ids` for id pre-fill, and this backlog's own
finding 13) — the finding's own dependency table lists exactly these.

**Status: outstanding.** No `CustomTextEditorProvider` exists in
`editors/vscode/extension.js`.

**Local model: not suitable.** This is design-judgment-heavy UI work with no
mechanical acceptance test — "does this feel like the right form" isn't
something a failing test catches, and it's an epic depending on four other
findings landing first.

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

**Status: outstanding.** `decision.links` (hardware@3) declares
`satisfies`/`constrained_by`/`supersedes`/`selects`/`blocked_by` — no
`recorded_by`.

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

**Status: outstanding.** `calc.py`'s `_SEGMENT`/`_UNIT_RUN` are unchanged
from what the finding describes — `Ω` still first-position-only, `%` still
only reachable through `PERCENT_RE`'s tolerance special case.

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

**Local model: not suitable.** Two distinct, interacting mechanisms (generic
field fragments and citation identity) plus a `revise.py` staleness
interaction to get right — this is exactly the kind of "did I actually wire
every consumer" problem `docs/design/keys.md` documents costing real,
disclosed effort even for its authors; a smaller model is more likely to
ship a fragment that resolves for the common case and silently doesn't
validate or doesn't get flagged stale by `revise`.

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

**Status: outstanding.** `docs/schema-reference.md` documents types
abstractly only; no generated-example step exists anywhere in the docs
build.

**Local model (not decided — my read): not suitable.** The finding itself
flags the real wrinkle — `docs-site/refdes.yaml` pins no `standard:`, so the
generator has to run against a *different*, standard-pinned project and get
injected into docs built from `docs-site/`. Getting that wiring subtly
wrong produces docs that build successfully and show stale or wrong
examples — quiet, not loud, which is the failure mode the suitability rule
above is written to keep away from a smaller model.

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

**Local model: not suitable.** This changes link-target-validation semantics
project-wide (universal substitution touches every `[requirement]` target
across the standard and every preset) — getting substitution scope subtly
wrong is a silent over- or under-acceptance of link targets, not a crash,
and the finding's own design-questions section shows how much judgment went
into even deciding the substitution rule was safe.

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

**Status: outstanding (both parts).** `CitationSpec` carries `page` but
templates only render it into a `<td>`, never into an `href`
(`item.html.j2:119`, `document.html.j2:127`); there is no `section:` field
and no outline-resolution code anywhere in `citations.py`.

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

**Local model: not suitable.** Depends on finding 14 (the grouping type)
landing first, touches coverage computation itself (the single most
consequential place in this codebase for a silent wrong-answer, per finding
24's own framing — "the failure mode is silent and optimistic"), and the
finding's own "one detail to settle during implementation" (an unregistered
group must hard-error, or a typo silently discharges an entire board's
obligations) is precisely the kind of edge a smaller model is liable to
skip without anyone noticing until much later.

---

## Surrogate keys — remaining layers

`docs/design/keys.md` §1 (key format), §2 (minting), §3 (composite expansion
and key-based resolution), and §5 (hashing on the key, plus the
baseline/seal hash-format migration) are implemented — see that document's
own implementation-status header for the module list. What's decided but not
yet built:

- **The corruption lint (§6)** — four layers of detection that fall out of
  one property (a key has no legitimate reason to ever change): malformed
  key well-formedness, uniqueness-within-scope, unknown-key resolution
  errors, and the baseline lint that catches a changed-but-still-present key
  by cross-referencing the most recent baseline.
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
