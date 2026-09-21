# Backlog — decisions on outstanding work

**This is a decision record, not a spec.** The other files in `docs/design/`
specify a mechanism in enough detail to implement from. This one instead
tracks *that a piece of work was decided on*, and what was decided, so that
agreement reached in conversation isn't stranded in a chat log the next
session can't see. An entry here earns its own `docs/design/<name>.md` (spec
detail, alternatives considered, a "what I'd prototype first" section) once
someone actually starts implementing it — until then, this is the whole
record.

Verified against the actual codebase as of commit `e73ffea` (2026-09-15,
`main`). Re-check before trusting an "outstanding" or "done" mark that's more
than a few commits old — this file decays exactly like the implementation
status headers on the spec docs do.

## Source

Two documents, GitHub attachments on issues #6 and #7, neither a file in
this repo:

- **Findings 1–11** come from the attachment on **issue #6**:
  <https://github.com/user-attachments/files/31321364/refdes-feedback.md>
  (posted 2026-08-21). The issue #7 documents re-post these same findings as
  their 1–11; all eleven were implemented before this backlog file existed,
  and are recorded in their own section below.
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

## GitHub issues #6/#7, findings 1–11

All eleven shipped before this file existed, so these entries record what
landed and where, not decisions still open. Titles are as GitHub states
them (the 2026-09-01 re-posting; issue #6's attachment carries the same 1–11).

### 1 — No published or CI-built copy of the reference docs site exists anywhere

**Status: shipped, not yet deploying.** Shipped in `089fdbe`:
`.github/workflows/docs.yml` builds `docs-site/` and deploys it to GitHub
Pages on every push to `main` (`actions/configure-pages` +
`actions/deploy-pages`). `1f1ec03` later added the
`docs-site/gen_examples.py --check` staleness gate to the same workflow's
build job (finding 20). It is not yet deploying, though: every run of the
workflow since it was added (56 runs, first 2026-08-22) fails at
`actions/configure-pages` with "Get Pages site failed ... verify that the
repository has Pages enabled and configured to build using GitHub Actions"
(HttpError Not Found) — the repository has Pages disabled (`has_pages:
false`). The build steps pass (pip install, `gen_examples.py --check`,
`refdes build` in `docs-site/`). The fix is a repository setting, not code:
Settings → Pages → Build and deployment → Source: GitHub Actions.

### 2 — `section:` markers validate fine in `refdes check` but fail every schema in the editor

**Status: done.** Shipped in `c659c23`: `schema_json.py` emits a
`section_marker` def — `section` the one key, `additionalProperties: false`,
mirroring `parse.py`'s `_only_key()` rule — appended to the list file's
`items:` `oneOf`, exactly as the finding scoped it (YAML list files only).

### 3 — Unify `text:`/`title:` into one field name for `requirement`/`bound`

**Status: done-differently.** The finding proposed renaming `text:` to a
required `title:` on both types. What shipped instead, in `50cf460`
(hardware@3, "text/method fold into body … field unification"), folded
`text:` into a required `body:` and made `title:` optional on both — the
opposite polarity. `v3/migration.yaml` carries `text:`/`method:` → `body:`
across, with `revise.check_body_merge_conflicts` refusing rather than
silently overwriting an item that already has its own body. No decision by
Jared was recorded for the divergence; this states what shipped.

### 4 — Nothing explains `note:` vs `source:` vs `rationale:` vs `body:`

**Status: done.** Shipped in `dd203e3`: `docs/authoring.md` gained a
"`source`, `note`, `rationale`, `body`" section laying the four out side by
side with their `on_change:` split (`source`/`note` = `log`,
`rationale`/`body` = `invalidate`), plus a pointer in `docs/standard-library.md`.

### 5 — `refdes build` has no `--dry-run`, despite having a real, permanent side effect

**Status: done.** Shipped in `c85deda`: `cmd_build` passes
`seal_write=not (args.dry_run or args.no_write)`, and the finding's
watermark half shipped too — `render_site(project, draft=…)` sets
`env.globals["draft_build"]` (`render.py`), read by `base.html.j2`.

### 6 — A file's `defaults:` leak type-specific values onto an item that overrides `type:`

**Status: done.** Shipped in `10b7263`: `Item.inherited_fields` and
`Item.defaults_line` (`model.py`) record which values came from the file's
`defaults:` block and from which line, so a validation failure on an
inherited value says so and points there instead of blaming the item
(`parse.py`'s merge sites, `build.py`'s enum check).

### 7 — `requirement` has no verb for "must comply with a rule stated elsewhere", and `component` has no path to `bound` at all

The two versions of this finding differ. The revised one (identical in the
issue #7 body and the 2026-09-01 comment) withdraws the original
`governed_by`/`governs` proposal and asks instead to widen `constrained_by`
to `[requirement, bound]` and declare it on `requirement` and `component`.

**Status: done — the component half as revised, the requirement half superseded by decision.**
The component side matches the revision in hardware@3 (`50cf460`):
`component.links` carries `satisfies: [requirement, bound]` and
`constrained_by: [bound]`, and `component` gained a `checks:` field. The
requirement side did not: `requirement.links` carries
`governed_by: [requirement, bound]` (inverse `governs`), shipped in the same
commit from the *issue #6* version of this finding, before the revision
existed.

**Decision — keep `governed_by`.** Jared chose on 2026-09-15 to keep
`governed_by` over the revised widen-`constrained_by` proposal. No rationale
was recorded.

### 8 — Item-id completion can't be narrowed by which file an item lives in

**Status: done.** Shipped in `1044c96`: the extension's completion
`filterText` now includes each item's source file and board alongside id and
title (`editors/vscode/extension.js`).

### 9 — There's no way to list or browse existing items from the CLI at all

**Status: done.** Shipped in `491283e`: `refdes ls` (`cmd_ls`, `cli.py`)
prints id, type, board, and title as aligned text — the board column omitted
when the project has no boards — filterable by `--type`, `--board`, `--file`,
and a free-text query that matches `tags:` as well as title.

### 10 — Completing a partially-typed id should offer the next free number

**Status: done.** Shipped in `c743328`: the index payload carries
`next_ids` (`render.py`), the next number `refdes id` would hand out per
prefix, reusing `ids.high_water()` as-is. The finding's part 2 (orphaned
ledger allocations) landed separately and informationally in `ebc1c8f`, as
a `refdes audit` report.

### 11 — An "untagged item" lint would fire on nothing — the useful signal is an item with no tags *of its own*

**Status: done.** Shipped in `a1bcdf0`: `build.lint_own_tags` warns when an
item's `tags:` are entirely inherited (via finding 6's `inherited_fields`)
or absent, skips types that declare no `tags:` field, and is opt-in via
`lint_own_tags: true` — sequenced after finding 9 so the warning points at
tags that are actually searchable.

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

**Status: done.** Shipped in `1330dee`. hardware@3's `group` type (GRP prefix,
`part_of` link, `contains` computed backlink) is declared in
`src/refdes/standards/hardware/v3/base.yaml`; `coverable: false` keeps groups
out of coverage, and every existing item type that should be able to join a
group already declares `part_of: [group]` in the same file. See also
`changelog.d/hardware-v3-group-type.added.md`.

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

_(Finding 14 has landed — the grouping type exists in hardware@3 — so the
dependency blocking finding 24 below is removed.)_

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

**Status: architecture decided (2026-09-16); remaining work is v1 scope, not
shape.** [`browser-editor.md`](browser-editor.md) settled on option B — a local
`refdes serve` whose rendered site is the preview, with a separate `/edit/`
application over the same plain files, so `_site/` stays static and the
“Edit this item” affordance exists only while the server runs. Its **Decisions**
section records the calls that followed from that, and **What v1 must deliver**
is the checklist to build against. Two items there are what make this more than
a form, and both are the author's own stated pain points: **filtering** as a
first-class surface (type, board, workspace, tag, source file, coverage stage,
check state, blocked state, link relationships, and free text — combinable,
counted, and held in the URL), and **identity handled for the author** (no
hand-typed IDs anywhere: `next_ids` offered at creation, allocation
authoritative under the save lock, link composites written from a picked key).
No implementation exists.

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

**Status: done, both parts.** `EXPLICIT_REF_RE` now admits
`ID#field` (and `ID#field|label`), and `_linkify` renders it as a link to that
field's row on the target's page — never as the field's value. `item.html.j2`
gives every declared field an `id="field-<name>"` anchor: on its table row, on
the section that renders it instead of a row (`options`, `checks`, a citations
field), or — declared but empty — on a collapsed empty row. Not `hidden`: an
element with no layout box is never scrolled to, so a hidden placeholder is a
link that navigates nowhere. An undeclared field is a
warning naming item, field, and type; an unknown item with a fragment warns
exactly as an unknown item without one. Tests: `tests/test_field_refs.py`.

**Part B**, shipped separately: a citation entry gains an optional declared
`id:` (`CitationSpec.id`, validated against the same character class
`EXPLICIT_REF_RE`'s own id group admits — an id outside it could never be
addressed by `[[cite:...]]` anyway, so it's rejected at declaration instead
of accepted and left permanently unreachable), unique across the whole
project the same way a figure id is (`project.citation_ids`, populated and
checked in `build.validate_items` since every citation is known from parsed
data alone — no render-time deferral needed, unlike a figure's per-document
numbering). `[[cite:<id>]]` (or `[[cite:<id>|label]]`) resolves directly
against that registry to a link on the declaring item's own page
(`<a class="ref cite-ref" href="...#cite-<id>">`); an unknown id warns and
renders the missing-ref span, and a `#fragment` on a cite ref warns exactly
as it does on a fig ref. `item.html.j2` puts `id="cite-<id>"` on the matching
row in the Citations table. `revise.py`'s `_stale_prose_references` now
reports a stale `[[ID#field]]` fragment two ways: the existing whole-id
check already caught `[[OLD-ID#field]]` after an id rename (the id token
underneath the brackets and fragment was always what `_ID_TOKEN_RE`
matched); newly, `[[ID#old_field]]` is reported when the same rename mapping
also renamed that field on the id's own (pre-rewrite) type, which
`id_changes` alone could never catch since the id itself need not have
changed. Tests: `tests/test_citation_ids.py`,
`tests/test_revise.py::test_revise_reports_a_stale_bracketed_field_fragment_after_an_id_rename`
and `::test_revise_reports_a_stale_field_fragment_after_a_field_rename`.

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
types duplicate nearly every field (`title`, `rationale`, the full `status:`
enum, `coverable`, `include:`, `body:`) for one real difference (`limit:`,
required). Proposed: single-level `extends:` with universal (Liskov)
substitution — any `[requirement]` link target accepts a `bound` too, no
opt-in marker — reasoned through at length in the finding, including
reversing its own earlier draft's opt-in-marker proposal once finding 22
established that `satisfies` excluding bounds was a defect, not a deliberate
boundary. The four `[requirement, bound]` link target lists collapse to
`[requirement]`. Coverage grouping (bounds under requirements vs. their own
section) becomes a project setting, defaulting to current (separate) behavior —
superseded by Jared's 2026-09-19 decision, which makes grouping the default for
every project; see the Status below. `extends:` resolves on the fully merged schema (after base →
presets → project overlay), so project overlays adding fields to `requirement`
are inherited by `bound`. Adopting `extends:` for `bound` in `hardware@3`
churns no hashes (`item.type` stays `"bound"`); no migration.yaml entry is
needed. Preset adoption (design-debate's `debate`) waits for threads Phase 4.

**Status: decided (Jared, 2026-09-19); implemented on ao/refdes-113 (phases 1-4, preset adoption still deferred).** Spec at
[`docs/design/extends.md`](extends.md) — states the substitution rule (universal
Liskov, no opt-in marker), ALLOW vs LISTING consumer classification (§3.2),
single-level enforcement, `include:` and `body:` inherited, `prefix`/`label`/
`plural` declared by child, field override replaces whole definition,
hardware@3 adoption for `bound` now (hash-neutral, no migration), preset
adoption after threads Phase 4. **All five open questions in extends.md §9 are
decided (2026-09-19), each as recommended — with one overturn of the spec's own
recommendation: coverage grouping is the default, period.** The default is
`coverage.group_inherited: true` for every project, new and existing, so an
existing project that rebuilds gets one grouped coverage section where it used
to get separate ones; a project that wants the old output sets
`coverage.group_inherited: false`. The spec's original `false` default is kept
there as the rejected option.

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

**Status: both parts done.** Part 2 shipped as `section:`: `CitationSpec.section`
(`model.py`) is authored intent, `resolve_sections()` (`citations.py`) walks the
outline of the bytes being pinned with pypdf and records `{section: page}` in
the lockfile record, and `_apply_section()` at build time reads that record and
sets `CitationStatus.section_page` — no PDF is opened outside `refdes fetch`.
Every failure is a `FAILED` line from `fetch` and a nonzero exit, naming the
path, the section and every citer: no outline, no matching title (with
`difflib` hints), an ambiguous title, an unreadable file, a missing
`refdes[pdf]`, or — on `--update` — a previously resolved section that the new
revision no longer has, reported with the page it used to be on. `page:` still
wins where both are given, warning on disagreement. `section:` is refused at
build time on a hash-only remote citation, since those bytes are not guaranteed
local.

The invariant that took the most thought: **a page is a fact about specific
bytes.** The record therefore stores `sections_sha256` beside `sections`,
`_apply_section()` refuses to use a page whose sha256 is not the sha256 now
pinned (warning instead), `_section_bytes()` will not resolve a local path whose
file has moved since it was pinned, and a re-pin re-resolves every section any
item in the project cites for that path — not the run's scope — because
`fetch --update --item A` replacing the bytes makes every recorded page of that
file stale, whether or not item B was asked about. Sections nobody cites are
dropped rather than accumulated. Without all four, the feature's failure mode is
the one this codebase cannot have: a confidently wrong link and no word said.

Part 1 shipped in `a077cb2`:
`item.html.j2` now appends `#page={{ c.spec.page }}` to *both* citation hrefs —
the upstream link and the published `local copy` link — guarded on `page` being
set, with the visible link text unchanged. Part 2 kept that template alone:
`section_page` reaches the href through the same guarded expression, as the
fallback when `page` is unset. `document.html.j2` and `references.html.j2`
remain deliberately untouched — the latter groups by URL across citers, where a
per-citation page would be misattributed.

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

**Status: shipped.** `BoardSpec.conforms_to` (parsed in `schema.py`, hard-
errored by `build.validate_conforms_to` when a target is not an existing group)
drives `build.compute_board_coverage`, which computes the same four stages per
(item, board) counting only that board's own satisfiers — an unboarded
satisfier counts for no board — warns on every pair short of `satisfied`, and
renders as a Conforming contracts table on `coverage-<board>.html` plus a
"not yet satisfied on boards: …" note on the project-wide page. A project
with no `conforms_to:` anywhere keeps its coverage output unchanged.

**Local model: suitable.** Finding 14 has landed — the grouping type exists in
hardware@3 — so the dependency is removed. The feared edge remains the same: an
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

**Status: both parts done.** Part 1 shipped in `f8e7ee0`:
hardware@3's `field_sets:` has a third entry `citations: {citations: {type:
citations, on_change: invalidate}}`, and both `component` and `decision` now
`include: [provenance, stewardship, citations]`, with the `migration.yaml`
rename above and this repo's own `items/components/power.yaml` moved over.
Part 2 shipped next: `CitationSpec.path` dispatches on scheme (`citations.classify`
— `http`/`https` remote, everything else a project-root-relative local file, with
drive letters, backslashes, absolute paths, `..` and symlink escapes all refused);
local files are pinned by `refdes fetch` reading from disk, re-hashed at every
build, published as content-addressed copies at `assets/citations/<sha256><ext>`,
and a changed-but-unre-pinned file is one warning naming every citer (error under
`--require-citations`). `vendor:` on a local path is a hard error at both validate
and fetch. The lockfile keeps its shape, keyed by the `path:` value — the two
namespaces are disjoint because remote keys always carry `http(s)://`, so no
lockfile migration was needed. The `revise.py` blind spot closed as a new global
`Mapping.citation_keys` category, applied inside every `citations`-typed field's
entries, with `citation_keys: {url: path}` in hardware v3's `migration.yaml` — and
a stale `url:` in any project now fails validation with a message naming the
rename and pointing at `refdes standard upgrade`.

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

**Status: outstanding — design drafted, awaiting review.** No `xlsx`/`csv`/
`openpyxl` reference exists anywhere in the package, and the lockfile records
hashes only, never extracted values. The blocker that parked this finding —
finding 25's Part 2, a citation being able to name a repo-local file — has
landed on `main` (`2001801`, `4496053`, 2026-09-15), so the finding is no
longer parked; only review of the draft design stands between it and
implementation. The draft also answers a question someone will ask again:
item-based aggregation (summing a field over a set of items) was considered
and rejected, for the completeness reason recorded in
`docs/design/calc-sources.md` §2.
**Design:** `docs/design/calc-sources.md` is the draft implementation specification, awaiting Jared's review.

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

**Status: done.** Shipped in `c96d96b`. `src/refdes/calc.py` now exposes
`Equation`, `set_equations`, and `validate_equations`; `src/refdes/schema.py`
loads an `equations:` block from `refdes-project.yaml` (validated in
`_load_equations`), checks for cycles, shadowed builtins, and duplicate params,
and hands the result to `calc.set_equations`. The project-wide namespace is
wired end-to-end. See also `changelog.d/calc-project-equations.added.md`.

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

**Status: done.** Shipped in `aa94058`. `src/refdes/schema.py` now defines
`PROJECT_SETTINGS_NAME = "refdes-project.yaml"`, `SCHEMA_NAME =
"refdes-schema.yaml"`, and `LEGACY_CONFIG_NAME = "refdes.yaml"` — the latter
triggers `LEGACY_CONFIG_ERROR` telling users to split and delete it. All
project settings (including `site:`, `id:`, `boards:`, `units:`, `standard:`,
`equations:`, etc.) live in `refdes-project.yaml`; the optional
`refdes-schema.yaml` holds only `types:`/`link_types:`/`field_sets:` overlays.
See also `changelog.d/config-split-two-files.breaking.md`.

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

**Status: fixed.** `log.html.j2` now renders `figured(entry.body_html)`,
and every log page write in `render.py` — the unscoped `log.html` plus the
per-board and per-workspace `log-<key>.html` pages — passes a `figured`
closure built over that page's own log entries' bodies, the same shape the
document page uses. Covered by
`tests/test_render_assets.py::test_figure_reference_resolves_on_the_log_page`.

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

**Status: fixed.** Both `_esc` helpers now escape `'` as `&#39;` after the
existing `&`, `<`, `>`, and `"` replacements.

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

**Status: done.** Shipped in `c0d1722`. `src/refdes/dates.py` provides
`parse_date` (strict calendar-date parsing accepting `-`/`/`/`.` separators)
and `validate_format`; `src/refdes/render.py`'s `_date_sort_key` calls
`dates.parse_date(value, project.date_format)` to produce an ordinal for
chronological sorting, and all three sort sites (`render.py:97`, `render.py:133`,
`render.py:264`) now use it instead of a raw string key. `date_format:` is a
project setting validated in `_validate_settings()` and defaults to strict ISO
(`YYYY-MM-DD`); `build.validate_items()` rejects non-conforming dates as hard
build errors. See also `changelog.d/date-format-log-sort.fixed.md`.

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

## Field report, finding 33

Recorded from Jared's use of refdes at work — no GitHub attachment, no code
review. The source note says so, as it does for 29–32.

### 33 — A component used by several boards belongs to none, so it is missing from every board's pages

**Source: field report, not issue #7.** A part used by two boards — the same
rail-to-rail LDO on Board A and Board B, one datasheet, one selection, one
`part_number` — has no home folder. It is not Board A's and it is not Board
B's, so it goes in `items/shared/`, and `shared` is not in the `boards:`
registry. That is deliberate on refdes' part: an unregistered segment gets no
board and "that is not an error, since shared items legitimately belong to
none" (docs/multi-board.md:46-49). What is not deliberate is the consequence.
Every board-scoped surface filters on the item's own resolved board, so the
shared component is absent from `parts-board-a.html` **and** from
`parts-board-b.html` — the two pages that exist to answer "what is on this
board" — while both boards' items `selects:` it. The part number is in the
project-wide parts page and on the component's own page, and nowhere a
board-scoped reader looks. Nothing fails, because the defect is an absence.

**What exists today, verified.** Resolution is one-way and single-valued:
`boards.resolve()` (boards.py:73-113) takes the item's own `board:` hint —
which `parse.py:423-424` sets after merging the file's `defaults:` under it,
so item beats file before this module is ever consulted — hard-errors it if it
names nothing in the registry, and otherwise falls back to `_derive()`
(boards.py:68-70), a single path segment looked up in a single `path_segment →
board key` index (boards.py:38-41, `_board_segment` 60-66). The result lands
in `Item.board`, one `str` (model.py:430). There is no set, no list, no
second chance. The surfaces that then read it, all with the same
`item.board != board → skip` shape:

- `render._in_scope` (render.py:57-64), the one filter shared by
  `_document_sections` (render.py:81) → `document-<board>.html`,
  `_coverage_rows` (render.py:112) → `coverage-<board>.html`, `_log_entries`
  (render.py:157) → `log-<board>.html`, and `summary_payload`
  (render.py:351-367) → `summary-<board>.html`;
- `citations.by_path` (citations.py:416-436, filter at 430) →
  `references-<board>.html`, and `citations.by_part_number`
  (citations.py:439-470, filter at 456) → `parts-<board>.html`;
- `nav.scope_reports` (nav.py:55-92, filter at 77-81), which decides not what
  a page shows but **whether the page is written at all** — a board whose only
  parts live in `shared/` gets no `parts-<board>.html` whatsoever, and no nav
  link to one;
- the `{{index}}` block's `board:` parameter (blocks.py:132-167);
- `cli._visible` (cli.py:150-174) and the item count beside it (cli.py:195),
  i.e. `refdes check --board board-a`, and `refdes ls --board` (cli.py:471);
- `seal.append_only_items` (seal.py:187-197), which is why an unboarded log
  entry's seal lives in `.refdes/log-seal.yaml` while its board neighbours
  live in `log-seal-<board>.yaml` (seal.py:42-47);
- `build._board_gate` (build.py:611-623), where an unboarded satisfier
  "counts for *no* board" — stated as a feature there, and it is one, for
  obligations.

Correctness is not the problem. Links are project-wide and boards never scope
them — `links.py` contains no reference to boards at all (grep count: zero) —
so a decision on Board A already `selects:` the shared component, the
component's page shows both boards' incoming links, and `refdes check` without
`--board` checks the whole thing correctly. `PartUsage.boards`
(model.py:336-340) even reports which boards a part number is used by, derived
from the boards of the items that name it — and for a part named only by
shared components that set is empty, so the project-wide parts page renders
"—" in its Boards column (parts.html.j2:36-38) for exactly the parts this
finding is about. Visibility is the problem, and one surface has already
admitted that: `_contract_rows` (render.py:128-145) is the single board-scoped
render site that says out loud it is "NOT scoped by `_in_scope`", because
finding 24's whole point was listing an item that lives elsewhere.

**The question that decides most of the design: counted, or only displayed?**
These are different claims and they should not be settled together.
*Displayed* means the item appears among a board's items on that board's
pages — in its parts list, its document, its index block. *Counted* means the
item changes a board's numbers: its coverage stage, its totals, its release
gate. My answer, and the recommendation below is built on it: a shared
component should be **displayed and listed** on each board that uses it, and
should **not** be counted as that board's coverage obligation. A BOM is a
listing, not a score — `parts-<board>.html` is the page someone takes to
procurement, and a part both boards buy belongs on it — whereas coverage is
already handled by a mechanism designed for "one item, many boards":
`conforms_to:` (finding 24) declares the obligation on the board and
`compute_board_coverage` (build.py:701-760) scores each (item, board) pair
against that board's own satisfiers. Folding shared items into coverage
without that declaration would double-count one engineering fact across N
boards' totals, and would do it silently. The two claims pull in different
directions and the honest answer is that refdes has been treating them as one
question, because one `item.board` answers both.

**Option (a) — board-declared inclusion, mirroring finding 24.** The author
writes, on the board:

```yaml
boards:
  board-a:
    includes: [GRP-PWR-COMMON]
```

naming a `group` whose `contains` members are shown and listed on that board,
resolved by the same walk `compute_board_coverage` already does
(build.py:732-741, `group.backlinks["contains"]`). It should **not** reuse
`conforms_to:`. That key means "this board owes this, scored per board,
warned on until satisfied" — an obligation, with `validate_conforms_to`
(build.py:581-608) hard-erroing a target that is not an existing group and
`compute_board_coverage` emitting a
warning per (member, board) pair short of `satisfied`. Attaching shared
components to that key would make every shared part an obligation each board
is warned about until it is "satisfied", which is nonsense for a part number.
A separate `includes:` key, validated by the same shape check as
`_conforms_to` (schema.py:431-452, which exists because a bare string iterated
one letter per error) and the same exists-must-be-a-group check, keeps the
mechanism and drops the semantics.

What the board pages then show: the group's members appear in
`parts-<board>.html`, `document-<board>.html`, and any `{{index board:}}`
table, because the filter changes from `item.board == board` to `item.board ==
board or item.key in included_keys(board)` — one predicate, in `_in_scope`
(render.py:57-64) and its three non-render twins (`citations.by_path`:430,
`citations.by_part_number`:456, `nav.scope_reports`:77-81) — plus the
`{{index}}` block's own copy at blocks.py:167 — which is the whole
implementation surface for display. What the manifest records: nothing new, if
inclusion stays display-only — `.refdes/boards.yaml` records the item's own
resolved board (boards.py:247-270, one scalar or one `{id, board}` entry per
item), and an item in `shared/` keeps recording no board, which is true. That
is the strength of this option: the drift machinery, the `--accept-board-move`
warning (boards.py:409-484), the per-board seals (seal.py:42-47, 187-197), the
token lint (boards.py:115-133), and `items.json`'s single `board` field
(render.py:574) all stay exactly as they are, because none of them is asked to
hold a set. What could silently go wrong: an author adds the component to the
group and forgets `includes:` on the new board, and the part is missing from
that board's pages again — the same absence, now one indirection further away.
That is the failure mode worth designing against, and the answer is the same
one finding 24 chose: make the *declaration* loud (an `includes:` target that
is not a group is a build error) and, if it is wanted, warn when a board's items
link to an unboarded item that no `includes:` on that board covers — a lint on
the gap, not a membership change.

**Option (b) — multi-board membership on the item (`boards: [a, b]`).** What
the author writes is one line, where and when they know the answer, which is
the most direct thing any option offers. What breaks is everything downstream
of `Item.board: str` (model.py:430). The manifest shape: `.refdes/boards.yaml`
is one value per item (boards.py:247-270), and a move is detected by string
inequality (boards.py:409-484) — a list needs a set-difference, and "board-a →
board-b" and "[a] → [a, b]" are different events that the current warning text
cannot distinguish, so `--accept-board-move` needs a new meaning. Per-board
seals: `append_only_items(project, board)` (seal.py:187-197) partitions items
across seal files, and a multi-board log entry would have to be sealed in N
files or in a `""` file that `--reseal board-a` then cannot reach — either way
one entry's immutability is now governed by N accept flags. `--board` scoping:
`check --board` (cli.py:150-174) and `ls --board` (cli.py:471) become
overlapping filters, so `refdes ls --board a` plus `--board b` no longer
sums to the project. The token lint (boards.py:115-133) has no single token to
check a prefix against, and would either warn spuriously or go quiet. Coverage
grouping: `_board_gate` (build.py:611-623) is the guard that an unboarded
satisfier discharges nobody, and a multi-board satisfier now discharges every
board it lists — including one it was added to for BOM reasons, which is
exactly the silent-and-optimistic failure that guard was written to prevent.
And `items.json` exports `board` as one string (render.py:574), so imported
artifacts and every downstream consumer change shape. What could silently go
wrong is the coverage half specifically: adding a board to a shared component's
list to make it show up on a page would also let that component satisfy or
address that board's requirements, with no warning anywhere. This option is
the one that makes display and counting inseparable in the worst possible
direction.

**Option (c) — derive membership from links.** An item with no board of its
own is shown on every board whose items link to it. No new syntax, no new
manifest entry, no author to remember anything, and it is precisely the fact
the finding is about — the boards that use it are the boards that link to it.
`PartUsage.boards` (model.py:336-340) already does this for parts, derived
from the naming items' boards, and the shared case is the one it renders as
"—". But two things make it a bad *rule* even though it is a good *report*.
First, "shown on" then has to mean "counted in" or not, and there is no
principled answer: if a shared component appears on Board A's parts page
because Board A links to it, does it appear on Board A's coverage page,
in Board A's summary totals, in the release gate? Whatever is chosen, the
answer arrives from a link the author typed for a different reason. Second,
the incidental-link risk is real and one-directional: one `references:` to a
shared note from a Board A decision, written three months ago and now
half-true, puts that note on Board A's pages forever, and — worse — the
inverse, a board that legitimately uses a part but names it in prose rather
than in a link, still doesn't get it. `workspaces.lint_cross_workspace_references`
(workspaces.py:92-127) is the precedent for keeping derived edges out of
scoping decisions: it iterates `item.links` exclusively and its docstring says
so in as many words (workspaces.py:102-106), because a derived relationship is
not a declared dependency. Use it as a diagnostic — "this unboarded item is
linked from board-a and board-b; consider `includes:` on both" — never as the
mechanism.

**Option (d) — leave it, and link out.** Shared items stay project-wide; a
board page that wants them links to `parts.html#part-...` by hand, the way
`item.html.j2:110` already links "also used elsewhere". The honest cost: the
author has to know the gap exists in order to work around it, and the
workaround is a hand-maintained link in prose that no build check will notice
when it rots, on every board, for every shared item — the exact class of
thing refdes normally makes a mechanism for. It also leaves `nav.scope_reports`
(nav.py:88-90) free to write no `parts-<board>.html` at all for a board whose
only parts are shared, so the page the link-out lives on may not exist. What
it buys is zero new semantics and zero risk of a shared part being counted
where it shouldn't be — which is a real argument under this project's
"refuse rather than guess" posture, and the reason this is a decision rather
than an obvious fix.

**Recommendation: (a), display-only, with (c) demoted to a diagnostic.** A
board names the shared groups it includes; membership follows; the predicate
lives in the five filter sites named above; nothing about the manifest, the
seals, the drift warning, the token lint, or `items.json` changes, because
none of them is asked to hold more than one board. Coverage stays exactly
where finding 24 put it — declared on the board, scored per (item, board) —
and `includes:` carries no obligation and emits no coverage warning. The
question I am least sure about, and would want settled before implementation:
whether `includes:` targets only `group` items or also individual ids. Groups
keep it symmetrical with `conforms_to:` and give one place to maintain a
platform BOM; ids are what a two-board project with three shared parts
actually wants to write, and forcing a `GRP-` item to hold three components is
ceremony. My lean: groups only, because the asymmetry between two
board-declared list keys would be a worse tax than the ceremony, and a
three-part group is cheap. Second uncertainty: whether `summary_payload`'s
orphan and margin tables should include included-but-not-owned items — they
are computed from the same `local` list (render.py:363-367), so whatever
`_in_scope` decides flows there automatically, and "displayed but not counted"
may not be separable without a second predicate. That is the design question
this finding should be answered on. — Decided 2026-09-19: they are separable,
and the second predicate is the accepted cost of the decision, not a reason to
revisit it.

**Status: decided (2026-09-19).** Option (a), display-only, with (c) demoted to
a diagnostic — and the tally half settled harder than the recommendation left
it: a board's summary numbers count **only** the items the board owns. The item
counts, the orphan and margin tables on `summary-<board>.html`, and anything
else `summary_payload` tallies read the ownership predicate; items that reach
the board through `includes:` are displayed and listed there, labelled as shared
("shared, via GRP-X"), and never tallied. Jared: "Should only tally what it
owns, not what is shared." That is why one predicate cannot serve both jobs and
`_in_scope` (render.py:57-64) grows a sibling rather than a widened test.
Rejected: (b) multi-board membership on the item, for the `_board_gate`
conflation catalogued above — a board added for BOM reasons would also take on
that component's obligations; (c) link-derived membership as the mechanism, for
the incidental-link one — a three-month-old `references:` would confer
membership; (d) leave it and link out, because the workaround is a
hand-maintained link that rots with no build check, on a page `nav.scope_reports`
might not even write. `includes:` names **groups only**, not individual item
ids — the finding's own lean, taken as the default because Jared did not
object, and marked revisitable: if the ceremony of a `GRP-` item holding three
components turns out to cost more than the asymmetry with `conforms_to:`, that
is the knob to turn. Nothing here is implemented yet; `includes:` still appears
nowhere in the package.

**Local model (not decided — my read): not suitable.** The code change is
small and the display half is loud, but the correctness claim is "this item is
now visible on exactly the boards that use it and counted on none of them",
which is a claim about absences in five filter sites and every page and report
built from them — and the failure mode of getting it wrong is the project's
characteristic one: a board's parts page or summary quietly reporting a BOM
that is not the board's. The
`_board_gate` interaction in particular (build.py:611-623) turns a display
feature into a coverage hole if the two predicates are conflated, and no test
that a delegating prompt would think to write is likely to catch that
conflation in all five filter sites at once.

---

## In-use feedback, finding 34

### 34 — The generated site has one look, and almost nothing about that look is a token

**Source: Jared, while using refdes at work, not from an issue.** "I would
like the editor to have flavor and not be some basic gruel engineers are so
very familiar with." The ask is about the *editor*, but the editor does not
exist yet (`cli.py:1182-1520` registers build/check/revision/release/index/ls/
id/fetch/audit/init/new/schema/standard/keys/revise/stub-tests/former-ids —
there is no `serve`), and the look it would inherit does. This finding is
therefore about theming the site first, with the editor as the second
consumer (§5). Written for someone who does not write CSS: where a term is
load-bearing, it is explained in the sentence that uses it.

**What exists today, verified against the files.** `src/refdes/templates/
assets/style.css` is 441 lines and defines eleven custom properties on `:root`
(`style.css:1-13`) — `--bg`, `--fg`, `--muted`, `--line`, `--panel`,
`--accent`, `--good`, `--bad`, `--warn`, `--claim`, and `--mono` (which is a
font *stack*, not a colour). A `prefers-color-scheme: dark` block
(`style.css:15-28`) redefines the ten colour tokens, and `var()` is used 138
times across the rest of the file, so colours themselves are in decent shape:
only two colour literals survive outside `:root` — `color: #fff` on
`.type-badge` (`style.css:192`) and the `rgba(0,0,0,.18)` shadow on
`#preview-card` (`style.css:397`) — and the fourteen `color-mix()` uses derive
their tints *from* the tokens, so they follow a theme automatically. The
stylesheet is linked once, `base.html.j2:6`, and copied to `_site/assets/` by
`render.py:880-882` (empty-project path) and `render.py:1112-1114`.

**The gap, and it is most of the work: everything that is not a colour.**
Counted in the same file: 66 `font-size` declarations, 65 of them literal px
from 11px to 30px; 20 `font-weight` declarations (400/500/600/650); 24
`border-radius` declarations (3px, 4px, 5px, 6px, 7px, 8px, 999px, 50%); 36
`padding` declarations and 82 `margin` mentions, with no shared rhythm —
`10px 14px`, `14px 16px`, `4px 16px 14px`, `6px 10px 6px 0` are each written
out where they recur; 14 `letter-spacing` and 14 `gap` declarations; 325 `px`
literals in total. Type is the worst of it: the body face is not a token at
all — it is inline in the `font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif`
shorthand at `style.css:36`, with a second hardcoded `system-ui, sans-serif`
at `style.css:183` — so there is no token anywhere that changes what the site
*is* typographically, only what it is coloured. The surfaces that carry the
most personality (`.pill` and `.type-badge`, the `.panel`/`.notice`/`.option`
boxes, `.timeline` and the thread styles at `style.css:337-372`, the table
rules on `.grid`/`.fields`/`.calc`) are all built from those literals. A theme
cannot reach any of them today. That is the refactor this finding is actually
about, and it should be said plainly rather than discovered halfway through.

**1. Scope — three sizes, and why the middle one.**

- **(a) Colours only**, by swapping the existing ten. Cheapest by an order of
  magnitude — the token layer already exists, so a theme is a file of ten
  `--name: value` pairs and the implementation is "load it, emit it after
  `:root`". But it is not what was asked for. Ten colours on a layout whose
  type, spacing and radii are fixed gives a *different-coloured* site, not a
  site with flavour; the gruel is the 11px uppercase letter-spaced label and
  the 8px radius, not the blue.
- **(b) Colours + typography + density**, which requires refactoring
  `style.css` into a real token layer first: add `--sans`, `--serif`,
  `--text-xs..--text-3xl` (or a base size plus a ratio), `--weight-*`,
  `--space-1..--space-6`, `--radius-*`, and replace the literals with `var()`
  throughout. Cost, honestly: it touches all 441 lines, it is the kind of
  change that can silently alter line-height and table density on pages no
  test asserts about, and it has to be reviewed visually, which is the
  slowest kind of review here. It is also a one-time cost paid once for every
  theme after it.
- **(c) Whole-look themes that also change layout** (sidebar vs top nav,
  cards vs flat lists, two-column documents). Rejected: refdes would then own
  N divergent stylesheets *and* the templates that satisfy all of them, which
  is how static generators grow a second product surface nobody can maintain.
  Layout is also where a theme stops being a short file and becomes a fork.

**Recommendation: (b)**, with (a) as the first milestone inside it — land the
token layer and one built-in theme that is visually identical to today, so the
refactor is provably a no-op, then add themes on top.

**2. Who can define one.**

- **Built-in named themes**, selected in project settings as `site: theme:
  <name>`. `site:` is parsed today by plain `.get()` calls at
  `schema.py:713-719` (`title`, `out`, `version`, `pages`, `nav`, `assets`)
  with **no validation of unknown subkeys** — unlike top-level settings, which
  hard-error on an unknown key with a difflib "Did you mean" hint
  (`schema.py:116-121`). So `site: theme: slate` must be added as an explicit
  check: an unknown theme name is a build error naming the available themes,
  never a silent fall back to the default. That asymmetry is the whole
  difference between a typo doing nothing and a typo doing the wrong thing.
- **Token overrides in project settings** — `site: tokens: {--accent: #..., --sans: ...}`.
  Zero new files for the author, and it composes with a named theme (theme
  first, overrides second). Trade-off: YAML is not CSS, so a value with a
  comma in it (a font stack) needs quoting rules people will trip over.
- **A project-local CSS file** loaded after the theme, e.g. `site: css:
  theme.css`, copied into `_site/assets/` and linked after `assets/style.css`.
  Note the existing guard it must not collide with: `_copy_project_assets`
  refuses any project asset whose top-level name is a template-owned file
  (`render.py:677-686`, `reserved = set(os.listdir(ASSET_DIR))`), so a project
  file named `style.css` is already a hard build error — a theme file needs its
  own name and its own `<link>`, not a second copy of the reserved one.
- **Rejected: a remote URL.** The site is plain static files that must work
  offline, on a plane, on a factory floor network, and must not change under
  an author between two builds of the same commit. A URL also makes a sealed
  baseline's rendering depend on someone else's server.

What each means for someone who does not write CSS: **a theme is a short file
of `--name: value` lines and nothing else** — no selectors, no braces, no
nesting, nothing to get structurally wrong. `--accent: #b3541e` is the entire
syntax. That is the property worth protecting, and it is what §3 turns on.

**3. Sharing.** Three routes, in increasing order of reach: **bundled with
refdes** (built-ins, the only kind that ships with an upgrade and gets the
contrast checking below); **a file committed in the project** (`theme.css`
beside the items, which is how it travels with the repo to a colleague, and
how it is reviewable in a diff); and **a gallery page on the docs site** —
`docs-site/refdes-project.yaml` is itself a pages-only refdes project
rendering `../docs` with the same stylesheet, so a gallery is a page there,
showing each built-in theme with the exact `site:` snippet and token file to
copy. Say it explicitly in the docs, because it is the reason sharing is safe
at all: **a token-only theme cannot break page structure** — it can only make
a colour, a face, a size, or a padding different, and the worst outcome is
ugly or hard to read. A project CSS file *can* break structure, hide a
section, or delete the nav, and should be documented as "past this line you
are on your own": supported for your own project, not a sharing format, and
not something a built-in theme will ever depend on.

**4. Invariants every theme must keep.**

- **Dark mode still works.** Decide now, because it changes the file format:
  either a theme supplies *both* palettes (two token blocks, and the dark
  block stops being refdes's property), or refdes keeps the
  `prefers-color-scheme` mechanism (`style.css:15-28`) and a theme declares
  light tokens plus dark tokens under two documented headings. My
  recommendation is the latter — keep the media query and the `color-scheme`
  declaration refdes's, keep the theme as two flat lists of pairs — because
  the alternative lets a theme ship that is unreadable at 2am, which is the
  common case for the log page on a phone. The newer `light-dark()` function
  (Baseline, all three engines, May 2024) is tempting for collapsing the two
  blocks into one line per token, but it is a second mechanism to explain to
  theme authors; not worth it in v1.
- **The print stylesheet still works.** `@media print` at `style.css:322`
  hides the nav and footer, un-flexes the layout, and sets `a { color:
  inherit }`. Any token a print rule depends on (`--bg`, `--fg`, `--line`,
  `--accent` for `.part-title`'s underline) must stay defined; a theme that
  redefines `--line` as transparent prints a document with no rules, which no
  build error would catch.
- **Contrast stays legible.** WCAG AA is 4.5:1 for normal text and 3:1 for
  large text (W3C, Understanding SC 1.4.3). refdes *could* check ratios at
  build: the tokens are hex literals in a file it already parses, and the
  ratio is ~15 lines of relative-luminance arithmetic with no new dependency.
  Cost: it can only check token-against-token (`--fg` on `--bg`, `--muted` on
  `--panel`, `--good`/`--bad`/`--warn` on both surfaces), not real rendered
  contrast through `color-mix()` tints — so it catches the gross cases, which
  is most of them. Recommendation: **check the built-ins at build (hard
  error) and project themes as a warning**, because refusing to build a
  project because its author likes a pale accent is the kind of friction that
  makes people delete the feature; and a warning naming the failing pair and
  the ratio is actionable.
- **The status colours keep their meaning.** `--good`, `--bad`, `--warn`,
  `--claim` are not decorative hues; they are read as pass/fail/at-risk/claimed
  on coverage strips, pills, stage bars and margin bars (`style.css:248-262`,
  `style.css:419-441`). A theme must not reassign them to arbitrary hues — a
  `--bad` that is not visibly alarming (pale beige, or a hue a colour-blind
  reader cannot separate from `--good`) is a **correctness problem, not a
taste one**, because the whole point of the strip is a verdict readable at a
  glance. Enforce it the way the other invariants are: a documented rule, plus
  a build-time check that `--bad` and `--good` are distinguishable from each
  other and alarming enough by whatever mechanical test is chosen (a minimum
  saturation/luminance band, or a required separate non-colour cue).

**5. The editor must not grow its own look.** `docs/design/browser-editor.md`
recommends shape B, a separate `/edit/` app served by `refdes serve`, and
already names the mitigation at `browser-editor.md:162` — "reuse design
tokens/CSS where sensible". Theming makes that concrete and cheap: the editor
links the **same `assets/style.css`** and the same theme file, so a project's
theme applies to both surfaces for free. If the editor needs editor-specific
rules, they belong in a second stylesheet that *imports the token layer only*
(`tokens.css`, the file §1(b) proposes) and never redefines it — one source of
truth per token, in whichever file the other imports. The failure to avoid is
an editor with its own hardcoded palette, which is the "basic gruel" the ask
is about, doubled and permanently out of sync.

**6. What could silently go wrong, and how refdes notices.**

- **A theme makes a diagnostic invisible** — `--bad` close to `--bg`, or a
  `.ref-missing` marker the same colour as the prose. Caught by the contrast
  check above, applied to the semantic pairs specifically.
- **A token typo falls back to browser defaults.** CSS does not warn: a
  declaration using an undefined or mistyped custom property becomes "invalid
  at computed-value time", which the browser treats as unset — the inherited
  or initial value, *not* the earlier cascade value, and a `var(--x,
  fallback)` only helps when `--x` is entirely unset. So `--accent: #f00`
  silently leaves the real `--accent` at its default and the site renders
  half-themed. Refdes notices by validating the theme's key set against the
  built-in token list at build: **unknown token name = error with a "did you
  mean" hint**, the same treatment `schema.py:116-121` already gives unknown
  settings.
- **A missing token in a hand-written theme** — same mechanism, opposite
  direction, and the reason a project theme should be *merged over* the
  default rather than replacing it, so an omitted token is the default value
  rather than unset. Validate the merged set is complete before rendering.
- **A theme file that is not copied into the output** — the site renders with
  the default theme and the author sees the right thing locally because their
  browser cached it. The build already tracks every file it wrote in
  `.refdes-manifest.json` (`render.py:641-735`) and prunes to it, so the check
  is one line: a declared `site: css:`/theme path must appear in `written`, or
  it is an error.
- **An upgrade adds a token an old theme does not define** — the new surface
  renders unstyled in every existing project. Mitigation: new tokens are added
  with a default in `style.css` (never only in a theme), so an old theme is
  incomplete-but-correct; and the completeness validation above runs against
  the *current* token list, so it reports "this theme predates `--space-7`, it
  now falls back to the default" as a warning rather than a mystery.

**Recommendation and v1 scope.** Do the token-layer refactor first, ship it as
a visually identical no-op, then ship theming on top of it. v1 should include:
the token layer (`--sans`, `--serif`, `--text-*`, `--weight-*`, `--space-*`,
`--radius-*` replacing the literals counted above); `site: theme: <name>`
with three or four built-ins, one of which is today's look; `site: tokens:`
overrides merged over the named theme; token-name and completeness validation
with "did you mean" hints; contrast checking (error for built-ins, warning for
project themes); the docs-site gallery; and the same stylesheet linked by the
future editor. v1 should refuse: layout-changing themes; remote theme URLs;
any project CSS file that a built-in theme depends on; reassignment of
`--good`/`--bad`/`--warn`/`--claim` outside their semantic bands; and a theme
format with selectors, nesting, or anything else that makes a theme a program
rather than a list of pairs.

**Status: outstanding — awaiting decision.**

---

## In-use feedback, finding 35

### 35 — A shared figure gets retyped into every calc block, and diverges silently when it changes

**Source: Jared, using refdes at work, 2026-09-16, not from an issue.** One
number — `V_in = 12 V +/- 5%` — belongs to the power stage and is used by
everything downstream of it. Today it is retyped into each item that needs it,
and when the input rail changes, the copies do not. He wants to name another
item's calc value explicitly, and liked the consequence: such a reference is a
*real dependency*, visible to the build, not a convenience alias. The typed
copies are not hypothetical — `items/decisions/dec-pwr-001-regulator-topology.md:43`
is the `V_in = 12 V ± 5%` line, and it is the same figure the finding is about.

**What exists today, verified.** Within one item, names already flow: `run_calcs`
threads a single `env` through every block of an item (build.py:887-921, with
`item._env` retained for `checks:` at build.py:921), and docs/math.md:30-31 says
both halves of the rule in prose — visible across blocks, **not** shared between
items. Re-declaring a name inside one item is an error: `evaluate_block` keeps an
`origins` map threaded by the same caller (build.py:890-893) and raises
"`'V_in' is assigned twice in this item` … `A name can only be assigned once per
item (blocks share one item-wide scope)`" (calc.py:914-927). Nothing crosses the
item boundary: `run_calcs` and `compute_hashes` both iterate `project.local_items`
(build.py:888, 1237), and an expression can only read names present in `env`
(calc.py:424-426). So the boundary this finding wants to open is exactly the one
math.md documents, and the one rule that must survive it is the duplicate-name
rule.

**What must not be reinvented.** Project equations — finding 27, shipped in
`c96d96b` — are `calc.Equation`/`set_equations`/`validate_equations`
(calc.py:208-293): a project-wide namespace of *formulas*. Finding 26's
`source("file.csv", "key")` (docs/design/calc-sources.md) is a lockfile-pinned
*input*. `{{name}}` (build.py:53, substituted in `render_bodies` at
build.py:1741-1760) is item-local *prose* interpolation of a formatted result.
And the stale-arithmetic signal (docs/design/stale-arithmetic-signal.md,
`build.calc_hash_for` at build.py:1092-1115, `lifecycle._stale_arithmetic` at
lifecycle.py:760) exists precisely to notice "the status changed but the
arithmetic did not" — and its own docstring says out loud that it cannot see an
upstream value moving: "A result changing because an upstream value moved, with
this item's own block untouched, is a different question this function doesn't
answer" (build.py:1107-1109). That sentence is this finding's gap, stated by the
feature that declines to close it.

**1. Syntax.** Three candidates. (a) A dotted reference inside the block —
`V_in = DEC-PWR-001.V_in`. (b) An import line above the block —
`use DEC-PWR-001.V_in as V_in` — with the block then reading `V_in`. (c)
`{{DEC-PWR-001.V_in}}` in the expression, reusing the prose interpolation.

(c) is out on ordering alone: `{{name}}` substitution happens in
`render_bodies` (build.py:1741), which `build()` calls at 1891, *after*
`run_calcs` at 1881 — the interpolation runs on text, after arithmetic, and
cannot feed it. It is also a formatted string, not a `Value`
(`item.calc_values` is `name -> formatted result`, model.py:412), so it carries
no unit and no tolerance. Keeping `{{…}}` meaning "prose, this item only" is
worth more than one fewer syntax.

(b) is workable but buys a second scoping rule for no benefit: an import line is
block-level syntax in a language whose only scope is the item, it has to decide
what happens when the alias collides with a local name (which is today's
duplicate error, so the answer is "error" either way), and it separates the
reference from the line that uses it. (a) reads as what it is and needs no new
statement form.

**Recommendation: (a), `V_in = DEC-PWR-001.V_in`, stored expanded as a
composite.** The syntax space is free — verified, not assumed: today
`DEC-PWR-001.V_in` fails as `unknown name 'DEC'` (the lexer reads `-` as
subtraction and evaluation hits `DEC` first) and `DEC_PWR_001.V_in` fails as
`Attribute is not allowed in an expression` (calc.py:471, and the module
docstring's "no attribute access", calc.py:3-5). So nothing silently evaluates,
but the diagnostic is a lie about the author's intent — which is an argument for
making it real syntax with a real message, not for leaving it.

Rename survival is the whole reason to care. This project stores structured
references as `DISPLAY-ID@key` composites resolved on the key half only
(docs/design/keys.md §3, `build.resolve_link_target` at build.py:395-422), so a
reference is written by the author bare and frozen to
`V_in = DEC-PWR-001@k7f3m2q9x4a.V_in`, refreshed on rename by the same rule.
It is **not** a `links:` reference, though, and must not pretend to be: the
precedent for a structured reference that lives outside `links:` is `checks:
against:`, which got its own `plan_check_expansion`/`expand_missing_checks`
(links.py:701, 802) sharing `_planned_target` (links.py:308) with the link path
so the §3 refresh rule cannot drift between them. A calc reference needs the
third instance of that same shape — one more `plan_*`/`expand_*` pair over calc
block lines, sharing `_planned_target` and the Layer 1/3 diagnostics. That is
also where `--no-write` comes from: every one of these write-backs is called as
`write=not args.no_write` (cli.py:95-125), and a bare reference under
`--no-write` still resolves, on the display id, exactly as keys.md §2's rule
requires.

**2. What is referenceable.** Option (a), any named value in the target's
blocks, is one keystroke of friction per reference and makes every local name in
every item public API — `A_board`, `eff_2`, the throwaway `tmp` in a scratch
block all become things a rename can break, which is the opposite of what
`origins` is for (calc.py:914-927 tells you to *rename* a colliding local; it
cannot tell you that the rename broke three other items). Option (b), an
explicit `exports:` list on the target, costs one line per publishing item and
buys the only rule that makes renames reportable: renaming an exported name is a
breaking change the tool can name, renaming a local is free.

**Recommendation: (b)** — `exports: [V_in]` on the target, validated the way
`equations:` is validated (each name must be one the item's calc blocks actually
assign; an `exports:` entry naming nothing is an error, not a no-op).
Referencing an unexported name is an error that names the fix, in the same voice
as the duplicate-name error. The friction is the point: publishing is the moment
the author says "this number is a contract."

**Decided otherwise (2026-09-19): any named value in the target item is
referenceable, and there is no `exports:`/`publishes:` list.** Jared's reasoning
is that naming the item in the reference *is* the explicit step this paragraph
wanted — `V_in = DEC-PWR-001.V_in` says out loud, at the site that needs it, that
someone else's number is being relied on — and an `exports:` list adds a second
vocabulary (names a block assigns, names the item publishes) that its author has
to keep in sync for a guarantee the reference already carries. The cost is
stated rather than buried, as this paragraph asked for it to be: the target's
author cannot see who depends on a variable, so renaming one breaks dependents.
Accepted, because it breaks **loudly** — every dependent fails at its own
reference line with the file:line, the item id and the reference — which is the
same bar `origins` and the duplicate-name error are held to. Everywhere else in
this finding, "exported names" reads as "the names that item's calc blocks
assign".

Imported projects: the data is exported (`render.items_json` emits per-item
calcs, render.py:588-597) but not absorbed — `imports._absorb`
(imports.py:61-122) reconstructs fields, links, identity and the upstream
content hash, and no calcs, and `run_calcs` never iterates external items.
**v1 refuses it**, with a message saying so. It is the right refusal rather than
a limitation: a cross-project calc reference is only honest against the pinned
artifact version (imports.py:46-54 already makes a version mismatch an error),
and getting there means deciding whether a downstream project's arithmetic is
reproducible from its own lockfile-and-pins — a question this finding should not
settle by accident.

**3. Evaluation order and cycles.** Calcs are per-item today; a cross-item
reference makes it a graph over items. Order falls out of the reference edges:
resolve edges first, evaluate in dependency order (DFS post-order, memoised —
an item's `env` is computed once and cached, since `env` is already the whole
state), which is a strictly smaller change than it sounds because pass structure
stays: `run_calcs` still owns one item's blocks, and gains a scheduler around
it. A cycle is an error naming the cycle, following both existing precedents —
`blocked_by cycle: a -> b -> a` (blocked.py:99, which reports and `return`s,
stopping the pass rather than half-annotating) and `equation cycle: a -> b -> a`
(calc.py:264, with `_equation_stack` as the runtime backstop, calc.py:270-288).
Reuse the `->` shape so the three cycle diagnostics read alike.

A reference to an item whose own calc failed must **not** restate that failure.
One root error at the item that broke, plus a downstream line per dependent
worded as "cannot resolve `DEC-PWR-001.V_in`: its item's calc failed" — the
same one-root-many-notes discipline `blocked.py` uses when several claimers
trace to one unsettled root (build.py:846-880). Otherwise a single bad line in a
shared item produces N identical errors and the author starts counting errors
instead of reading them.

**4. Staleness — the correctness core.** Three options. (a) Recompute silently:
the value is always current, and "stale" becomes meaningless — worse, a seal or
baseline recorded earlier describes arithmetic whose inputs no longer exist, and
nothing says so. (b) Put the resolved upstream value into the referring item's
content hash. (c) Leave the value current but mark dependents suspect.

**Recommendation: (b), with (c) as the presentation layer of (b), and (a) alone
rejected.** The argument is comparison, not assertion: finding 26 already decided
this for the source-backed case, and decided it the same way — a value that is an
arithmetic input is content, so the resolved `(path, key, locked text)` goes into
the content hash and "seals/baselines/suspect-link consumers notice a reviewed
source-value change as content" (docs/design/calc-sources.md §8). A referenced
calc value is the same kind of thing one level up. (c) alone is not available
anyway: suspect links do not exist — docs/lifecycle.md:261-264 describes them as
the thing a future mechanism would supply — and a correctness guarantee cannot be
built on machinery that has not been built.

What the author sees, and this is the payoff: DEC-A's `V_in` moves, DEC-B's calc
block is untouched, and DEC-B shows up in the baseline diff as `changed` with
nothing in its own text to point at. That is precisely the shape
stale-arithmetic was invented to catch and explicitly cannot (build.py:1107-1109),
so the diff line has to say what moved: `changed DEC-B — referenced
DEC-PWR-001.V_in: 12 V ± 5% -> 11.4 V ± 5%`. The item template already renders a
`stale` pill for a dependency that moved out from under an item
(item.html.j2:214, the blocked-chain case), so the affordance exists.

The honest costs, stated rather than buried. It is a hash-definition change:
`HASH_FORMAT` is 3 (build.py:1044), and this bumps it — but so does finding 26,
and the two must coordinate on one number and one historical payload builder,
exactly as formats 2 and 3 were carried forward conditionally (keys.md §5).
It puts a value that lives in another file inside this item's identity, so a
rename of the upstream *display id* must not churn — hash the resolved key and
the resolved value, never the composite text, the same rule as
`_link_hash_token` (build.py:1118-1140). And it means an author can see their own
item marked changed for something they did not do, which is the correct report
and the one most likely to be complained about; the diff line naming the upstream
value is what makes it readable instead of mysterious.

**5. Units and tolerance.** Confirmed, and this is the strongest argument for the
feature over copy-paste. A `Value` is `(nom, lo, hi)` over pint quantities
carrying its unit (calc.py:33-51), and `_binary` propagates the interval by
corners (calc.py:74-96), so a reference to `12 V ± 5%` arrives with its width
intact. A retyped `12 V` loses the ±5% silently and reports a suspiciously tight
answer — the copies are not merely a maintenance problem, they are a correctness
problem the moment someone drops the tolerance while retyping. A dimensionality
mismatch at the reference site is an ordinary calc error at the line that has the
wrong dimensions: the unit assertion `P = DEC-X.V_in * I | W` fails in the
existing `convert_value` conversion (calc.py:831-843), and a bare mismatch inside
a larger expression fails in `_binary`'s pint operation. No new diagnostic class
is needed; the line reported is the line the author has to fix.

**6. Composition with findings 26 and 27.** The rule that keeps three mechanisms
from becoming three systems: **they differ in where the number comes from, not in
what it becomes.** All three bind a name in one `env` to one `Value`, and all
three contribute their resolved scalar to the content hash. Consequences, each
falling out rather than needing its own code: a referenced value may itself be
source-backed — the referring item sees a `Value` and performs no I/O, so
calc-sources.md's hermeticity rule (never parse a spreadsheet during check or
build) survives one hop and, since the upstream value is in the upstream item's
hash and the upstream hash is in the artifact, two hops. An equation takes a
referenced value as an argument for free, because arguments are evaluated
`_eval_node(a, env)` over the same env (calc.py:284) — `thermal_rise(
ref("DEC-X", "P_diss"), 40)` needs no change to `_call_equation`. And the
duplicate-name rule is untouched: a reference binds a name *exactly as an
assignment does*, so `origins` fires if an item both references `V_in` and
assigns it — one name, one meaning per item, which is the rule the finding was
told must survive and does.

**7. Failure modes.** Target id does not exist → error at the reference line,
"no item `DEC-PWR-001`", the same shape as `check against X, which does not
exist` (build.py:988). Target exists but has no such variable → error naming the
name and the target's exported names. Target's *exported* variable renamed → the
reference names nothing and errors; and here the honest disclosure: **keys do not
save this half.** A surrogate key protects the item half of the reference across
a rename; a calc variable has no surrogate, and `resolve_link_target`
deliberately has no `former_ids:` fallback (build.py:408-411). `exports:` does not
fix that either — it makes the breakage *reportable at the reference site* rather
than silent, which is the most any of this can promise. Target deleted → the
unknown-key diagnostic (`build._unknown_key_message`), display half not consulted
as a fallback (keys.md §3 case 3). Reference into an item on another board, or an
unboarded shared item → allowed and useful; boards never scope links (finding 33
verified zero board references in links.py), and finding 33's shared component is
exactly the item two boards want to read one number from. The gap to disclose:
a calc reference is not a `links:` edge, so it is invisible to
`lint_cross_workspace_references` (workspaces.py:92-124, which iterates
`item.links` exclusively), to backlinks, and to coverage. Making it a link edge
would drag it into coverage semantics, and finding 33's `_board_gate` lesson
(build.py:611-623) is that a display feature turned into a coverage edge is how a
display feature becomes a coverage hole — so v1 discloses the blind spot instead.
A log entry referencing a sealed entry's value → the sealed value cannot move, so
the reference is stable; if the seal is violated, both the violation and the
dependent's changed hash report, and the diff line naming the upstream value is
what keeps that from looking like two unrelated problems. `--no-write` → the
expansion write-back is skipped and the bare reference still resolves on the
display id; nothing under `items/` or `.refdes/` changes, same as the existing
no-write contract on the other expansions (cli.py:95-125). `refdes check` → an
unresolved reference is an error, and check writes nothing.

**v1 scope.** Include: the dotted reference form with a real diagnostic
replacing `unknown name 'DEC'`; composite expansion, refresh and Layer 1/3
diagnostics through a `plan_*`/`expand_*` pair sharing `_planned_target`;
`exports:` on the target with validation that every exported name is assigned;
dependency-ordered evaluation with one cached `env` per item; cycle errors in the
`a -> b -> a` shape; one root error plus downstream notes; the resolved
`(key, name, value text)` in the content hash under a coordinated
`HASH_FORMAT` bump with a historical builder; the diff line naming the upstream
value and its old value; unit and tolerance flow-through with no new diagnostic
class. Refuse: references into imported items (with a message saying why);
references to unexported names; `exports: "*"` or wildcard publishing;
`{{ID.name}}` prose interpolation of another item's value — the author writes
`V_in = DEC-PWR-001.V_in` and then `{{V_in}}`, which keeps prose and arithmetic
pointing at one name; calc references as `links:` edges, into backlinks,
coverage, or the workspace lint; referencing anything but a single named value
(no block import, no "import everything"); and any change to `source()` or to
equations beyond what one shared `env` gives for free.

**Status: decided (2026-09-19).** Syntax is (a), `V_in = DEC-PWR-001.V_in`,
stored as a `DISPLAY-ID@key` composite like every other structured reference
(§1) — written bare, frozen on the key half, refreshed on rename by the same
rule. Any named value in the target is referenceable; there is no `exports:`
list (§2, decided against that section's own recommendation, with the
invisible-dependents cost accepted because a rename breaks loudly at every
referring site). A reference to a missing item, a missing name, or a renamed
name is a **loud error at the referring site** — file:line, the item id, the
reference — never a silent default and never a stale value. The resolved
upstream value **enters the referring item's content hash** (§4's recommendation,
consistent with finding 26), so an upstream change shows the dependent as
`changed` in baselines with the diff line naming which reference moved and what
it moved from and to; the `HASH_FORMAT` number stays coordinated with finding
26's bump, one number and one historical builder, exactly as §4 says. Rejected:
(b) `use … as …` import lines and (c) `{{ID.name}}` in expressions (§1), for the
ordering and second-scope reasons given there; published-exports (§2); and
recompute-silently or mark-suspect-only (§4), the latter because suspect links
do not exist yet and a correctness guarantee cannot be built on machinery that
has not been built.

**Local model (not decided — my read): not suitable.** The parser change and the
scheduler are small, but the correctness claim is "every item whose arithmetic
depended on a value that moved is reported, and no item that did not is" — a
claim about a graph, about hash carry-forward across a format bump, and about the
interaction of three value-into-`env` mechanisms. The failure mode is the
characteristic one twice over: a reference that silently resolves to the wrong
item half (a composite refreshed wrongly), or a hash change that churns on a
rename it was supposed to be immune to. Both pass a build with no failing test
anywhere, and both are in machinery — keys, hashing, seals — that this project
has consistently kept off a small model's plate.

---

## Surrogate keys — remaining layers

`docs/design/keys.md` §1 (key format), §2 (minting), §3 (composite
expansion, display-half refresh, and key-based resolution), §5 (key-based
hashing, hash-format migration, dual-shape readers, conditional storage
conversion, relabelled diffs, and key-stable seal verification), §6 Layers
1-5 (well-formedness, uniqueness, unknown-key resolution, the
latest-baseline lint, and the informational audit of older baselines), and
§7 (`refdes keys adopt`) are implemented — see that document's own
implementation-status header for the module list. Adoption is explicit and
transactional; the self-describing `.refdes/keys-adopted.yaml` marker records
it, and new stamps/seals then use key-keyed storage.

**Status: implemented** (the §4 cleanup landed after this section was
written; see keys.md's implementation-status header for the shape):

- ~~**The subtractive cleanup in `revise.py`/`former_ids.py` (§4)**~~ —
  `revise.py`'s prefix-rename reference machinery (`_rewrite_reference_ids`,
  `_rewrite_block_sequence`, `_rewrite_id_tokens`, `_relabel_id`,
  `_relabel_ledger`, `_restore_ledger`) is gone, along with the ledger's
  burned-prefix collision check and the baseline/seal record-id remapping;
  `_rename_prefix` survives as the private id/prefix-line helper, and
  `Mapping.prefixes` stays (prefix renames still move display ids). A prefix
  rename now runs the writable-load key pipeline (mint, link/check
  expansion, follows freeze) inside its own transaction and refuses with
  file:line if a structured reference to an affected id is still bare
  afterwards; dry runs simulate the pipeline on a throwaway copy and report
  what the real run would expand. `former_ids.propose` answers the internal
  "which new item replaced this old id" question by key lookup (exact,
  confidence 1.0) for baselines that carry keys; similarity scoring remains
  only for legacy keyless baselines.

**Both disclosed gaps are closed:**

- **`checks: [{value, against}]` still resolves `against:` as a bare display
  id.** ~~It isn't a `links:` reference at all...~~ **Closed.** `against:`
  now accepts the same `DISPLAY-ID@key` composite a link target does --
  resolved through `build.resolve_link_target`, expanded/refreshed through
  `links.plan_check_expansion`/`expand_missing_checks`, both reusing the §3
  refresh rule and the Layer 1/3 diagnostics rather than reimplementing
  either. Hashing needed `hash_format: 3` (docs/design/keys.md §5,
  2026-09-14): `checks:` was never a `link:*` payload key, so reducing
  `against:` to its resolved key for hashing is a hash-definition change of
  its own, carried forward conditionally the same way format 2 was.
- **Imported cross-project links carry no key.** **Closed 2026-09-15.**
  `render.items_json` now exports nullable item keys; `imports._absorb`
  preserves pre-key artifacts as provisional entries but adds keyed imports
  under their surrogate keys. `cli._load` therefore expands and refreshes
  local composites against imported targets before `build.resolve_link_target`
  resolves them. Layer 1 attributes malformed artifact keys to their
  `imports:` entry, and Layer 2 treats the local project plus all artifacts
  as one key namespace without changing the established display-id collision
  rule.

**Local model: not assessed for any of the above.** The remaining work
touches identity/correctness machinery directly: adoption rewrites every
item file and baseline in one transaction, refresh and cleanup alter rename
semantics, and the two disclosed gaps are already-known correctness holes.
None of this was discussed against the suitability rule in conversation,
and I'd rather leave it unmarked than guess at a rule this consequential.

---

## An idea from Jared, finding 36

### 36 — Resolve `<img>` references by filename against a declared search path, not by relative path

**Source: Jared, a direct request — not from an issue, not from code review,
not from using the tool at work.** Today's pain: `<img src>` resolves
relative to the *source file's own directory* (`build.py:1557,1572-1574`), so
moving a document to a different folder breaks every image it embeds, and a
photo shared by items in several folders needs a `../../` path written out by
hand at every use site. His framing: make this work the way `#include
<foo.h>` does in C++ — write the filename, let the tool find it.

**1. The analogy is worth taking literally, not loosely — and it argues
against the obvious implementation.** `#include <foo.h>` does **not** search
the whole project tree; it searches a small, explicitly declared list of
include directories (`-I` paths, or a toolchain default list) and nothing
else. An implementation that instead walked every directory under the
project root looking for a file named `diagram.png` would not be the C++
analogy — it would be the thing C++ deliberately avoids, and for the same
reason this project avoids it everywhere else: an unbounded search over
mutable ambient state (the whole tree, as it happens to be arranged today) is
exactly the "permanent meaning derived from mutable ambient context" pattern
already corrected twice here (board-from-path, and the group/file-link
question finding 14 rejected for the same reason). The closer analogy, and
the recommendation, is a **declared list of asset search directories in
project settings** — the same shape `site.assets:` already is
(`schema.py:719`, `model.py:660`: `asset_dirs: list[str]`, currently used
only to bulk-copy whole directories into `_site/assets/`, `build.py:1933-1942`).
Whether search reuses `site.assets:` itself as the list, or a new
sibling key, is an open question (see §2); either way, the list is short,
explicit, and lives in the file an author already edits to add a photo
directory — never a directory the tool discovers on its own.

**2. Open question: one list or two.** `site.assets:` today means "copy this
whole directory into the output, verbatim, for hand-typed hrefs to point at"
(`build.py`'s `collect_static_assets`, identity-mapped, never hashed,
deliberately — `docs/design/index-blocks.md` §10 explains why an
author-typed `href` cannot be silently rewritten). Reusing it as the search
list too is the smaller surface (one key, one mental model: "directories this
project keeps its assets in"), but conflates two different guarantees — bulk
copy is unconditional and untyped, name-search resolution needs to be
unambiguous project-wide (§3). A separate key (`site: asset_search: [...]`,
naming only) avoids that conflation at the cost of a second list to keep in
sync when a directory serves both purposes, which in practice is most of
them. Recommendation: reuse `site.assets:` — most projects that want this
feature already declare the directories it would search, and a second list
that usually mirrors the first is the kind of duplication this project
otherwise refuses to introduce (see finding 21's argument against
`requirement`/`bound` field duplication for the general version of this
concern). Worth deciding explicitly rather than assuming, since it changes
what a `site.assets:` entry *means*, not just what consumes it.

**3. Ambiguity is a hard error, always — this is the load-bearing rule.**
If two files anywhere on the search path share a leaf name — `diagram.png` in
both `figures/power/` and `figures/thermal/` — resolution must refuse with an
error naming **every** candidate and its full path, never a silent
first-match. Decided 2026-09-19, and the trigger is pinned: the refusal happens
**at the reference site**, when an `<img>` names the ambiguous leaf — two
same-named files that no image points at are not an error, so nothing walks the
search path hunting duplicate leaf names. The collision is a property of the
reference, not of the directory. This project's characteristic bug is code that reports success
while doing the wrong thing, and "quietly resolved to a different
`diagram.png` than the one meant" is precisely that shape: the build
succeeds, the site renders, and the wrong photo sits under a caption that
describes the right one, discoverable only by a human noticing later. There
is no safe implicit tie-breaker here (first-declared directory, most-recently
modified, alphabetical) — every one of them is a rule nobody reading the
document can see, which is the same objection keys.md raises against a
display-id fallback when a key fails to resolve (keys.md §3, case 3: "the
display half is deliberately not used as a fallback ... falling back would
resurrect exactly the ambiguity keys exist to remove"). The fix a human takes
in response is also mechanical and worth stating in the error itself:
disambiguate by writing a longer relative path instead of a bare filename, or
rename one of the files.

**4. Recommend resolve-and-freeze, for the same reason it was chosen twice
already.** This project has already made this exact call twice: a bare
numeric `id:` is expanded by `refdes id` and frozen at the number resolved
(`docs/design/keys.md` §2 recap; `ids.py`), and a link target is expanded to
the `DISPLAY-ID@key` composite and frozen, never re-resolved from the display
half at build time (keys.md §3). The argument transfers unchanged: resolve
the bare filename against the search path **once**, on a writable command,
and rewrite the source file's `<img src="diagram.png">` to the concrete
relative path that was found (`<img src="figures/power/diagram.png">`) —
the same write-back mechanism `_process_images` already has the hook for,
since it already rewrites every `<img src>` it processes into
`assets/<hashed path>` in the rendered HTML (`build.py:1591`); this adds an
earlier, source-file-mutating pass in front of it, gated by `--no-write`
exactly as key minting and link expansion already are (keys.md §2). Without
freezing, the tool would instead need to re-run the same search, from
scratch, on every future build — meaning that adding a second, later file
also named `diagram.png` to the search path silently changes which file an
*existing, unmodified* document points to, with no diff anywhere to show it.
That is the board-from-path mistake in a new location: permanent meaning
(which photo this document shows) derived from ambient state (whatever
happens to be on disk this time) instead of being pinned the moment it was
established.

**One place the analogy runs out, and it should be disclosed rather than
implied away: freezing does not give the asset an identity the way a
surrogate key gives an item one.** An item's key survives a rename or a file
move because the tool controls both ends of that reference and rewrites it
(keys.md §3's refresh rule). An image file has no key — it is bytes on disk
identified only by its path — so once `<img src="figures/power/diagram.png">`
is written, moving `diagram.png` breaks it exactly as a hand-written relative
path breaks today, with no different failure mode and no automatic repair.
What resolve-and-freeze actually buys is authoring convenience (write a short
name once, and the tool finds and pins the correct long path for you) and
robustness to *moving the document* (the frozen path no longer depends on
where the referencing file lives), not robustness to moving the *asset*. That
distinction is worth stating plainly in whatever documents this, since "smart
asset resolution" sounds like it should survive both and it only survives
one.

**5. Trigger — what counts as "the short form," and what does not change.**
Recommend a fallback chain, not a syntax switch: a `src` that resolves
relative to the source file's own directory keeps resolving exactly as it
does today — zero behavior change for every existing document, and the
common case (an image sitting beside the markdown that embeds it) never
touches the search path at all. Only a `src` that **fails** to resolve
relative to the source file, **and has no path separator in it** (a bare
leaf filename, `diagram.png`, not `figures/diagram.png`), falls through to a
search-path lookup. A multi-segment relative path that fails to resolve
stays a plain "does not exist" error, not a search candidate — searching by
leaf name for a path that was clearly meant to be a specific location would
blur exactly the boundary §1 draws between a declared list and a tree walk,
and would make an author's typo in a subdirectory name silently resolve to
an unrelated file elsewhere on the search path instead of erroring. If it
still fails after the search-path lookup (not found, or found and ambiguous
per §3), it is the same build error `_process_images` already raises for a
missing image (`build.py:1575-1580`), extended to name which directories
were searched.

**6. Boundary — this is about `<img>`, not "assets" generally.** The finding
is scoped to photos and embedded images, and that scope should hold:
`site.assets:` already solves a different problem for everything else it
covers — a whole directory copied verbatim for an author-typed `href` the
tool never resolves or rewrites (a PDF, a datasheet not managed as a
citation) — and nothing about that needs filename search, because the author
already writes the exact path by hand into a link they control end to end.
Citations have their own resolution mechanism entirely (a URL or a
project-relative `path:`, pinned by content hash, vendored under
`.refdes/vendor/<sha256><ext>` — `citations.py`), chosen specifically because
provenance and hash-pinning matter more than authoring convenience for a
cited document; filename search would be the wrong model there even if it
were extended, since two datasheets legitimately sharing a filename across
vendors is normal, not an error. `[[fig:id]]` figure references are already
name-based, but the name is a **declared figure id**, not a filename — a
different addressing scheme solving a different problem (cross-referencing a
numbered figure in prose), and out of scope here. So the boundary is: this
applies to `<img src>` only, and only to the local-file case that today
resolves relative to the source file — a URL `src` is untouched
(`_URL_SCHEME_RE`, `build.py:1570`).

**Status: decided (2026-09-19).** The search list **reuses `site.assets:`** —
no separate `asset_search:` key (§2's recommendation, taken: one list, one
mental model, and a second list that usually mirrors the first is the
duplication this project refuses). A bare filename that exists in two or more of
those directories is an **error at the reference site** when an image names it,
naming every match and its full path, never a first-match pick; two same-named
files nobody references are not an error (§3 as corrected above). Rejected: a
second `asset_search:` key, for the mirroring-lists cost above, and any implicit
tie-breaker — first-declared directory, newest mtime, alphabetical — because
each is a rule no reader of the document can see. The exact error wording and
the fallback-chain trigger in §5 stand as written; nothing here is implemented.

**Local model: not suitable.** Ambiguity resolution and the freeze semantics
are exactly the shape of judgment call this project keeps off a smaller
model: getting either subtly wrong — a tie-breaker that silently picks a
file instead of erroring, or a freeze that re-resolves instead of pinning —
produces a build that succeeds while pointing at the wrong photo, which is
this project's characteristic failure and, per finding 33's framing of the
same rule, exactly the "no test that a delegating prompt would think to
write is likely to catch" case. This is also design-unsettled work under the
suitability rule's second clause (§2 above is a real open question, not yet
decided), which keeps it off regardless of how loud the eventual acceptance
test could be made.

---

## An idea from Jared, finding 37

### 37 — A tree view of the whole project, as part of the built site

**Source: Jared, using refdes at work, 2026-09-16, not from an issue.** He
asked whether a "tree view for everything" had ever been discussed — it has
not, in this backlog or in the design docs — and said it should be part of
basic site operation, not an editor-only feature. The motivation is
navigating a project you cannot hold in your head, and he named its own
half: it is the read side of the filtering problem the browser editor takes
as a v1 requirement (docs/design/browser-editor.md, "Filtering": *finding
the thing is most of what authoring a traceable project costs*). A filter
answers "which items match X"; a tree answers "where am I". Neither is the
other.

**What exists today, verified.** Three things are tree-shaped or
list-shaped, and none of them is this.

The **sidebar** is a real recursive tree — `NavNode` (nav.py:20-43) holds
links or groups of the same type to arbitrary depth, and `build_nav`
(nav.py:137-197) builds workspace groups nesting board groups nesting pages
— but it is a tree of **pages**, never of items. Its leaves are hand-written
pages and the generated reports; the items themselves appear only inside
pages. It collapses with `<details>`, pre-opened when the current page lives
inside a group (base.html.j2:30, `node.contains(current_page)`), which is
the collapse mechanism this finding should reuse rather than reinvent.

**`{{cascade}}`** (blocks.py:362-412) is a tree of items, and the closest
thing to this finding — but it is a tree along **one relation from one
root**: `from` and `direction` are required, `via` names the link types to
follow (default: every `trace`-enabled verb, blocks.py:384-393), `depth`
bounds the walk at 3 by default. Its cycle handling is the part worth
reading before designing anything new (blocks.py:250-336): the walk keeps a
`visited` set seeded with the root (blocks.py:277), and following an edge to
an already-visited item renders it **once more as a terminal leaf** annotated
`(already shown above)` (blocks.py:324-327, 346) instead of recursing — one
rule that handles a true cycle and an ordinary diamond identically, because
bounding on *node* answers both. The same primitive, with `on_cycle="error"`
instead (`CascadeCycleError`, blocks.py:234-248), is what `blocked.py`
reuses to make a `blocked_by` cycle a hard build error (blocked.py:68-99) —
so the seam already has two callers with two different cycle policies and a
documented reason for each.

**`{{index}}`** (blocks.py:132-198) is tables, not a tree: items of one type
filtered by `board=`/`tag=`, grouped under `<h4>` headings by one field's
value. One level, no nesting, no parent-child anything. And the **item
dashboard** is a flat table of every item — the exact wall this finding is
about: at project scale it is a list nobody scrolls.

**The relations a tree could nest by**, and what each already means:
`part_of:`/`contains` with the `group` type (finding 14, shipped — members
point at the group, `contains` is the computed backlink, groups are
deliberately not coverable and not satisfaction targets); the coverage
chain `requirement → satisfied_by → verified_by`, which is not a stored
edge but a computed stage ladder (`compute_coverage`, build.py:769-780,
addressed/claimed/satisfied/verified; the five-stage order including `open`
at render.py:115); `blocked_by` (blocked.py — a graph asserted acyclic,
resolved transitively to roots); boards and workspaces, which are a
**registry**, not item relations at all — an item resolves to at most one
`str` board (finding 33's verified single-valued resolution) and workspaces
own items, not boards, in the registry (nav.py:150-155); and the folder
layout under `items/`, which multi-board.md:31 says outright is "just
organisation until you register them" — a tree view that nested by folders
would be deriving meaning from ambient file placement, the mistake this
project has corrected repeatedly.

**1. What does it nest by?** Three answers. (a) One fixed relation. (b) A
chosen one, like `{{cascade}}`'s `via=`. (c) A composite containment view:
workspaces → boards → groups → items.

(a) is not enough to be *the* view of everything: any single relation
omits every item that does not participate in it, and an omitting view
cannot be the site's basic orientation surface — see §2's no-omission rule.
(b) is already built and shipped: that is `{{cascade}}`, and re-listing its
design here would be re-deciding it. The honest division of labour is that
**relation-shaped trees are cascade's job and this finding should not
compete with it**. What cascade structurally cannot do is be total: a rooted
walk shows what is reachable from one item, and says nothing about the rest
of the project.

So the recommendation is **(c) for the site-level view**: nest by the
containment spine — workspace (registry), then board (registry), then
`part_of` groups, then items — because it is the only nesting where **every
item has a place without the author having declared anything**: every item
has at most one board and zero-or-more groups, and the leftovers get an
explicit bucket (§2). And it is the question an author actually has when
they open "the tree view for everything": not "what traces from REQ-X" —
they know that question and already have `{{cascade}}` for it — but "what
is in this project, grouped how, and what is floating." That is a
containment question, and containment is what `part_of`/`contains` and the
registries already mean.

**2. It is a graph, not a tree — and the rendering rule must be stated, not
waved at.** An item can be `part_of` several groups; groups can contain
groups; `part_of` is an ordinary link type and can cycle. Three candidate
rules for an item with two parents: duplicate the subtree under each, show
it once with references elsewhere, or refuse to render. Refusing is out — a
view that errors because the data is legal is the tool scolding the project
for a shape the schema permits. Duplicating is what `{{cascade}}` does not
choose, and for a *total* view it is worse than in a rooted one: with N
parents the item's whole subtree appears N times, and a reader scanning for
"is this item in the project once" cannot tell whether the second copy is
the same item or a coincidence of naming.

**Recommendation: expand once, reference everywhere else — which is
cascade's answer generalised, not a second invention.** Each item renders
expanded under exactly one parent, chosen by a deterministic rule (first
board/group in a fixed order: registry order, then group id), and under
every other parent it renders as a leaf with a link, annotated with the
verb and the primary location — the same shape as `(already shown above)`
(blocks.py:346), reading e.g. `part_of GRP-PCIE-SPEC — see Board A >
GRP-PCIE`. Cycles need no new machinery: the visited-set-on-node rule
(blocks.py:324) terminates any walk whatever the graph does, and the
`visited` set is shared across the whole forest, not per-root, so an item
reachable from two roots still expands once. One implementation seam to
disclose honestly: `walk_cascade` creates its own `visited = {root_id}`
(blocks.py:277) and is single-root, so a forest walk either grows a
parameter to pass an external visited set in, or wraps it with a
multi-seeded entry point. That is a small change to a shipped primitive with
two existing callers and their tests; it should be made deliberately, not
by copy-pasting a second walker, which is exactly the drift risk keys.md §3
raises about the §3 refresh rule having one implementation.

**The no-omission rule, stated as an invariant: an item reachable by no
path at all must be visible somewhere, or the view lies by omission.** An
item with no board and no group — precisely finding 33's `items/shared/`
component, and every item in a project that has never used `part_of` at all
— must land in a visible synthetic bucket, `Project-wide`, rendered last
with a count. This is not optional polish: a tree view that quietly omits items is
the project's characteristic failure — a build that succeeds while hiding
something — and unlike finding 33's board pages, where the omission was one
surface among several that still showed the item, a tree advertised as *the
whole project* is read as exhaustive, so silence inside it reads as
nonexistence. The invariant is mechanically testable: the count of expanded
nodes equals `len(project.local_items)`, every time, on every fixture.
Naming matters too: `Project-wide`, not `(orphaned)` or `(unassigned)` —
multi-board.md:46-49 is explicit that shared items legitimately belong to
no board, so the bucket is an observation, not an accusation.

**3. Page, block, or both?** Both, and the existing machinery makes that
cheap rather than ambitious. The **block** is `{{tree}}`, a third member of
the family, registered as a `BlockSpec` in the same dict as its two siblings
(blocks.py:416-425) and inheriting every convention the family already
enforces: closed parameter set, no expressions, no nesting, narrative pages
only. Parameters, in the house style:

| Parameter | Required | Meaning |
|---|---|---|
| `board` | no | Scope to one board's subtree (validated against `project.boards`, `_suggest` on a typo — the `{{index}}` `board=` precedent, blocks.py:154) |
| `workspace` | no | Same, for the workspace registry |
| `via` | no | Nest one level deeper by a named relation *under* the containment spine (e.g. `via="satisfies"` expands each requirement's satisfiers inside its board/group branch); validated against `project.link_types` like cascade's `via=` (blocks.py:384-390) |
| `depth` | no, default `2` | How deep the containment spine expands before collapsing to counts |

Required parameters: none — `{{tree}}` alone is the whole-project view, and
that is the point: unlike `{{cascade}}`, which must be told its root, this
block has no root to ask for. A bad parameter reports through the machinery
that already exists and needs no new design: `_validate_params`
(blocks.py:117-128) raises `_BlockError` for an unknown or missing parameter
naming the accepted set, `extract_blocks` turns that into a `project.error`
with the page's file and the directive's line number plus a visible
`⚠` marker in the rendered page (blocks.py:462-467), and `refdes check`
reports it because `cmd_check` runs the full `build()` (cli.py:245), which
runs `render_pages` (build.py:1985) where block extraction lives. An unknown
parameter to `{{tree}}` is a check failure with a file:line, same as for the
other two.

The **page** is `tree.html`, generated unconditionally as part of the basic
site — this is the half Jared asked for specifically: "part of basic site
operation." The machinery already decides what a scope's page set is: add a
`"tree"` entry to `REPORT_LABELS` (nav.py:46-53) and `scope_reports`
(nav.py:55-92) and `render.render_site` writes it and the nav links it, with
the single-source-of-truth property that section's docstring exists to
protect — no dangle, no orphan. Scoped `tree-<board>.html` and its workspace
equivalent are in the v1 set — decided 2026-09-18, see Status — and whether
a given project actually gets one falls out of `scope_reports`' existing
"no items, no page" rule rather than needing its own decision.

**4. Scope and size.** v1 generates `tree.html` project-wide, and board- or
workspace-scoped `{{tree board=...}}` blocks in hand-written pages cover the
narrower views; `tree-<board>.html` as a generated report is easy to add
precisely because `scope_reports` is the one gate, and was decided on
2026-09-18 to join the scoped report set now rather than later — a board's
`document-<board>.html` already lists its items in reading order, so the
scoped tree's marginal value is smaller than the project-wide one's. On a large project the page must open
small: the spine expanded to `depth` (default 2 — workspaces/boards and
their group level, items collapsed to counts like "Board A > GRP-PCIE (9)"),
every collapsed node a `<details>` exactly like the sidebar's (base.html.j2:30),
which is CSS-only and keeps the promise output.md makes twice — "with
JavaScript disabled every reference is still a working link" (output.md:21-22)
and the narrow-viewport toggle where "no JavaScript is involved, and it
works with JavaScript disabled" (output.md:131-134). `<details>` is
therefore not a preference but a constraint this feature inherits: any
collapse mechanism that needs JS to expand is a non-starter, which rules out
the interactive tree widgets a JS app would reach for and is also, per the
editor's own deferred list, the difference between a built static page and
the editor surface. Print: expanded nodes print as an ordinary nested list,
the same argument index-blocks.md §6 makes for cascade's `<ul>` over a table.

**5. What it is for, honestly.** Two candidate answers, and the finding
should not pretend to be both. As a **report** — "what is unaddressed, what
hangs off this requirement" — it is redundant: `coverage.html` already
answers unaddressed by stage ladder, and `{{cascade}}` already answers
"what hangs off this" better than a global tree could, because rooted and
verb-filtered. As **navigation** — the question is why the sidebar plus
filtering is not enough. It is a fair challenge: the sidebar is a tree, and
the browser editor's filter list (v1, browser-editor.md) will facet by
type, board, coverage stage, and link relationships. The answer is that the
sidebar is a tree of *pages* and never shows an item, and a filter list is
by construction not a map — filtering answers a question you arrived with,
and at project scale the thing you cannot do with either existing surface is
see the shape you did not know to ask about: how much is filed, how much is
not, where the groups are, which board is a graveyard. That is orientation,
it is genuinely navigation, and it is what v1 serves. The report reading —
`Project-wide` as a standing finding-33 visibility surface, group sizes as a
smell test — is a consequence of the navigation view being total, not a
second feature, and should be documented as such rather than sold as an
audit tool.

**6. Interaction with the browser editor and finding 33.** With the editor:
same data, different surface, and the editor's own constraint binds here too
— the tree must be built from the **built** project through the
side-effect-free path, never a file scan, because "a list that disagreed
with the report page about which requirements are open would be worse than
no list" (browser-editor.md, Filtering). The editor's filtered list and the
tree are then two views of one built payload; when the editor ships, its
list should be able to render *inside* tree scope (filter within Board A),
and the tree's anchors (`#grp-pcie`, item ids as they are today) are what
make a tree node and a filter result the same addressable thing. Nothing in
v1 depends on the editor existing; nothing in the editor's design is
invalidated by the tree. With **finding 33**: this is the feature's quiet
payoff and should be said plainly — a tree with a mandatory no-omission
bucket is exactly where an item that belongs to no board becomes
conspicuous, on every build, to everyone, instead of being absent-in-silence
from board pages. It does not *fix* finding 33 (the shared component still
needs `includes:`-style display inclusion to appear on the boards that use
it), and it must not be documented as if it did: the bucket makes the gap
visible, which is a navigation win and a finding-33 input, not a resolution.

**v1 scope.** Include: `{{tree}}` as a third `BlockSpec` with
`board`/`workspace`/`via`/`depth`, validated by the existing
`_validate_params`/`extract_blocks` path so bad parameters are `refdes
check` errors with file:line; `tree.html` generated unconditionally via
`REPORT_LABELS`/`scope_reports`, plus scoped `tree-<board>.html` and
`tree-<workspace>.html` pages through the same gate; the containment spine
(workspace → board → group → item) with expand-once-reference-elsewhere
built on the visited-set rule from `walk_cascade`, including whatever small
visited-set-as-parameter seam the forest walk needs; the mandatory
`Project-wide` bucket with the totality test (expanded count ==
`len(project.local_items)`); `<details>`
collapse with `depth` default 2, no JavaScript; cycle termination by the
same node-bounded rule, with a fixture that has a `part_of` cycle and a
multi-group item. Refuse: folder-shaped nesting (multi-board.md:31);
relation-rooted trees that compete with `{{cascade}}` (use `via=` for the
one level of it this block offers); any JS-dependent behaviour; tree
*editing* — this is the read side, the editor owns writes; and any change
to what `board:`, `part_of`, or the coverage stages *mean* — the tree
renders the model, it does not amend it, and in particular `Project-wide`
is a render bucket, not a new item state anywhere in the data.

**Status: three questions decided 2026-09-18; the §1 containment-spine
question remains open.** Multi-parent items expand once — an item renders in
full under one deterministic primary parent and as a reference link under
every other, {{cascade}}'s rule generalised (§2); duplicating was rejected,
because in a total view a subtree repeated under N parents makes a reader
unable to tell a second copy from a coincidence of naming.
`tree-<board>.html` and the workspace equivalent join the scoped report set
now, not later (§4). And the catch-all bucket for items with no board and no
group is `Project-wide`, not `(unfiled)`: that name says what those items
are — shared, project-level items, which docs/multi-board.md:46-49 says
legitimately belong to no board — rather than what they lack, and it
matches how refdes already names its project-wide pages.

**Local model (not decided — my read): suitable, IF the task specifies the
totality tests.** The rendering is composition of things that exist —
`NavNode`'s recursive template macro, `walk_cascade`'s visited rule,
`BlockSpec` validation, `<details>` — and every parameter error is loud by
inheritance. But the finding's one hard promise is "never silently drop an
item," and a walker with a shared visited set dropping a multi-parent item
is precisely a silent-wrongness that a build passes and a casual reader
never notices. The task must name the tests: expanded count equals item
count on every fixture; a two-group item appears expanded once and as a
reference once; a `part_of` cycle terminates; an item with no board and no
group lands in `Project-wide`; and the JS-disabled contract holds (no
`<script>` in the tree's markup). Without those named, the verdict reverts,
for the same reason finding 14's does.

---

## An idea from Jared, finding 38

### 38 — A generated vocabulary reference and diagram

**Source: Jared, a direct request.** His complaint is the one this file has
been accumulating evidence for all month: the vocabulary — every type, field,
link verb, block parameter and reserved key an author can write — is declared
in one place and described in about six, and the described version keeps
slipping away from the declared one. He wants a dictionary generated from the
actual schema, with a diagram of how the types connect, and he was explicit
about two constraints: no reader-side JavaScript, and no Mermaid. The
agreement reached in conversation is that a build-time Python dependency is
acceptable (the `refdes[pdf]` extra at `pyproject.toml:41-47` is the
precedent), that the diagram is rendered to SVG when the docs build runs and
embedded as a plain `<svg>` element, and that nothing in the published site
fetches or executes anything to show it.

**1. What the vocabulary actually is — six families, and only three of them
live in a schema file.** A dictionary has to say what it is a dictionary of,
and the surprising part is that the schema is not the whole answer. Types:
seven in the bundled base (`requirement`, `bound`, `decision`, `test`,
`component`, `group`, `log` — `base.yaml:127-254`), eleven with the
`design-debate` preset (`debate`, `option`, `claim`, `position`). Fields: the
ones a type declares under `fields:` plus the ones `include:` pulls in from a
field set (`base.yaml:95-104` defines `provenance`, `stewardship` and
`citations`; `include:` appears at `base.yaml:138,156,177,196,214,236,249`),
each with its own option vocabulary — `type`, `required`, `required_when`,
`default`, `choices`, `on_change`. Link verbs: fifteen in the base
(`base.yaml:106-125`), nineteen with the preset, each carrying `inverse`,
`label` and optionally `trace`, with the legal targets declared per type under
`links:`. Those three families are data in YAML. The other three are Python:
the engine-reserved item keys (`RESERVED` at `parse.py:33`, the overridable
subset at `parse.py:37`, and the file-level `defaults:` / `section:`
constructs at `parse.py:576-609`), which are not schema fields at all and so
appear in no generated schema output; the generated-block syntax
(`{{index}}` and `{{cascade}}`, their required and optional parameters read
straight out of the registry at `blocks.py:416-426`, matched by the
whole-line `{{ ... }}` form at `blocks.py:46`); and the two bits of inline
syntax that live in markdown rather than YAML — `calc` blocks and their
`name : unit = expr` assignments (`calc.py:792-796`) with inline `{{P_diss}}`
references (`build.py:52`), and the image attribute suffix
`{width=60% caption="..." id="fig-curve"}` whose accepted names are
`IMAGE_ATTR_NAMES` at `build.py:78`. A generator that walks `project.types`
documents the first three families and is silent on the rest — and the last
three are exactly where the prose is vaguest today, because nothing declares
them in a form a reader can look up.

**2. The generated diagram already exists, and it is already stale.**
`refdes schema --graph` (`cli.py:828-829`, rendering
`schema_json.build_graph()`) prints Mermaid flowchart source for the resolved
type/link graph, and `docs/cli-reference.md:507-520` advertises it with the
claim that being "generated, not hand-drawn" means "a preset or project
overlay changing a verb can't leave it silently stale". `docs/links.md:97-121`
acts on that claim: it embeds the output under a comment reading "generated by
`refdes schema --graph` — do not hand-edit". That checked-in diagram is
wrong right now. It has no `group` node and no `part_of` edge anywhere, and
the hand-written verb table beside it (`docs/links.md:130-143`, fourteen rows)
omits `part_of` too — while the version this repo pins, `hardware@3`
(`refdes-project.yaml:47-50`), declares `part_of: {inverse: contains}` in its
link types and `part_of: [group]` on `requirement`, `bound`, `decision`,
`test` and `component` (`base.yaml:139-142,157-160,178-185,197-199,215-220`).
`grep part_of docs/links.md` returns nothing. This is the single most useful
fact in this finding, because it locates the real problem: generation is not
what keeps a document honest. The comment on that block says do not hand-edit,
and nobody did, and it is still wrong — because nothing regenerates that file.
By contrast the *other* generated artifact in the docs has a gate: CI runs
`python docs-site/gen_examples.py --check` (`.github/workflows/docs.yml:39-40`)
and `tests/test_docs_examples.py` asserts byte-for-byte that the injected
examples equal `scaffold.new_item_text()`'s live output. So the shape of this
finding is not "write a diagram generator"; it is "put every vocabulary
description under the gate finding 20 already built, and stop checking in
diagrams that the gate does not cover".

**Decided (2026-09-19), and one consequence pinned here:** the generated SVG
**replaces** the Mermaid output of `refdes schema --graph` (`cli.py:829-830`;
the flag's own help, `cli.py:1438-1440`, says "Mermaid flowchart source") rather
than becoming a second diagram generator sitting next to it. Jared does not want
Mermaid in this project, so there is one diagram mechanism — the SVG emitter of
§6 — and the checked-in Mermaid block at `docs/links.md:97-123` is deleted with
it, not regenerated.
(One half of the staleness claim above has since been fixed: `part_of`/`contains`
is now a row of the hand-written verb table, `docs/links.md:143`, landed in
`e43bbdb`. The embedded diagram is still stale — `grep -n part_of docs/links.md`
matches the table row and the `hardware@3` note under it, never the diagram —
which is the point this section makes.)

**3. Where the definitions live.** Three options, and the interesting part is
that the cheapest-looking one turned out not to be blocked at all — by either of
the things this section first said blocked it. (a) A `doc:` prose key on each
declaration in the YAML. This is the nicest end state — definition and
declaration in one place, impossible to forget to update separately — and it is
not free in either direction, though not for the reasons stated here when the
finding was written. It is **no longer true** that an unrecognised key inside a
type, field or link mapping is inert: that stopped when nested-config validation
landed on main in `a1899e5` (`src/refdes/configcheck.py`). One `BlockChecker`
now holds a closed key set per block — `TYPE_KEYS`, `FIELD_KEYS`, `BODY_KEYS`,
`LINK_TYPE_KEYS` at `configcheck.py:54-76` — and `BlockChecker.keys`
(`configcheck.py:98-116`) raises a `SchemaError` naming the unknown key, its
block path and a `difflib` did-you-mean, for `types.<name>`
(`configcheck.py:372`), `types.<name>.fields.<name>` (`:320`), `types.<name>.body`
(`:383`), `link_types.<name>` (`:357`) and the fields of a `field_sets:` entry
(the same `field_spec`, reached from `:338`); `schema.load_project` runs
`validate_settings` and `validate_overlay` before anything reads a block
(`schema.py:453-454`). So `doc:` is not a key the loader tolerates, it is a key
that has to be **added to those recognised sets** — types, fields, link types
and field sets — before anyone can write it anywhere, project overlay included.
That is a small diff, but it is a config-validation diff and not a docs diff,
and it is the thing to review. The bundled standard is not blocked either:
**`hardware@3` is not released.** Every `hardware@3` change sits under the
Unreleased section (`CHANGELOG.md:8`) — "**The bundled standard moves to
`hardware@3`.** Five changes, arriving together because none was ever published
on its own" (`CHANGELOG.md:27-28`) — the newest released section is
`[0.5.0] - 2026-08-21` (`CHANGELOG.md:291`), which is where `hardware@2` shipped
(`CHANGELOG.md:507`), and the freeze promise is written "Byte-identical forever
**once released**" (`base.yaml:3-5`); `tests/test_standards.py:95-96` guards
that promise for v1 against the addition of v2, which is a released-version
claim, not a claim about a version that has not shipped. `hardware@3` is still
moving under in-flight work — the `log`/`decision` merge lands in it, not in a
new `hardware@4` (`docs/design/extends.md:368-370`, and the phase ordering in
`docs/design/living-notes-plan.md:36`) — so `doc:` keys can go into
`standards/hardware/v3/base.yaml` directly, before its first release, and the
version bump this finding thought (a) had to pay for is not needed. (b) A
separate prose file keyed by term, checked against the resolved schema by the
lint in §4. (c) For the three code-defined families, the declaration *is* a docstring:
`RESERVED`, `BlockSpec`, `IMAGE_ATTR_NAMES` and the calc regexes are Python
objects, so a generator that reads them cannot drift, and the work is writing
the prose next to them rather than inventing a place to put it. Recommendation
for v1: (c) for the code families and (b) for the bundled types, fields and
verbs, with (a) allowed for project overlays. That is a deliberate
half-measure and I want to name the cost: (b) reintroduces the two-places
problem this finding is complaining about, and what makes it safe is not the
file layout but the lint. If the two-places compromise is unacceptable, the
alternative is a version bump, which is a bigger decision than a docs page and
should be made as one. **Decided otherwise (2026-09-19): (a), everywhere** —
every definition is a `doc:` key next to the declaration it defines, and there
is no separate vocabulary file. Jared: "They shouldn't be separated." The
half-measure is rejected precisely because of the cost named here: (b) is the
two-places problem this finding exists to close, papered over with a lint.
And the version bump the alternative required is not on the table — `hardware@3`
is unreleased (above), so the bundled `base.yaml` takes `doc:` keys in place.

**4. The lint — both directions, and it is the load-bearing part.** A term in
the resolved schema with no definition, and a definition naming no term, are
both build failures — the second with a `difflib` suggestion, the same trick
`parse.py:457` uses for an unknown link verb. Three more cases are worth
naming because they are the ones that will actually happen. A definition whose
term exists only in a preset the build didn't enable is not an error but must
not be rendered: generate from the resolved schema, never from the bundle, or
the page advertises `debate` to projects that never asked for `design-debate`.
A `doc:` key spelled `docs:` is no longer the quiet one: since `a1899e5` an
unknown key in a type, field, body, link-type or field-set spec is a hard
`SchemaError` with a did-you-mean (§3), so the typo fails the build at load
instead of silently deleting a definition, and the lint does **not** have to
police the spelling of the annotation itself. That job moved to `configcheck`,
which is where it belongs — it is a config error, not a documentation gap. What
the lint keeps is the two directions above and the preset case. And a term
renamed in one place and not the other is caught by both directions firing at
once. All of this runs inside the existing `--check` flag, in the CI step that already
exists at `docs.yml:40`, plus a sibling of `tests/test_docs_examples.py` so it
fires in `pytest` too and not only on the docs job.

**5. What each entry shows.** The definition; where it is declared; where it
may appear; what may point at it; and an example. "Where it is declared" is
the one with a catch: `_expand_include` resolves `include:` into `fields:` and
then *pops* the `include:` key (`standards.py:290-311`), so the resolved
schema no longer knows that `decision.source` came from `provenance`. Type and
verb provenance is half available — `Project.preset_provided_types` and
`preset_provided_links` (`model.py:641-642`, built by `standards.preset_providers()`)
named the preset for a name, which is how `parse.py:336,458` can say "provided
by the X preset, which is not listed under `standard.presets:`" — but the
`origin` map that distinguishes base from preset inside `_load_standard`
(`standards.py:110-116`) is local to that function and used only for collision
errors, and nothing at all records which field set a field came from. So the
generator either re-reads the raw bundle YAML or re-derives membership by set
intersection; I'd re-derive, since it costs nothing and keeps the generator
from depending on the bundle's file layout. "Where it may appear" for a verb
means its target list, with the empty-list case rendered explicitly —
`blocked_by: []` at `base.yaml:183` means unrestricted, and a reference that
prints an empty target list reads like a mistake. "What may point at it" is the
inverse, computed the way `schema_json.py` already computes it for editor
completion. The example should not be new writing: `scaffold.new_item_text()`
is already the single source for the per-type examples in
`docs/schema-reference.md` and is already byte-checked, so a type entry renders
that and a verb entry renders a two-item snippet built by the same code. Every
example is then loaded, not just rendered — written into the scratch project
`gen_examples.py` already builds from the repo's pin and run through the same
load-and-validate path `refdes check` uses, so an example that stopped
parsing is a failed build rather than a paragraph of YAML nobody can
copy-paste. Disclosed limit of that: filled-in example *values* are new
hand-written content, and the loader catches structural drift (unknown field,
bad `choices` value, missing required field) but not a value that is perfectly
well-formed and semantically silly.

**6. The diagram.** Nodes are types; edges are verbs, labelled with the verb;
targets come from each type's `links:`. Field-set membership is a different
relation and should be a different picture, not dashed edges on the same one —
a reader asking "what does `decision` inherit" and a reader asking "what can a
`decision` point at" are asking different questions. Size, counted from the
bundled standard: 23 link declarations expanding to 29 edges over 7 nodes;
with `design-debate`, 27 declarations, 36 edges, 11 nodes. That is small enough
that a general-purpose layout engine is overkill and large enough that a naive
force-directed placement is unreadable; what reads at that size is a layered
top-down arrangement — `group` and `bound` high, `requirement` mid, `decision`
and `component` below, `test` and `log` at the bottom — with edge ordering
within each layer chosen to reduce crossings. The dependency options, checked
against their own licence pages: `grandalf` is pure Python and implements a
Sugiyama layout in about 600 lines, but is GPL-2.0/EPL-1.0 and alpha-status,
and a viral licence in the dependency chain of an MIT project
(`pyproject.toml`, `license = {text = "MIT"}`) is not a trade worth making for
11 nodes; the `graphviz` and `pydot` packages are MIT but are wrappers that
need the native `dot` binary on `PATH`, which breaks `pip install refdes` on a
clean Windows box and adds a system package to the docs job; `pygraphviz` is
BSD-3 but a SWIG C extension needing a compiler and the Graphviz library;
`networkx` is BSD-3 and pure Python but is a very large dependency for one
small graph, and its layout functions want numpy at call time; `graph-layout`
(shakfu) is MIT, pure Python with optional Cython, ships a `SugiyamaLayout`
and a `to_svg()`, and its own documentation build does precisely what this
finding wants — execute tagged blocks in a markdown file and replace them with
inline SVG — which makes it the best library fit if a library is wanted at
all. My recommendation is to hand-roll the layout for v1: at this size the
layout is a fixed layer assignment plus a barycentre pass, a couple of hundred
lines with no dependency, and it produces coordinates that are byte-stable,
which the `--check` gate requires and a force-directed solver with a random
seed does not give for free. The emitter goes behind one function taking
nodes and edges and returning SVG, so swapping in a real engine is a
replacement and not a rewrite if a project's own overlay grows the graph past
the point where a fixed layout works. **Decided (2026-09-19): hand-rolled, as
recommended** — no graph library, on the licence and native-binary analysis
above. Taken as the default rather than a closed door: it is revisitable exactly
where this paragraph put the hinge, when an overlay outgrows a fixed layer
assignment, and the one-function emitter boundary is what makes that swap cheap.
Three rendering constraints, all of them promises the site already makes: inline `<svg>` rather than `<img src>`,
because inline is what lets fills use the theme's CSS custom properties and
therefore follow dark mode (README.md:344-346, `docs/output.md:20-21`);
nothing in the path fetches or executes, since the published site promises no
network calls and working links with JavaScript disabled; and print, where
`style.css:322-333` already reshapes the page and the diagram needs
`break-inside: avoid` next to the existing `.doc-item` rule so it isn't cut in
half across a page break. Clickable nodes are free in that scheme — an `<a
href="#term-decision">` around each node group works with no JavaScript and
degrades to ordinary text in print. And determinism is a feature of the gate,
not of the layout library: sort nodes and edges by name before emitting, or the
byte-equality check becomes a coin flip.

**7. Scope: the bundled standard, or every project's resolved schema.** v1 is
the docs-site page, generated against the repo's own pin — the same pinned
scratch project `gen_examples.py` already builds — because that is the
vocabulary the prose docs describe and it needs no new template. Per-project
should be scoped honestly rather than dismissed: the generator is a function of
a `Project`, so a page in every built site is one template, one nav entry
(`docs-site/refdes-project.yaml:16-40` is the nav list; pages come from
`site.pages`), and one extra render pass over a schema the build already walks
twice for `items.json` and `schema.json`. What it costs is two questions the
docs-site page can dodge. What does an override look like — the merged truth,
or the merged truth with origin labels, which needs the provenance §5 says is
discarded? And what does a project with forty types and ninety verbs get, where
the size assumption in §6 stops holding and the fixed layout has to become the
library case? Writing the generator as `vocabulary(project) -> (markdown, svg)`
makes the per-project page a template and a nav line later; writing it against
the docs-site project directly makes it a rewrite.

**Decided (2026-09-19): both surfaces, from one generator.** The bundled
standard's reference on the docs site *and* every project's own vocabulary —
local overlay types included — on that project's own built site. That makes
`vocabulary(project) -> (markdown, svg)` a requirement rather than a nicety: the
docs-site page is one call site with the repo's pinned scratch project, not a
separate code path. It also means the two questions this section says the
docs-site page can dodge are v1 work, not deferred work: how an override renders
(merged truth, with origin labels where §5's provenance can be recovered), and
what a forty-type project gets when the fixed layout stops holding.

**8. Failure modes, and which ones generation actually fixes.** A term renamed
with a stale definition, or a definition for a term that no longer exists: the
two lint directions, both build failures. An example that stopped parsing: the
scratch-project load, a build failure. A diagram that silently drops an edge:
this is the `docs/links.md` failure, and it is the one generation does *not*
fix by itself — the mitigation is a count printed in the page footer ("29 edges
from 23 declarations") and a test asserting the emitted edge count equals the
resolved schema's, so an omission moves a number instead of disappearing into
a picture nobody compares. A definition that is stale but still reads true: no
mechanical defence, and the page should say so rather than implying the
dictionary is verified prose. A preset-gated term rendered for a project that
didn't enable the preset: generate from the resolved schema (§4). And the
freeze trap from §3, which is a decision rather than a bug.

**v1 as I'd build it:** the lint and the generator in `docs-site/gen_examples.py`
as a second marker block under the existing `--check` flag and the existing CI
step; a `docs/vocabulary.md` page with one section per family from §1, in
reading order rather than alphabetical, since six of the terms in it
(`id`, `body`, `type`, `defaults`, `section`, `history`) are engine keys that
have no schema entry to sort under; the layered SVG emitter in the same file,
behind one function; the nav entry; and a fix to `docs/links.md` by pointing it
at the generated page instead of carrying a checked-in Mermaid block that
nothing regenerates.

**Status: decided (2026-09-19).** Definitions live next to each declaration as
a `doc:` key in the YAML, never in a separate file — Jared: "They shouldn't be
separated." Rejected: the separate prose file (§3's (b)) and the
`doc:`-keys-in-a-future-`hardware@4` variant, both because either one keeps the
two-places problem this finding exists to close; the bump is unnecessary anyway,
since `hardware@3` is unreleased and `v3/base.yaml` takes `doc:` keys in place
(§3). Because unknown keys in those specs have been hard errors since `a1899e5`,
`doc:` must be added to the recognised key sets for types, fields, link types
and field sets in `configcheck.py` before it can be written anywhere. Layout is
hand-rolled, no graph library (§6, the recommendation taken; default, revisitable
when an overlay outgrows a fixed layer assignment). Scope is both surfaces from
one generator — the bundled standard's reference on the docs site and each
project's own vocabulary, local overlay types included, on that project's own
site (§7). And the generated SVG replaces the `refdes schema --graph` Mermaid
output rather than adding a second generator: no Mermaid (§2). What is left is
implementation detail — the lint's wording, the layer assignment for the bundled
graph — not design.

**Local model: partly suitable, and the split is worth naming.** The generator,
the lint and the SVG emitter are the shape this project delegates: every
failure mode in §8 except the last is loud (a failed `--check`, an unparseable
example, an edge count that moves), the input is a data structure already in
memory, and the acceptance tests write themselves off §4. The layout is not.
"Is this diagram readable at 29 edges" is a judgment call with no failing test
attached, and a smaller model that gets it wrong produces a page that passes
every check and still cannot be read — the same silent-success class finding
33 frames, and the same reason `docs/links.md` shipped a stale diagram under a
"do not hand-edit" comment: nothing in the pipeline could tell anyone the
picture had stopped matching the thing it pictures.

---

### Living notes, history and task lists -- design draft

See [living-notes.md](living-notes.md) for the draft exploring dynamic notes,
captured history, and a task list that follows a thread tip.
