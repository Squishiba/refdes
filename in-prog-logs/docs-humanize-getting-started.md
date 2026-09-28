Task: apply the humanizing treatment to `docs/getting-started.md` — the plan's
proposed Tier 2 fallback (`.scratch/docs-humanizing-plan.txt` §5, "Proposed
decision rule if the pilot slice proves too subtle"). Full-page pass, Tier 2
item 3 of the §7 queue.
Role: delegated worker. Single-file edit.
Started: 2026-09-27
Status: FINISHED — page edited (4 changed regions in 3 hunks at git's default
context, 21 insertions / 17 deletions; 5 hunks at -U0), all acceptance checks
pass, changelog fragment added.

Plan location: the plan file is gitignored and per-worktree, so it is absent
here. Read read-only from the primary checkout:
  /home/jorb/work/refdes/.scratch/docs-humanizing-plan.txt      (404 lines)
Rubric source: plan §6 (P1-P7, H1-H8), acceptance checks plan §8 (A1-A9).
The pilot's rubric reconstruction and its two harness traps were read from
in-prog-logs/docs-humanize-troubleshooting-pilot.md. Per AGENTS.md I wrote
nothing outside this working directory.

Files changed by me (this is the complete change set):
  M docs/getting-started.md                              (prose only, 5 hunks)
  A changelog.d/docs-getting-started-prose.fixed.md
  A in-prog-logs/docs-humanize-getting-started.md          (this file)
Scratch (gitignored, left in place per AGENTS.md): `.scratch/doccheck.py`,
`.scratch/gs-before/`, `.scratch/gs-after/`, `.scratch/concepts-ref/`,
`.scratch/getting-started.HEAD.md`, `.scratch/initprobe/`, `.scratch/tutproj/`,
`.scratch/gs-schema.json`.

STEP 0 — ownership check. DONE. `git status` -> "nothing to commit, working
tree clean"; `git diff -- docs/getting-started.md` -> empty. No other session
owned this page. Nothing was staged, stashed, reset or cleaned at any point.

STEP 1 — CLI verified against THIS checkout. DONE. `refdes` is not on PATH and
system python3 has no refdes. The plan's borrowed-interpreter invocation,
pointed at this worktree, resolves to this tree:
  PYTHONPATH=$PWD/src /tmp/pypdf4/bin/python3 -c "import refdes; print(refdes.__file__)"
  -> /home/jorb/.paseo/worktrees/16msma8v/holy-pelican/src/refdes/__init__.py
Caveat carried forward from the plan and NOT resolved: third-party deps come
from another worktree's venv (/tmp/pypdf4). I installed nothing.

STEP 2 — the go/no-go the brief asked for. ANSWER: the page is NOT below the
`docs/concepts.md` bar in aggregate, and I did not treat it as if it were.
This is the honest headline finding, so here is the measurement.

Plan §11 U2 flagged that the original planning pass never read this page and
that the fallback's precondition — "that it is actually below the concepts.md
bar" — was UNVERIFIED. Verified now, by measurement (`.scratch/doccheck.py`
plus a paragraph/sentence census over non-fence, non-table, non-heading lines):

                          getting-started.md    concepts.md
  prose paragraphs                  23                 17
  prose words                      517                590
  longest paragraph          162 w (:43)          51 w (:101)
  longest sentence            37 w                 39 w (:106)

So on both sentence length and prose density the page is COMPARABLE TO OR
BETTER THAN the benchmark. The plan's Tier 2 framing ("narrative/tutorial,
prose-heavy") does not survive contact with the file: at 14 real fenced
blocks (the plan's "30 fences" is a count of ``` LINES) most of this page is
example, and the example is good.

The real defect is at PARAGRAPH scale, not sentence scale, and it is one
paragraph: :43-58 was a single 162-word block carrying six unrelated facts
(what init writes; the `version: 3` pinning caveat; where types come from;
`refdes-schema.yaml`; the `--standard none` escape hatch; `.vscode/settings.json`;
`items/` not being created) — 3.2x the benchmark's largest paragraph, with an
em-dash-spliced run-on at its core ("`version: 3` is ... never the literal word
`"latest"` — a later `refdes` may write a higher number here"). That is the
plan's `:146`-class defect (the worst readability defect the pilot found in
troubleshooting.md) reproduced in a different shape, and it is real.

VERDICT: go, but SCOPED. I rewrote that paragraph and four small, individually
defensible defects, and left the other 22 prose paragraphs byte-identical.
The brief's stop condition ("if it turns out to already be at that bar, say so
and stop") did not fire for the page as a whole; it DID fire for 22 of its 23
paragraphs, and I honoured it there. A whole-page rewrite would have been
manufacturing edits, which is the named failure mode in plan §9 R3
("over-editing into blandness").

STEP 3 — the rewrite. DONE. Rubric P1-P7 / H1-H8 (plan §6). 4 changed regions,
all prose, 21 insertions / 17 deletions.
  - :43-58, the mega-paragraph. 162 w / 7 sentences / longest 37 w -> 4
    paragraphs, 168 w / 11 sentences / longest 24 w. Longest paragraph on the
    page drops 162 w -> 75 w, and the longest sentence drops 37 w -> 24 w,
    which puts the page's worst case BELOW the benchmark's worst case. Every
    one of the six facts is retained, in the same direction and at the same
    strength; only the packaging changed. Two em-dash splices became sentences
    (H2) and the block is now four scannable units (H5). All 12 code spans and
    both links in the paragraph survive (P2/P3), which is why the
    "installed `refdes`" span appears twice still — see H6 note below.
  - :129-130, the one duplicated phrase. "the type that makes the next step
    possible" (:108) and "which is what makes the next step possible" (:129)
    said the same thing twice, ~20 lines apart. Dropped the second (H6). The
    surviving claim — "`limit` ... is parsed into a quantity, not stored as a
    string" — is untouched, including its slightly loose "not stored as a
    string" wording; see NUANCE 1.
  - :134-137, "— no trip back to this page needed." A self-referential aside
    aimed at the page, not the reader's problem (H1). Cut. The claim it hung
    off — same resolved schema as an editor's completion — is kept verbatim.
  - :227, "Note the test declares `verifies`." "Note" is on H1's canned-word
    list. Cut the word; the sentence is stronger as a statement.
  Deliberately NOT done, in the interest of R3:
  - :3-5, :14-16, :20-21, :66-67, :71-72, :92, :104, :108-110, :182-188,
    :204-208, :252-253, :255-260 all left byte-identical. I had a candidate
    rewrite for :20-21 ("A project is any folder containing `refdes-project.yaml`
    — the file is the project marker") on H4 grounds, and rejected it: "the
    project marker" is the term AGENTS.md itself uses for the file, so cutting
    it loses vocabulary rather than repetition.
  - :204-205 (the stderr/stdout interleaving caveat) is load-bearing and now
    has direct evidence behind it; see A9.
  - No heading touched, no fence touched, no example touched, no `**Remedy:**`
    -style structural convention invented (H8 — this page has none, and still
    has none).

STEP 4 — claims re-verified BEFORE rephrasing (P7), and the whole tutorial
executed. The pilot's A9 for troubleshooting.md was source-reading. For a
tutorial page there is a stronger check available, so I ran it: I built the
entire walkthrough in `.scratch/tutproj/` from the page's own YAML, verbatim.
Every claim in the page that has an observable consequence was executed.

  VERIFIED TRUE (page needs no correction, and I changed none of these):
  - `refdes init` writes exactly the two files shown and no more. Ran it:
    output yaml is byte-identical to the page's block; `.vscode/settings.json`
    is created; `items/` is NOT created (so "make it, and any folders under
    it, yourself" is correct); the init banner says
    "wrote refdes-project.yaml / standard: hardware@3".
  - `version: 3` is the newest bundled version, pinned as an integer, and
    init's own help says so: "<latest> is resolved to a concrete pinned integer,
    never written as the literal word 'latest'". The page's caveat ("a later
    `refdes` may write a higher number here; that is expected, and not a sign
    this page is out of date") is CORRECT and is preserved at full strength
    (P5). This is the page's one feature-status-flavoured hedge.
  - `refdes init --standard none` exists; help describes it as "the fully
    self-declared escape hatch (today's pre-standard behavior)", which is what
    the page's "as every project did before this existed" is gesturing at.
  - `refdes new decision` really does emit a starter with each field commented
    ("generated from the identical resolved schema 'refdes schema --json'
    emits"). See NUANCE 1 for the one word that overstates it.
  - `refdes id` output is byte-identical to the page's quoted block, including
    the `(items/requirements/power.yaml:9)` / `:13` line numbers.
  - `refdes build` output is byte-identical to the page's quoted block:
    "P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2",
    "2 item(s) with no coverage", "4 items, 1 errors, 1 warnings".
  - The page's stderr/stdout caveat (:204) is NOT decorative — my run really
    did interleave differently ("build completed with errors" landed between
    the ERROR and WARNING lines). The page says it may; it does. Kept verbatim.
  - The coverage claim at :228-229 is exactly right. From the built
    `_site/items.json`: REQ-PWR-001 stage `verified` (verified_by TST-PWR-001),
    REQ-PWR-002 stage `satisfied` (satisfied_by DEC-PWR-001, verified_by []).
  - The append-only claim at :252-253 is right. I edited the sealed LOG-001
    summary and rebuilt: "LOG-001 is append-only and has been modified since
    it was sealed. Append a new entry with `amends: [LOG-001]` instead". The
    page's "corrections are appended with `amends:`" is the same remedy.
  - `limit` is a real field type: `refdes schema --json` gives
    `bound__bare.properties.limit`, required, "parsed as a quantity with a
    comparison — '>= 9 V', '<= 600 mA'".

DISPUTES / NUANCES — REPORTED, NOT RESOLVED. No feature-status dispute and no
wrong claim was found on this page. That is itself a finding worth stating
plainly, because the plan's §10 F1/F2 disputes live on OTHER pages. Two small
things I noticed and deliberately did NOT touch:

  NUANCE 1 — "prints a starter with every field commented in" (:136) is very
    slightly stronger than what `refdes new decision` does. `title:` and
    `status:` are emitted UNCOMMENTED (as required fields, carrying their own
    trailing `# required -- text` / `# choices: ...` annotations); the other 15
    fields are commented out. I rephrased around this sentence (to cut the
    "no trip back to this page needed" aside) and deliberately left the claim's
    wording and strength alone rather than narrowing it to "every optional
    field". P6/P7: report, do not fix. A reviewer may want "with every field
    annotated" instead.
  NUANCE 2 — "not stored as a string" (:130) is loose in the same direction:
    in `refdes schema --json`, `limit` IS `"type": "string"`. The tool parses
    it as a quantity at build time, which is the point the sentence is making,
    and the schema's own description says "parsed as a quantity with a
    comparison". So the sentence is defensible as written and I left it
    exactly as written (P6). Flagged only because a pedantic reader with the
    JSON schema open could object.

NEITHER nuance is a feature-status claim, so neither was a P7 freeze. Neither
touched a disputed fact. Both are recorded here for the reviewer.

ACCEPTANCE CHECKS (plan §8) — my own results, re-runnable by a reviewer.
Harness: `.scratch/doccheck.py {extract,compare}`, reconstructed from the
pilot's log (its copy did not survive into this worktree; the pilot worktree is
gone). Baseline is `git show HEAD:docs/getting-started.md` in
`.scratch/getting-started.HEAD.md`; "after" is the working tree. Reproduce:
  /tmp/pypdf4/bin/python3 .scratch/doccheck.py extract .scratch/getting-started.HEAD.md .scratch/gs-before
  /tmp/pypdf4/bin/python3 .scratch/doccheck.py extract docs/getting-started.md .scratch/gs-after
  /tmp/pypdf4/bin/python3 .scratch/doccheck.py compare .scratch/gs-before .scratch/gs-after
Harness notes, both of which changed a result on this page:
  (i) The line-local code-span regex `` `([^`\n]+)` `` would MISS spans that
      wrap a line, and this page has them (e.g. the `refdes-schema.yaml` span
      and the `[editor support](...)` link text are split across lines at
      :49-50 and :55-56). The harness pairs backtick runs the way CommonMark
      does and normalises the line ending to a space: 46 prose spans are seen.
      A naive regex would have reported a smaller, wrong number and made A3
      partly vacuous.
  (ii) Fence CONTENTS are the authoritative A2 comparison, never fence line
      numbers — the same trap the pilot hit on A5. My first harness run
      reported A2 FAIL for exactly that reason (fences.jsonl embeds start/end
      line numbers, and this edit adds 8 lines, so 11 of 14 blocks shift). I
      fixed the harness to compare contents and report position shifts as INFO.
      Independently confirmed by a second method: sha256 over each of the 14
      block bodies, HEAD vs worktree, identical.
  (iii) Plan §2/§7's "30 fences" for this file is a count of ``` LINES, not
      blocks. This page has 14 real fenced blocks. The nested ```calc block
      inside the four-backtick decision example is correctly treated as part of
      its parent block, and there are 0 code spans inside any fence, so A3's
      prose/fence split is not double-counting here.

  A1 Scoped diff and ownership. PASS. `git status --short` -> only
    ` M docs/getting-started.md` plus my two new files. `git diff --stat --
    docs/getting-started.md` -> 1 file, 21 insertions(+), 17 deletions(-).
    Every hunk is prose, in 4 regions: :43-58 (2 hunks at -U0, 1 at default
    context), :129-130, :134-137, :227. No
    other section of the page is touched; no other file is modified except my
    log and my changelog fragment. Ownership confirmed clean BEFORE editing.
  A2 Fenced-block byte equality. PASS. 14 blocks before, 14 after, 0 differing
    bodies, info strings unchanged. Double-checked with sha256 per block.
  A3 Inline code-span multiset. PASS. 46 prose spans before, 46 after; sorted
    multiset byte-identical. 0 spans inside fences on both sides.
  A4 Link/anchor preservation. PASS. 9 `](...)` targets before and after,
    byte-identical; 0 reference definitions. Anchor resolution, re-run after
    the edit with a GitHub-slug resolver: all 7 file-only links exist and both
    anchors resolve — `standard-library.md#editor-support-json-schema-emission`
    ("## Editor support: JSON Schema emission") and
    `standard-library.md#versioning-and-pinning` ("## Versioning and
    pinning"). 0 broken. (This page has none of the pilot's DISPUTE 2-style
    dead anchor.)
  A5 Heading set/order. PASS. 10 headings, text and order identical, 0 added,
    0 removed.
  A6 No new identifiers. PASS. Unique span contents before and after are set-
    equal; added=[] and removed=[]. Every identifier in the new prose was
    already on the page.
  A7 Word count. PASS. 1127 -> 1108, -1.7%, budget +/-15%. The edited regions
    went 162+27+46+33 = 268 w -> 168+21+44+31 = 264 w, so nothing was gutted
    and nothing was padded.
  A8 Repo gates. PASS.
    `pytest tests/test_docs_examples.py tests/test_vocabulary_page.py
     tests/test_themes_page.py -q` -> 35 passed in 2.07s.
    `python docs-site/gen_examples.py --check` -> "docs/schema-reference.md is up
     to date." / "docs/vocabulary.md is up to date.", exit 0.
    Also ran `pytest tests/test_config_unknown_keys.py -q` -> 51 passed: that
    file is the only test that mentions this page (it asserts
    `docs.nav_order[:2] == ["index", "getting-started"]`, i.e. nav order, not
    prose), and I changed no heading or filename.
  A9 Spot-verify rephrased claims. DONE, and then some — see STEP 4. I
    executed the full walkthrough rather than only spot-checking, because for a
    tutorial that is both cheaper and stronger than reading source. Every
    claim I rephrased around (the `version: 3` pinning caveat, `limit` as a
    field type, `new decision`'s shared schema) was verified before or during
    the rewrite, and both resulting sentences are sourced above. No audit of
    the fenced blocks was attempted or needed: A2 proves they are untouched.

SELF-REVIEW AGAINST THE PLAN'S §9 R TARGETS (for the reviewer, not a substitute).
  R1 meaning survived: the six facts of the old mega-paragraph are all still
    there, in the same order of explanation and at the same strength. The two
    facts most at risk were the "not a sign this page is out of date" caveat
    (kept, and now its own sentence) and the `refdes-schema.yaml`
    holds-only-`types:`/`link_types:`/`sets:` restriction (kept, in its own
    sentence). The one dropped clause is the duplicated
    "which is what makes the next step possible" (STEP 3, H6) and the two
    asides named in STEP 3 — all three are restatement or page-talk, not facts.
  R2 status wording preserved, nothing to surface: the only feature-status
    sentence on the page is the `version: 3` pinning caveat, kept verbatim in
    direction and strength and now verified true against `init --help` and a
    real `init` run. No disputed status exists on this page, so unlike the
    pilot there is no F1-style freeze to honour.
  R3 voice: the page now reads more like `docs/concepts.md` in its worst spot
    and is untouched everywhere else. Concretely, the em-dash-spliced run-on
    and the two canned asides are gone; the page's genuinely good human lines
    ("Nobody typed 0.2366; the build computed it and compared it to the
    budget.") are byte-identical. I did not flatten the page into a uniform
    register, and I did not touch the 22 paragraphs that were already fine.
  R4 claims untouched: zero facts changed. A6 proves no identifier was added or
    renamed, A3 proves no code span was added or dropped, and every fenced
    block — which is where this page's factual content mostly lives — is
    byte-identical.
  R5 warnings/non-goals present: "they will never change" (:104), "no trip
    back to this page needed" removed but the stderr/stdout caveat (:204) and
    the append-only rule (:252) both survive verbatim, as does the
    "not a sign this page is out of date" hedge. No warning was softened.
  R6 cross-page consistency: no term was renamed, so no neighbour can have
    drifted. `docs/index.md` was not touched. "the project marker" was
    deliberately KEPT for the reason in STEP 3.

WHAT I DID NOT DO, DELIBERATELY.
  - Did not rewrite the 22 paragraphs that already meet the benchmark. This is
    the single biggest difference from how a "humanize the whole page" brief
    might read, and it is the brief's own stop condition applied at paragraph
    granularity.
  - Did not resolve NUANCE 1 or NUANCE 2, and did not add the words
    "optional"/"annotated" that would resolve them.
  - Did not touch any fenced block, including the quoted tool output — the
    quoted `refdes id` / `refdes build` output is correct as it stands, verified
    by execution, so there was nothing to fix and no licence to touch it.
  - Did not touch `docs/index.md`, any other page, or `docs/troubleshooting.md`.
  - Did not run `ruff` — no Python was changed, and AGENTS.md records that
    `ruff check .` is not a clean baseline and is not a valid gate.
  - Did not add a test. The guarantee here is the harness plus the existing
    docs gates; a test asserting my own prose would be the wrong shape.
  - Did not re-run the tutorial after the edit. No fence changed (A2), so the
    tutorial's behaviour is identical; STEP 4's runs are the evidence.

FOLLOW-UPS FOR THE ORCHESTRATOR (not done here).
  1. NUANCE 1 and NUANCE 2 above, if a reviewer wants them tightened. Both
    are one-word fixes to `docs/getting-started.md` and neither is urgent.
  2. Plan §7's Tier 2 ordering rests on line/word/fence counts (plan §11 U2),
    and this page shows those counts are a poor proxy: it looked like the
    prose-heaviest candidate in the plan and is in fact one of the better
    written. Consider reading before queueing the rest of Tier 2
    (lifecycle, coverage, change-tracking, design-log) rather than trusting
    the counts; plan §11 U3's "thin basis" worry is now a demonstrated risk.
  3. Plan §10 F1 (`refdes keys adopt`) and F2 (`bound` required field) remain
    open on troubleshooting.md and are untouched by this pass, as is the
    pilot's DISPUTE 2 dead anchor `ids.md#renumbering-former-ids`.
  4. Adopt `.scratch/doccheck.py` as the standing A2-A7 harness for the rest
    of the queue. The wrapped-code-span regex trap (i) and the line-number
    trap (ii) will each produce a false failure on some page in the queue.
  5. Note for whoever picks up troubleshooting.md's remaining sections: that
    page's DISPUTE 2 anchor fix and the `**Remedy:**` page-wide consistency
    question are still open from the pilot.
