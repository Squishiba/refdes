Task: Execute the humanizing PILOT proposed in `.scratch/docs-humanizing-plan.txt`
§5 — rewrite ONLY the `## Surrogate keys` section of `docs/troubleshooting.md`
(lines 102-147 of the pre-edit file).
Role: delegated pilot worker. Single-file, single-section edit.
Started: 2026-09-27
Status: FINISHED — section rewritten, all acceptance checks pass, changelog
fragment added.

Plan location: the plan and its companion log were NOT in this worktree. They
were found in the primary checkout and read read-only from there:
  /home/jorb/work/refdes/.scratch/docs-humanizing-plan.txt      (404 lines)
  /home/jorb/work/refdes/in-prog-logs/docs-humanizing-planning.txt (168 lines)
`.scratch/` is gitignored and per-worktree (AGENTS.md), which is why the plan
file was absent here. Per AGENTS.md I wrote nothing outside this working
directory; every file I created is in this worktree.

Files changed by me (this is the complete change set):
  M docs/troubleshooting.md            (the slice only — see A1)
  A changelog.d/docs-troubleshooting-surrogate-keys-prose.fixed.md
  A in-prog-logs/docs-humanize-troubleshooting-pilot.md          (this file)
Scratch (gitignored, left in place per AGENTS.md): `.scratch/doccheck.py`,
`.scratch/a-before/`, `.scratch/a-after/`, `.scratch/troubleshooting.HEAD.md`.

STEP 0 — ownership check (plan A1, run BEFORE editing). DONE.
  `git status` -> "nothing to commit, working tree clean".
  `git diff -- docs/troubleshooting.md` -> empty.
  So no other session owned this page. (Other files being dirty is expected
  per AGENTS.md and was not the case here anyway.)

STEP 1 — verified the CLI runs against THIS checkout (plan §0, U1). DONE.
  `refdes` is not on PATH and system python3 has no `pint`. The plan's
  borrowed-interpreter invocation, pointed at this worktree, resolves correctly:
    PYTHONPATH=$PWD/src /tmp/pypdf4/bin/python3 -c "import refdes; print(refdes.__file__)"
    -> /home/jorb/.paseo/worktrees/16msma8v/mighty-robin/src/refdes/__init__.py
  Caveat carried forward from the plan and NOT resolved: third-party deps come
  from another worktree's venv (/tmp/pypdf4). I installed nothing.

STEP 2 — re-verified the disputed/feature-status facts BEFORE rephrasing
(plan P7). DONE — and this changed what the section could safely say.
  - `refdes keys --help` -> `usage: refdes keys [-h] {adopt} ...` /
    "adopt  transactionally adopt key-keyed baselines and seals". Same
    command-surface-only evidence the plan recorded (plan §0). I did not run
    `adopt`. See DISPUTE 1.
  - The corruption lint whose messages this section quotes is NOT design-only
    in this tree. `src/refdes/keys.py:125-144` builds the malformed-key message
    (the "check character mismatch" reason is `:135`, the corruption sentence
    `:138-140`, the expected-char suffix `:142-144`);
    `keys.py:181-190` builds the "is already used by" message;
    `keys.py:549-555` the "key changed since baseline ... A key never changes
    legitimately." message; `keys.py:471-500` `deleted_key_message` the "key
    deleted ... now no key is declared." message and its "The old key is
    recorded for ..." clause plus the two-records-disagree note;
    `keys.py:591` the "older baseline ... references key" message.
    `src/refdes/build.py:492-503` builds both dangling-key messages (bare key
    drops the label clause; labelled key keeps it), `build.py:534` the
    " in {link} target (labelled {label})" context the page shows as
    "in refines target", `build.py:1367` the `check against` variant, and
    `build.py:553` / `:1391` the ordinary "which does not exist" messages.
  - Every quoted message in my slice therefore matches source, and every
    message I rephrased around was checked first (plan A9).
  - One re-cast worth naming: the old prose said "This is informational — the
    item was likely deleted." I replaced that restatement of the quoted
    message with its operational consequence, "The build is fine; `refdes
    audit` lists it so you can confirm the deletion was deliberate." Verified
    before writing: `keys.py:564-571` documents layer 5 as audit-only, and its
    only caller is `src/refdes/cli.py:599` inside the audit command — the
    standing layer-4 error is run separately by `validate()`. Same claim, same
    strength, concrete. Flagged here so a reviewer can second-guess it (R1).
  - I did NOT change, strengthen, or add any feature-status statement (P5).
    "A key never changes legitimately", "The label may be stale; the key is
    what resolves", "this is audit information, not a build error", "never
    edited by hand", "it will be re-minted", and "run a writable command to
    mint missing keys" are all still present at their original strength and in
    their original direction.

STEP 3 — the rewrite. DONE. Rubric P1-P7 / H1-H8 (plan §6).
  What I actually changed, defect by defect, all inside the section:
  - :107-114 (plan's cited defect). The quoted tool sentence was spliced
    mid-clause ("Each one continues `<long quote>`, and a check-character
    mismatch ends with ..."), and "never edited by hand" then appeared a second
    time in the author's own voice five lines later. Now: the quote is set off
    as its own sentence, the expected-char suffix is a separate short sentence,
    and the "written by `refdes` / never edited by hand" fact is stated once.
    The `refdes` code span had to survive (P2/P3 multiset), so it is carried by
    "`refdes` writes that line, and it is never edited by hand."
  - :117-118. Cause-after-effect inverted into effect-then-cause, one
    sentence each, so the remedy reads as the answer to a stated problem.
  - :123-124. Two sentences merged into one (H4: the second only
    re-encapsulated the first).
  - :130-132. "name where the old key survives" -> "say where the old key is
    still recorded", which is the message's own verb (keys.py:479).
  - :138-140. See STEP 2's re-cast note.
  - :146, the plan's "worst readability defect found in the sample": a single
    ~470-character sentence carrying four distinct facts. Now four sentences
    plus a lead-in for the variant pair, each fact on its own line. The
    `(if present)` condition on the label was deliberately KEPT — dropping it
    would have broadened the claim.
  - Dropped the trailing "too" from the two near-identical "give it a new
    display `id:` too" remedies. It is a canned carryover, carries no
    condition, and changes no code span.
  Structural convention (H8): the `**message** / **message**` quote headers and
  the `**Remedy:**` line are unchanged. `**Remedy:**` was NOT introduced
  anywhere outside this section, per H8 — the page-wide inconsistency is still
  the reviewer's call.
  Deliberately NOT done: no quoted message line was retyped. All ten long
  message lines are untouched context in the diff, so quote corruption is
  impossible by construction, not merely unlikely.
  Word count: slice 600 -> 607 words; file 2583 -> 2590 (+0.3%).

DISPUTES — REPORTED, NOT RESOLVED (plan P5/P7, §10 F1, R2).
  DISPUTE 1 — `refdes keys adopt` feature status, UNRESOLVED. Stated on both
  sides, and I am not authorized to pick one.
    - `AGENTS.md:24` lists `refdes keys adopt` among the things "still design
      only".
    - The command surface contradicts it (STEP 2). Help output proves the
      subcommand is registered and described; it does not prove it is
      implemented, correct, or safe to document, and I did not run it.
    - NEW EVIDENCE I found this session, offered as evidence only, not as a
      verdict: `changelog.d/keys-adopt.added.md` exists in this tree (a
      "shipped in an earlier release" fragment); `docs/cli-reference.md:1037`
      is a full `## refdes keys adopt` section with examples;
      `docs/ids.md:146-148`, `docs/multi-board.md:111,136-137`,
      `docs/lifecycle.md:201` and `docs/links.md:41` all describe its
      behaviour in the present tense.
    - IMPORTANT FOR THE REVIEWER: `refdes keys adopt` does NOT appear anywhere
      in the section I edited (`grep -n adopt docs/troubleshooting.md` -> no
      match, before or after). The task brief said this section "touches" that
      claim; it does not. So there was no disputed sentence in my slice to
      freeze, and the feature-status wording I did preserve is the *adjacent*
      one — key minting, re-minting, and the corruption lint being live. Those
      I verified against source (STEP 2) and left at their original strength.
      The F1 dispute therefore passes through this pilot UNTOUCHED and still
      needs its own reconciliation pass.
  DISPUTE 2 — pre-existing dead anchor, NOT mine, NOT fixed (P6). Found by A4.
    `docs/troubleshooting.md:263` links `ids.md#renumbering-former-ids`, but the
    heading in `docs/ids.md` is "Renumbering `former_ids:`", whose GitHub slug
    is `renumbering-former_ids` (underscores are word characters). Line 263 is
    in the `## IDs` section, outside my slice; the link is byte-identical to
    HEAD, so this is pre-existing. Route to a link-fix pass.
  DISPUTE 3 — plan F2 and F3 re-confirmed as still open and still out of scope.
    `:47-50`'s "`requirement` and `bound` have no required field at all under
    **hardware@3**" and `:64`'s hardware@2 dating of the `constraint`->`bound`
    rename are both outside my slice; untouched.

ACCEPTANCE CHECKS (plan §8) — my own results, re-runnable by a reviewer.
  Harness: `.scratch/doccheck.py {extract,compare}`. Baseline is
  `git show HEAD:docs/troubleshooting.md` saved to
  `.scratch/troubleshooting.HEAD.md`; the "after" side is the working tree.
  Reproduce with:
    /tmp/pypdf4/bin/python3 .scratch/doccheck.py extract .scratch/troubleshooting.HEAD.md .scratch/a-before
    /tmp/pypdf4/bin/python3 .scratch/doccheck.py extract docs/troubleshooting.md .scratch/a-after
    /tmp/pypdf4/bin/python3 .scratch/doccheck.py compare .scratch/a-before .scratch/a-after
  Two harness notes, both of which changed a result, so do not trust a naive
  re-implementation:
   (i) The naive code-span regex `` `([^`\n]+)` `` MISSES spans that wrap a
       line, and three spans in this very section wrap (the corruption
       sentence, `(Expected check character 'a'.)`'s neighbour quote, and
       `The old key is recorded for ...`). Missing them would have made the A3
       multiset check vacuous for exactly the spans that matter most here. The
       harness pairs backtick runs the way CommonMark does and normalises the
       line ending to a space, so 28 spans are seen in the slice, not the 26 a
       line-local regex reports. Slice `key:` count is 5 and `id:` is 2, and
       the slice holds 0 links and 0 fenced blocks.
   (ii) Plan §2's "2 fences" for this file is a count of ``` LINES, not
       blocks: the file has exactly one real fenced block (lines 52-55). The
       four-backtick constructs the plan mentions at :203-205 and :221 are
       inline code spans containing triple backticks, not fences. A2 therefore
       compares one block — and it is outside my slice anyway, which is why the
       check is a regression guard rather than the main event.
   (iii) A5 must compare heading TEXT, not heading line numbers: the edit adds
       9 lines, so a heading's line number legitimately moves. My first run
         reported A5 FAIL for that reason alone; the headings themselves are
         identical.

  A1 Scoped diff and ownership. PASS.
    `git status --short` -> ` M docs/troubleshooting.md` only.
    `git diff --stat` -> 1 file, 30 insertions(+), 21 deletions(-).
    All 9 hunks fall in lines 107-156, i.e. inside `## Surrogate keys`
    (`:102`) and above `## Links` (`:158` after reflow; `:149` before). No hunk
    touches any other section, and no other file is modified except my log and
    my changelog fragment. Ownership was confirmed clean BEFORE editing (STEP 0).
    Nothing was staged, stashed, reset, or cleaned at any point.
  A2 Fenced-block byte equality. PASS. `fences.jsonl` and the rendered
    `fences.txt` are byte-identical (1 block, 4 lines, 52-55, outside the slice).
  A3 Inline code-span multiset. PASS. 211 spans before, 211 after; sorted
    multiset byte-identical. Unique-span set also identical (176), so nothing was
    renamed (A6 passes with it).
  A4 Link/anchor preservation. PASS for the multiset; 11 `](...)` targets before
    and after, byte-identical, and the raw link lines are byte-identical to
    HEAD. My slice contains zero links. Anchor resolution: 9 of 11 resolve;
    the 2 that do not are DISPUTE 2 (pre-existing dead anchor) and `file.pdf`,
    which is a literal example URL rather than a doc link. Both predate this
    edit.
  A5 Heading set/order. PASS (11 headings, text and order identical, 0 added,
    0 removed).
  A6 No new identifiers. PASS. 176 unique span contents before and after, set
    equality. Every quoted message and every identifier in the section is one
    that was already there.
  A7 Word count. PASS. 2583 -> 2590, +0.3%, budget +/-15%. The slice itself went
    600 -> 607 words, so nothing was gutted and nothing was padded.
  A8 Repo gates. PASS.
    `pytest tests/test_docs_examples.py tests/test_vocabulary_page.py
     tests/test_themes_page.py -q` -> 35 passed in 1.98s.
    `python docs-site/gen_examples.py --check` -> "docs/schema-reference.md is up
     to date." / "docs/vocabulary.md is up to date.", exit 0. (Run with
     PYTHONPATH=$PWD/src under the borrowed interpreter; these three pages hold
     no generated region I could have disturbed, but the gate is cheap and
     proves the pass left them alone.)
  A9 Spot-verify rephrased claims. DONE — see STEP 2. Every quoted message and
    every message-shaped claim in the section was checked against
    `src/refdes/keys.py` and `src/refdes/build.py` before I reworded around it;
    the two prose claims I newly introduced ("The build is fine", "resolution
    goes by it") are sourced in STEP 2. No full audit was attempted — that is
    out of scope for a humanizing pass by plan §3b.

SELF-REVIEW AGAINST THE PLAN'S R TARGETS (for the reviewer, not a substitute).
  R1 meaning survived: the two facts most at risk were the `(if present)`
    condition on a stale display label and the bare-key variant pair; both are
    intact and still attached to the same remedies. The one deliberate
    re-encapsulation is flagged in STEP 2.
  R2 status wording preserved, dispute surfaced: DISPUTE 1, and the
    brief-vs-reality mismatch about which section carries the claim.
  R3 voice: the section still uses the page's own `**message**` / `**Remedy:**`
    lookup-table shape and its em-dash asides. I did not flatten the six
    entries into a uniform register, and I did not over-edit the four entries
    the plan did not flag — blocks 2-5 got one or two sentences each, not a
    rewrite.
  R4 claims untouched: zero facts changed. A6 proves no identifier was added or
    renamed, and every message line is untouched diff context.
  R5 warnings/non-goals present: "A key never changes legitimately",
    "never edited by hand", "The label may be stale", "not a build error", and
    "if the target should exist" all survive at original strength.
  R6 cross-page consistency: no term was renamed, so no neighbour can have
    drifted. `docs/index.md` was not touched.

WHAT I DID NOT DO, DELIBERATELY.
  - Did not touch any other section of troubleshooting.md, including
    `## Items and fields` (the plan's next slice) and the rest of the file.
  - Did not resolve DISPUTE 1, DISPUTE 2, or plan F2/F3.
  - Did not introduce `**Remedy:**` outside this section (H8).
  - Did not add, remove, or reword a heading; did not reorder entries.
  - Did not run `ruff` — no Python was changed, and AGENTS.md records that
    `ruff check .` is not a clean baseline and is not a valid gate.
  - Did not add a test. The mechanical guarantees here are the harness plus
    the existing docs gates, and a new test asserting my own prose would be
    the wrong shape of guarantee.

FOLLOW-UPS FOR THE ORCHESTRATOR (not done here).
  1. Reconcile DISPUTE 1 (`refdes keys adopt`) in a factual pass. The new
     evidence in DISPUTE 1 is the strongest yet, but it is still command
     surface plus shipped-doc evidence, not an execution.
  2. Fix DISPUTE 2 (`ids.md#renumbering-former-ids` -> `#renumbering-former_ids`).
  3. Route plan F2 (the `bound` required-field claim) and F3 (hardware@2
     dating) to a factual audit.
  4. Adopt `.scratch/doccheck.py` (or port it) as the standing A2-A7 harness for
     the rest of the queue. The line-local code-span regex is a trap on any page
     with wrapped spans, and A5 must ignore heading line numbers or the queue
     will collect false failures.
  5. Decide the page-wide `**Remedy:**` consistency question (plan H8 leaves it
     to the reviewer). The rest of troubleshooting.md uses bare sentences with
     no labelled remedy.
  6. Correct plan §2/§4's fence accounting for this file (1 block, not 2; the
     four-backtick items are inline spans) before the next worker relies on it.
