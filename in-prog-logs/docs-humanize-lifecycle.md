Task: apply the humanizing treatment to `docs/lifecycle.md` — plan §7 Tier 2
item 4 (`/home/jorb/work/refdes/.scratch/docs-humanizing-plan.txt` §7 line 246:
"4. docs/lifecycle.md (340/2309w, 12 fences)"). Full-page pass.
Role: delegated worker. Single-file edit.
Started: 2026-09-27
Status: FINISHED — page edited (12 changed regions, 61 insertions / 44
deletions, all prose), all acceptance checks pass, changelog fragment added.

Plan location: the plan file is gitignored and per-worktree, so it is absent
here. Read read-only from the primary checkout:
  /home/jorb/work/refdes/.scratch/docs-humanizing-plan.txt      (404 lines)
Rubric source: plan §6 (P1-P7, H1-H8), acceptance checks plan §8 (A1-A9).
The two prior passes' logs were read in full for the established pattern:
  in-prog-logs/docs-humanize-troubleshooting-pilot.md   (PR #65, 319a79e)
  in-prog-logs/docs-humanize-getting-started.md         (PR #70, 72a34fc)
Per AGENTS.md I wrote nothing outside this working directory.

Files changed by me (this is the complete change set):
  M docs/lifecycle.md
  A changelog.d/docs-lifecycle-prose.fixed.md
  A in-prog-logs/docs-humanize-lifecycle.md               (this file)
Scratch (gitignored, left in place per AGENTS.md): `.scratch/doccheck.py`,
`.scratch/lc-before/`, `.scratch/lc-after/`, `.scratch/lifecycle.HEAD.md`,
`.scratch/selftest-gs/`, `.scratch/selftest-gs-pre/`, `.scratch/x/`,
`.scratch/gs-pre.md`, `.scratch/ts-pre.md`.

STEP 0 — ownership check. DONE, BEFORE editing.
  `git status` -> "On branch eatable-walrus / nothing to commit, working tree
  clean".
  `git diff -- docs/lifecycle.md` -> empty (exit 0, no output).
  So no other session owned this page, and the whole tree was clean. Nothing
  was staged, stashed, reset, or cleaned at any point in this task.

STEP 1 — harness reconstructed, and its traps are REAL on this page.
  `.scratch/doccheck.py {extract,compare,census}`. Neither prior worktree
  survived, so I rebuilt it from their logs and then VALIDATED it against the
  two pages whose exact counts those passes reported:

    page                          prior pass reported    my harness
    getting-started.md (post)     46 spans/14 blocks/10  46 / 14 / 10  match
                                 headings
    getting-started.md (pre)      46 spans (naive)       46            match

  So the reconstruction reproduces both prior A2/A3/A5 results exactly.

  IMPORTANT CORRECTION TO THE PRIOR LOGS, because it changes a number:
  the pilot's and the getting-started pass's harness note (i) — "a line-local
  code-span regex misses spans that wrap a line" — DOES NOT REPRODUCE on
  getting-started.md. I ran the naive `` `([^`\n]+)` `` regex against the
  pre-edit file and got 46, identical to the CommonMark-pairing harness, with
  identical multisets (no span only-in-either). The wrapped constructs the
  getting-started log cites at :49-50 and :55-56 are wrapped LINES carrying a
  span/link, not spans whose delimiters straddle a line break. I am recording
  this because I was about to repeat that claim in this log, and repeating an
  unreproduced harness claim is exactly the confident-but-wrong failure mode
  AGENTS.md warns about.

  The trap is nonetheless REAL on the page I am editing. Empirical counts:

    file                  naive spans   CommonMark spans   blocks
    docs/lifecycle.md         129             135             6
    docs/troubleshooting.md   209             210             1   (pre-PR-#65)
    docs/concepts.md           45              45             1
    docs/getting-started.md    46              46            14

  Six prose spans in lifecycle.md have delimiters that straddle a line break
  and that the naive regex therefore misses entirely:
    :6    `refdes\nbuild`
    :24   `refdes\ncheck`
    :185  `REQ-OLD-002\n(requirement) "Legacy input protection" — removed`
    :231  `refdes\naudit`
    :275  `(no\nrelease stamped yet)`
    :325  `refdes\naudit`
  135 - 129 = 6, exactly. A line-local A3 check on this page would have
  silently compared 129 spans and would NOT have caught an edit to any of
  those six — including the two `refdes audit` spans and the long `removed`
  example that the prose I rewrite sits right next to. The other two traps
  both apply too and are designed out: fence CONTENTS not line numbers (my
  edit adds lines, so 5 of 6 blocks shift), and heading TEXT not line numbers.

STEP 2 — the go/no-go, re-measured (the brief said don't trust the numbers).
  My own measurements, `.scratch/doccheck.py census`:

                              lifecycle.md   concepts.md
    lines / words             341 / 2309w     118 / 875w
    prose paragraphs          40              18
    prose words               1684            577
    longest paragraph         226 w (:190)    51 w (:101)
    longest sentence          103 w (:190)    39 w (:106)
    fenced blocks             6               1
    ``` lines                12              2

  The brief's "~12 fences" is, as in both prior passes, a count of ``` LINES
  not blocks. This page has 6 real fenced blocks. The brief's 340 lines /
  2309 words are correct.

  VERDICT: GO, and unlike getting-started.md this page really is below the
  benchmark. Its longest paragraph is 4.4x the benchmark's largest and its
  longest sentence 2.6x the benchmark's longest — worse than anything the
  pilot or the getting-started pass found. The 226w paragraph is at :190-207
  ("Hash format versioning") and it is the worst readability defect in this
  humanizing effort so far, beating the pilot's :146 470-character sentence.
  It also breaks the file's own wrap: :196 is 147 characters, ~1.9x the
  78-column convention every other prose line on the page follows. The
  getting-started pass's Tier-2 ordering rested on counts, and its own
  follow-up #2 warned those counts are a poor proxy; here they happened to
  point the right way, so this is the one page in the queue where the counts
  and the reading agree.

  Seven sentences on the page are 40w or longer; the plan's defect is not one
  bad sentence but a whole page that never breaks a thought.

STEP 3 — disputed/feature-status claims re-verified BEFORE rephrasing (P7).
  This page carries the plan's §10 F1 dispute IN THE MIDDLE OF THE PARAGRAPH
  I most wanted to rewrite (:201 pre-edit, `` `refdes keys adopt` names the
  entries it cannot carry ``), so the P7 freeze landed squarely on the hot
  spot rather than beside it. Verified against source, not memory:

  CLI verified against THIS checkout first (STEP 1 analogue): `refdes` is not
  on PATH, and the plan's borrowed-interpreter invocation resolves to this
  tree —
    PYTHONPATH=$PWD/src /tmp/pypdf4/bin/python3 -c "import refdes; print(refdes.__file__)"
    -> /home/jorb/.paseo/worktrees/16msma8v/eatable-walrus/src/refdes/__init__.py
  Caveat carried forward and NOT resolved: third-party deps come from another
  worktree's venv (/tmp/pypdf4). I installed nothing.

  - `refdes keys adopt` — the page's claim is TRUE in this tree, and I can now
    show it without running the command. `src/refdes/cli.py:1012` defines
    `cmd_keys_adopt`, and `cli.py:1063` inside it emits
    `f"  uncomparable baseline entry {baseline.name}: {item_id}"`, which is the
    page's quoted `uncomparable baseline entry <name>: <id>` exactly. The
    claim is therefore NOT a P7 freeze after all — I verified it, so I was free
    to reword around it, and I did not change its strength or direction.
  - `refdes audit` prints an `uncomparable N` line in the baseline diff —
    VERIFIED. `_print_baseline_diff` (`cli.py:563`) at `:571-573` prints
    `f"  uncomparable {len(diff.uncomparable)}   {uncomparable}"`. I checked
    this specifically because the only `uncomparable N` print I found at first
    glance was in `_run_stamp` (`cli.py:303-318`, under
    `outcome.status == "conflict"`), which would have made the page's
    attribution to `audit` look wrong. It is not wrong: both paths print it.
  - "`refdes revision`/`refdes release` name them when a re-stamp conflicts" —
    VERIFIED, that is the `cli.py:303-318` branch.
  - "They are not counted as unchanged either." — VERIFIED.
    `lifecycle.py:906` is a bare `continue` commented "neither 'changed' nor
    'unchanged' -- reported as uncomparable", and `_print_baseline_diff:586`
    prints the unchanged count from a separate tally.
  - `hash_format` "currently **5**" — VERIFIED, `build.py:1468` `HASH_FORMAT = 5`.
  - All five format descriptions — VERIFIED against the history comment at
    `build.py:1437-1464`, clause by clause, including the two "hashes exactly
    as under format N" no-op claims ("An item with no such reference has the
    exact same payload as format 3"; "...no image reference has the exact same
    payload as format 4"). The parenthetical I broke up was factually sound;
    only its packaging was broken.
  - The eight `release_gate:` defaults in the page's YAML block — VERIFIED
    key-by-key against `model.py:57-68`. All eight rows match, including
    `unverified_requirements` and `info_check_failures` defaulting
    release/revision false/false. "an overlay on the defaults" is
    `schema.py:174-175`; "difflib-suggested against the eight names" is
    `schema.py:197` (`difflib.get_close_matches(..., sorted(RELEASE_GATE_DEFAULTS), n=1)`).
  - The eight-row gate table — VERIFIED against `_RULES` (`lifecycle.py:584-593`)
    and each `_rule_*` body: `draft_items` over `local_items` via `_is_draft`;
    `unpinned_citations` = `state == "unpinned"`; `missing_kept_copies` =
    `state == "cache_missing"`; `uncovered_requirements` = `stage == "open"`;
    `unverified_requirements` = `stage != "verified"`;
    `info_check_failures` = resolved severity `!= INFO` and a failing check;
    the two move rules read `project.board_moves` / `project.workspace_moves`.
  - "Neither `uncovered_requirements` nor `unverified_requirements` count a
    draft item's open coverage against it" — VERIFIED, `_coverable_offenders`
    (`lifecycle.py:534-549`) skips `_is_draft` items, and its docstring gives
    this exact reason.
  - The "Draft detection" paragraph — VERIFIED almost sentence-for-sentence
    against `_draft_field_name`'s docstring (`lifecycle.py:474-484`): a field
    literally named `status`, `type: enum`, `draft` among the declared
    choices, and the docstring itself names "the same field-existence
    convention satisfying_statuses:/coverable_statuses: already use". A type
    with no such field returns None and never trips the rule.
  - "this rule resolves it per item, not per type" — VERIFIED,
    `_rule_info_check_failures` (`lifecycle.py:560-573`) uses
    `build_mod._severity_for(spec, item)`, and its docstring says the gate
    "must resolve severity per item, not per type".
  - "docs/design/candidate-parts.md §4" — VERIFIED, that file's `## 4. (B)
    Status-dependent `check_severity`` is the right section. (The code's own
    comment cites §4.5, "The release gate" — a subsection of §4, so the page's
    coarser pointer is not wrong. Noted, not changed.)
  - "no flags on either" and "there is no `--dry-run`" — VERIFIED.
    `refdes release --help` and `refdes revision --help` each show
    `usage: refdes <cmd> [-h] name` and nothing else, and both help strings
    carry the "running this when the project isn't ready *is* the check"
    wording the page paraphrases. `_run_stamp`'s docstring (`cli.py:276`) says
    the same thing in the same words.
  - The error floor — VERIFIED. `cli.py:286-288` builds read-only and returns
    `_report(project)` on any `project.errors` BEFORE `stamp()` is reached, so
    nothing is written.
  - "zero git object reads" / "git is never invoked at all" — VERIFIED against
    the `lifecycle.py:14-16` docstring ("nothing here ever invokes git, reads
    `.git/config`, or touches the object database") and
    `lifecycle.py:454-455` for the `os_user` default.
  - The "Re-running the same name" entry — VERIFIED. `lifecycle.py:684-693`
    returns `status="unchanged"` with the file untouched, "not even stamped_at
    rewritten, mirroring `refdes fetch`", gated on `existing.kind == kind and
    _same_baseline_items(...)` — which is the page's "same items, same kind"
    exactly; `:694-700` is the differing-content error with the
    "names are permanent once written" wording behind it.
  - `(no revision stamped yet)` / `(no release stamped yet)` — VERIFIED,
    `cli.py:679` and `cli.py:687`.

  I DID NOT VERIFY, and am not asserting: "Neither command checks git
  working-tree cleanliness." A negative claim about absence of behaviour, and
  I found no cleanliness check in `lifecycle.py` — but absence of a grep hit
  is not proof of absence, and I did not run either command against a dirty
  tree to confirm. Left byte-identical, flagged here rather than asserted.

STEP 4 — the rewrite. DONE. Rubric P1-P7 / H1-H8 (plan §6). 12 changed
  regions, 61 insertions / 44 deletions, all prose.

  The dominant one, and the only place I did structural rather than cosmetic
  work:
  - :190-207 pre-edit, the 226-word paragraph. One 103-word sentence held a
    five-item enumeration inside a parenthetical, and the sentence then
    continued past the closing paren into the migration rule, so the
    enumeration and the rule that consumes it were a single syntactic unit.
    It is now four paragraphs: the definitions, the two no-op facts they imply
    for an item that has neither, the migration rule, and the `uncomparable`
    distinction. Every one of the five format descriptions survives with its
    original wording; the two `--` asides became a full sentence. I also
    rewrapped :196, which was 147 characters — the only prose line on the page
    over 80 and a clear break of the file's own 78-column wrap.
  - :171-179, the 102-word paragraph holding a 51-word sentence. Now three
    paragraphs. The second `only` in "`verdict` only for a type with a
    verdict-bearing status field" was dropped: it restated "the rest only when
    they apply" in the same sentence (H4). I judged that a de-duplication
    rather than a meaning change — the surviving clause is still the only-when
    condition — and it is called out here so a reviewer can disagree.
  - :68-76, the 103-word paragraph. Split into three, and its 40-word
    em-dash-spliced sentence ("...moves to `selected` — so `refdes release`
    can go from clean to blocked...") broken at the dash, because those are
    two independent claims welded into one breath.
  - Six smaller ones, all single-clause fixes: the semicolon splices at :106
    and :291 and :298; the 46-word "since ... and ..." double-justification in
    the `git_identity` bullet; the 40-word two-questions sentence, whose
    parenthetical became a clause; the 42-word `relabelled` sentence; and the
    two "simply"s at :341 and :347, six lines apart, meaning the same thing
    (H1 + H6).

  Deliberately NOT done, and this is most of the page (R3, "over-editing into
  blandness" — the failure mode plan §9 names):
  - The three bullets at the top, "Two layers.", the gate table, both
    "**Why ...**" paragraphs, the "Draft detection" paragraph, the
    "Neither `uncovered_requirements` nor ..." paragraph, the baseline-file
    intro, the "**`type`/`title` per item, not just a hash**" paragraph, the
    `os_user` bullet, the two diff bullets, "Baselines:" and "Not the
    git-history layer" openers, and all four Edge-case entries are
    byte-identical. Every one of them already has short sentences and the
    page's own structural shapes.
  - I specifically considered and rejected splitting the "An item deleted
    since a baseline was stamped." Edge-case entry (69w) and the
    "What still needs an actual git-backed layer" paragraph (66w). Both are
    modestly over the benchmark's 51w, but their longest sentences are 30w and
    28w, and the Edge-case entry matches its four sibling entries. Paragraph
    count was not the defect on this page; sentence shape was.
  - No heading, fence, table cell, link, or example touched. No
    `**Remedy:**`-style convention invented (H8 — this page has none, and
    still has none).

ACCEPTANCE CHECKS (plan §8) — my own results, re-runnable by a reviewer.
  Harness: `.scratch/doccheck.py {extract,compare,census}`. Baseline is
  `git show HEAD:docs/lifecycle.md` in `.scratch/lifecycle.HEAD.md`; "after"
  is the working tree. Reproduce:
    python3 .scratch/doccheck.py extract .scratch/lifecycle.HEAD.md .scratch/lc-before
    python3 .scratch/doccheck.py extract docs/lifecycle.md .scratch/lc-after
    python3 .scratch/doccheck.py compare .scratch/lc-before .scratch/lc-after
  System python3 3.13.5 is enough for the harness (stdlib only); the gates in
  A8 need the borrowed interpreter.

  THREE HARNESS BUGS I HIT AND FIXED, because each one produced a confident
  wrong number first, and a reviewer re-running this should not inherit them:
  (i) The naive code-span regex misses the six straddle spans listed in STEP 1.
      135 vs 129 on this page. Designed out: backtick runs paired CommonMark-style.
  (ii) Fence line numbers shift when prose is reflowed — my edit adds 17 lines,
       so 5 of the 6 blocks move. Designed out: A2 compares contents + info
       string and reports shifts as INFO. Cross-checked by an independent
       sha256-per-block script, 6/6 identical.
  (iii) NEW, and the mirror image of (i): my heading scanner counted `#`
        comments inside fenced code as headings, so it reported 14 headings
        instead of 9 — this page's baseline block has `# The standard the
        project was pinned to...` and `# Present only for kind: release...` in
        it, and the `stamped_by` block has `# refdes-project.yaml`. A5 still
        PASSED, because the bug was symmetric across before/after, so the
        comparison stayed valid — but the reported count was wrong and a
        reviewer diffing "14 headings" against the file would have found nine
        and rightly doubted the harness. Now fence lines are excluded, and the
        real count is 9. Re-validated after the fix against getting-started.md
        (still 46 spans / 14 blocks / 10 headings, matching PR #70).

  A1 Scoped diff and ownership. PASS.
    `git status` before editing: "nothing to commit, working tree clean";
    `git diff -- docs/lifecycle.md`: empty. Ownership confirmed clean BEFORE
    any edit (STEP 0). Nothing was staged, stashed, reset, or cleaned at any
    point. `git status --short` now shows exactly ` M docs/lifecycle.md` plus
    my two new files. `git diff --stat -- docs/lifecycle.md` -> 1 file,
    61 insertions(+), 44 deletions(-). All 14 hunks are prose; the gate table
    at :47-56, the 6 fenced blocks, all 9 headings, and all 3 links are
    untouched context in the diff.
  A2 Fenced-block byte equality. PASS. 6 blocks before, 6 after, 0 differing
    bodies, info strings unchanged (`yaml`, `console`, `console`, `yaml`,
    `yaml`, `console`). Independently confirmed by sha256 per block, HEAD vs
    worktree: all 6 identical.
  A3 Inline code-span multiset. PASS. 135 spans before, 135 after; sorted
    multiset byte-identical. 0 spans counted inside any fence on either side.
  A4 Link/anchor preservation. PASS. 3 `](...)` targets before and after,
    byte-identical; 0 reference definitions. Anchor resolution with a
    GitHub-slug resolver: `workspaces.md` and `change-tracking.md` both exist;
    `design-log.md#after-a-release` resolves to `## After a release`
    (design-log.md:193, slug `after-a-release`). 0 dead. This page has none of
    the pilot's DISPUTE 2-style broken anchor.
  A5 Heading set/order. PASS. 9 headings, text and order identical, 0 added,
    0 removed (see harness note (iii) for why the count is 9 and not 14).
  A6 No new identifiers. PASS. 94 unique span contents before and after,
    set-equal; added=[] and removed=[]. Every identifier in the new prose was
    already on the page — which is the check that matters most for the
    hash-format rewrite, where I had to re-word around eleven spans including
    two identical `checks: against:` and a compound `calc_hash`/`calc_refs`.
  A7 Word count. PASS. 2309 -> 2334, +1.1%, budget +/-15%. Prose-only
    paragraph count 40 -> 49 and prose words 1684 -> 1709, so nothing was gutted
    and nothing was padded; the growth is the paragraph breaks plus the
    "oldest first" / "cost an ordinary item nothing" connectives.
  A8 Repo gates. PASS.
    `pytest tests/test_docs_examples.py tests/test_vocabulary_page.py
     tests/test_themes_page.py -q` -> 35 passed in 1.99s.
    `python docs-site/gen_examples.py --check` -> "docs/schema-reference.md is up
    to date." / "docs/vocabulary.md is up to date.", exit 0.
    Also `pytest tests/test_config_unknown_keys.py -q` -> 51 passed, and
    `grep -rln "lifecycle.md" tests/` -> no match, so no test asserts against
    this page's prose or nav at all. (Run with PYTHONPATH=$PWD/src under
    /tmp/pypdf4; the three gated pages hold no generated region I could have
    disturbed, but the gate is cheap and proves the pass left them alone.)
  A9 Spot-verify rephrased claims. DONE, thoroughly — see STEP 3, which
    verified every claim on the page that carries an observable consequence,
    before rephrasing around it. This is the plan's "not a full audit" limit:
    I did not audit the 6 fenced blocks' internal claims, because A2 proves
    they are byte-identical to HEAD and I changed no byte inside them.

BEFORE / AFTER, worst case (the measurement the brief asked for).

                        before      after     concepts.md (benchmark)
  longest paragraph     226 w (:190)  77 w (:208)   51 w (:101)
  longest sentence      103 w (:190)  38 w          39 w (:106)
  prose paragraphs      40           49          18
  prose words           1684         1709        577
  sentences >= 40 w     7            0           —
  words / fences        2309 / 6     2334 / 6    875 / 1

  Honest reading of those numbers, rather than a victory lap:
  - Longest sentence 103w -> 38w, which puts the page's worst sentence BELOW
    the benchmark's worst (38 vs 39). That is a real pass.
  - Longest paragraph 226w -> 77w, a 2.9x cut and no longer 4.4x the
    benchmark — but 77w is still ABOVE the benchmark's 51w, so unlike the
    sentence metric this one does not clear the bar. I stopped there on
    purpose: the remaining 77w paragraph is four sentences of 16w/14w/29w/18w
    (trigger, recompute, branch, why) and splitting it would sever a mechanism
    chain rather than reveal anything. Its line number moved (:190 -> :208)
    because the edit added 18 lines above it.
  - No sentence on the page is 40 words or longer any more; all seven that
    were are gone, not shortened to just under the line.
  - `concepts.md` was NOT edited and remains the read-only benchmark (plan
    §7 Tier 0). Measured, never touched.

DISPUTES — REPORTED, NOT RESOLVED. One, and it is F1 from the plan.
  F1 (`refdes keys adopt` feature status) — STILL UNRESOLVED, and this page is
  now the strongest single piece of evidence for the "AGENTS.md is stale"
  side, which is exactly why I am reporting it rather than acting on it.
    - `AGENTS.md:24` lists `refdes keys adopt` among the things "still design
      only".
    - The command surface contradicts it: `refdes keys --help` prints
      `usage: refdes keys [-h] {adopt} ...` with "adopt — transactionally
      adopt key-keyed baselines and seals", and `refdes keys adopt --help`
      documents `--dry-run` and describes minting, link expansion, re-keying
      and a full revalidate.
    - WHAT I ADDED THIS SESSION, as evidence and not as a verdict: the page
      describes `keys adopt` behaviour in the present tense at :216, and that
      behaviour is backed by a real code path — `cmd_keys_adopt` at
      `cli.py:1012` with the `uncomparable baseline entry` report at
      `cli.py:1063` and a seal-entry twin at `:1072`. A description with no
      implementation behind it does not usually print a per-entry report.
    - WHAT IS STILL MISSING, and is why I am not calling it: I did not run
      `refdes keys adopt`. Command surface plus a plausible code path is not
      an execution, and the disagreement between AGENTS.md and the tool is a
      separate task from a humanizing pass. I did not soften, strengthen, or
      re-word the page's claim in either direction — it says what it said.
    - Note for whoever reconciles it: the plan's F1 evidence pointed at
      `docs/lifecycle.md:201` as one of five pages asserting adopt in the
      present tense. That line is inside the paragraph I rewrote most heavily,
      and I preserved the claim verbatim within it.

  Two smaller things, reported and deliberately NOT touched (P6):
  - "the diff view already reports the status change that caused it" (:76) is
    loose. The diff's `stale_arithmetic` report
    (`_print_baseline_diff`, `cli.py:569-570`) reports a status change that
    left a calc block stale, which is narrower than "the status change that
    caused it" implies for the general case. The sentence sits in the block I
    split, so I could have narrowed it, and did not — narrowing a claim is a
    factual edit, not a prose one.
  - "Neither command checks git working-tree cleanliness" (see STEP 3) is a
    negative claim I could not verify by execution. Untouched.

  Nothing else on this page is disputed, and — unlike the pilot — no disputed
  status needed protecting, because the one dispute here I was able to verify
  against source before rewriting around it.

SELF-REVIEW AGAINST THE PLAN'S §9 R TARGETS (for the reviewer, not a substitute).
  R1 meaning survived. The five format descriptions are the risk: all five are
    present with their original wording and their original order, both
    no-op clauses survived as a full sentence rather than an inline aside, the
    migration branch kept both arms ("if it matches... if not..."), and the
    `(if present)`-style condition the pilot had to protect has no analogue
    here. The one deliberate de-duplication is the dropped second `only` in the
    per-item additions sentence, flagged in STEP 4.
  R2 status wording preserved. The single feature-status-adjacent claim is
    the `keys adopt` sentence, byte-identical in strength and direction, with
    F1 surfaced above rather than silently resolved.
  R3 voice. The page's genuinely good lines are untouched: "Running `release`
    when you're not ready *is* the check", "A baseline's whole point is to
    stay legible after the live item is gone", the `REQ-OLD-002 removed`
    contrast at :190-191 (which is the best-written sentence on the page and
    which I deliberately did NOT "fix" the semicolon in), and the Edge-case
    entries. I did not flatten the two bolded rationale paragraphs or the
    bolded Edge-case lead-ins, and I added no structure the page lacked.
  R4 claims untouched. Zero facts changed. A6 proves no identifier was added,
    dropped, or renamed; A3 proves the code-span multiset is identical; A2
    proves all 6 fenced blocks are byte-identical, and that is where this
    page's quoted tool output lives.
  R5 warnings and non-goals present. "no flags on either", "there is no
    `--dry-run`", "Not a gate condition", "No dedicated subcommand", "No
    special handling", "No override flag exists for this, on purpose", "not
    built here", "The floor, always on, not configurable", "Why nothing
    defaults on for `revision`", and "They are not counted as unchanged
    either" all survive. No warning was softened, and the page's deliberate
    non-goals (the parked git-history layer, zero git object reads) are intact.
  R6 cross-page consistency. No term was renamed, so no neighbour can have
    drifted. `docs/index.md` was not touched.

WHAT I DID NOT DO, DELIBERATELY.
  - Did not resolve F1, did not run `refdes keys adopt`, and did not edit
    AGENTS.md.
  - Did not narrow the two loose claims named above.
  - Did not rewrite the ~20 paragraphs that already read like the benchmark,
    including four Edge-case entries and both "**Why ...**" rationales.
  - Did not touch the 8-row gate table, any of the 6 fenced blocks, any
    heading, any link, or `docs/index.md`.
  - Did not normalise the page's mixed em-dash / `--` punctuation, nor fix the
    one pre-existing 81-char prose line at :284 (it was :269 in HEAD, byte
    identical). Both are consistency decisions for a reviewer, like the
    pilot's H8 `**Remedy:**` question — and this page has a third such
    question, since `keys adopt` is described in the present tense here and in
    four other pages.
  - Did not run `ruff` — no Python was changed, and AGENTS.md records that
    `ruff check .` is not a clean baseline and is not a valid gate.
  - Did not add a test. The guarantee here is the harness plus the existing
    docs gates; a test asserting my own prose would be the wrong shape. And
    `grep -rln "lifecycle.md" tests/` returns nothing, so no test asserts
    against this page today.
  - Did not re-run the CLI after the edit. No fence changed (A2) and no claim
    changed, so the page's described behaviour is identical; STEP 3's
    source-reading and help-output checks are the evidence.

FOLLOW-UPS FOR THE ORCHESTRATOR (not done here).
  1. Reconcile F1 (`refdes keys adopt`) in a factual pass. This page plus
     `cmd_keys_adopt`'s real per-entry report is the strongest evidence yet,
     and it is still not an execution. See DISPUTES above.
  2. Adopt `.scratch/doccheck.py` as the standing A2-A7 harness. All three
     traps I hit are in the getting-started pass's follow-up #4 already, and I
     can now add a third: a heading scanner must exclude fence lines or it
     counts YAML comments as headings (9 vs 14 on this page).
  3. Correct plan §2/§7's fence accounting for this page the same way the
     getting-started pass asked for its own: 6 blocks, not the "12" quoted
     above (12 is the count of ``` lines). The same error is in the plan for
     getting-started.md (30 vs 14) and troubleshooting.md (2 vs 1), so it is
     systematic across the whole Tier 2 queue and every remaining worker will
     inherit it.
  4. The plan's Tier 2 ordering rested on counts (plan §11 U2/U3) and those
    counts were a poor proxy for getting-started.md. On THIS page they
    happened to be right, so the queue's premise is neither confirmed nor
    refuted — keep reading before queueing coverage.md / change-tracking.md /
    design-log.md rather than trusting the numbers.
  5. Two unfixed prose lines here are one-line fixes if a reviewer wants them:
     the `stale_arithmetic` overclaim at :76, and the unverified negative
     claim about working-tree cleanliness.
