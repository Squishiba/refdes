Task: apply the humanizing treatment to `docs/coverage.md` — plan §7 Tier 2
item 5 (`/home/jorb/work/refdes/.scratch/docs-humanizing-plan.txt` §7 line 247:
"5. docs/coverage.md (341/2477w, 18 fences)"). Full-page pass.
Role: delegated worker. Single-file edit.
Started: 2026-09-27
Status: FINISHED — page edited (13 changed regions, 70 insertions / 58
deletions, all prose), all acceptance checks pass, changelog fragment added.

Plan location: the plan file is gitignored and per-worktree, so it is absent
here. Read read-only from the primary checkout:
  /home/jorb/work/refdes/.scratch/docs-humanizing-plan.txt      (404 lines)
Rubric source: plan §6 (P1-P7, H1-H8), acceptance checks plan §8 (A1-A9).
All three prior passes' logs were read in full for the established pattern:
  in-prog-logs/docs-humanize-troubleshooting-pilot.md   (PR #65, 319a79e)
  in-prog-logs/docs-humanize-getting-started.md         (PR #70, 72a34fc)
  in-prog-logs/docs-humanize-lifecycle.md               (PR #73, 36eea7c)
The lifecycle log is the one I leaned on hardest, for the reason the task
brief says. Per AGENTS.md I wrote nothing outside this working directory.

Files changed by me (this is the complete change set):
  M docs/coverage.md
  A changelog.d/docs-coverage-prose.fixed.md
  A in-prog-logs/docs-humanize-coverage.md                  (this file)
Scratch (gitignored, left in place per AGENTS.md): `.scratch/doccheck.py`,
`.scratch/coverage.HEAD.md`, `.scratch/cv-before/`, `.scratch/cv-after/`,
`.scratch/lifecycle-pre.md`, `.scratch/lifecycle-post.md`,
`.scratch/gs-post/`, `.scratch/lc-pre/`, `.scratch/lc-post/`,
`.scratch/co-ref/`, and the throwaway projects `.scratch/cvproj`,
`.scratch/cvproj2`, `.scratch/cvp3`, `.scratch/cvp4`, `.scratch/cvext`,
`.scratch/cvext2`.

STEP 0 — ownership check. DONE, BEFORE editing.
  `git status` -> "On branch towering-wolf / nothing to commit, working tree
  clean".
  `git diff -- docs/coverage.md` -> empty (exit 0, no output).
  So no other session owned this page, and the whole tree was clean. Nothing
  was staged, stashed, reset, or cleaned at any point in this task.

STEP 1 — harness, and the four traps are not all hypothetical here.
  `.scratch/doccheck.py {extract,compare,census}`. The lifecycle pass's copy
  did not survive into this worktree either, so I rebuilt it from the logs and
  VALIDATED it against the four independent published counts before trusting
  it:

    file                                    published             my harness
    docs/lifecycle.md (pre-edit, 36eea7c^)   135 spans/6 blk/9 hdgs  135/6/9  match
    docs/lifecycle.md (post-edit, 36eea7c)   135 spans/6 blk/9 hdgs  135/6/9  match
    docs/getting-started.md (post, PR #70)    46 spans/14 blk/10 hdg  46/14/10 match
    docs/concepts.md                          45 spans/1 blk (Table) 45/1  match

  Note the third row is the one the lifecycle log explicitly re-derived rather
  than inherited: the getting-started pass's claim that the wrapped-span trap
  fires on getting-started.md does NOT reproduce there, and my harness agrees
  with the correction (46 = 46, naive = CommonMark on that file). I did not
  repeat the earlier claim.

  THE FOUR TRAPS, AND WHICH ONES ARE REAL ON THIS PAGE:

  (i) ``` fences counted as LINES not BLOCKS. The plan's "18 fences" for
      coverage.md is a ```-line count. The file has 9 real fenced blocks.
      This is the SAME systematic error the lifecycle pass flagged for its own
      page (6 blocks, not 12), getting-started (14, not 30) and
      troubleshooting (1, not 2). It is in the plan for every remaining Tier
      2/3/4 item, so every worker after this one will inherit it. Real here:
      18 vs 9.
  (ii) A line-local regex `` `([^`\n]+)` `` misses spans whose delimiters
      straddle a line break. Real here, though only just: 164 spans vs the
      naive 162. The two wrapped spans are
        :29    `status:` / `on_hold`  (a bullet in "Why several and not one")
        :99-100 `test.links.verifies:` / `[requirement, bound]`
      The second one matters: it sits INSIDE the 139-word paragraph I rewrote
      hardest, so a naive A3 on this page would have been blind to the single
      most fragile span in the edit.
  (iii) A heading scanner that does not skip fenced regions counts YAML
      comments as headings. NOT real on this page — I checked, and coverage.md
      has no `#`-comment line inside any of its 9 fences (`grep -n '^\s*#'`
      returns only the 14 real headings). The exclusion is in the harness
      anyway and is what makes it reproduce lifecycle.md's 9 rather than 14.
  (iv) Comparing fence/heading LINE NUMBERS across a reflow. Real by
      construction: my edit adds 12 lines, so ALL 9 blocks shift. Designed
      out — A2 compares body + info string and reports shifts as INFO.

  HARNESS BUG I HIT AND FIXED (a fifth, in the same family, and it produced a
  wrong number first): `extract()` built the prose stream by DELETING fence
      lines, so every code span's reported `line` was numbered against the
      fence-stripped text, not the file. On this page that put the two
      wrapped spans at :29 and :99 when :99 was right and :29 was not far off
      only by luck. It also produced a nonsense "spans inside a fence: 25"
      figure. Fixed by replacing each fence line with a NUL sentinel instead
      of removing it, which keeps every later line number equal to its real
      line number and simultaneously makes a span that would bridge a fence
      detectable (CommonMark forbids a code span crossing a block boundary).
      Re-validated: all four published counts above still match, and the two
      wrapped spans' line numbers were then hand-checked against
      `sed -n '29p;30p;99p;100p'` — they are right.

STEP 2 — the go/no-go, re-measured. VERDICT: GO. The page really is below
  the `docs/concepts.md` bar, and the brief's "possibly-inaccurate 2477 words"
  is accurate: `wc -l -w docs/coverage.md` -> 341 2477, unchanged.

                              coverage.md      concepts.md (benchmark)
    lines / wc -w words      341 / 2477w       117 / 875w
    real fenced blocks       9  (18 ``` lines) 1  (2 ``` lines)
    prose paragraphs         41                 18
    prose words              1776               590
    longest paragraph        139 w (:91)        51 w (:33)
    longest sentence         64 w (in :91)      39 w (:106)
    paragraphs w/ >=40w sentence  7            0
    paragraphs > 51w         14                 0

  So the worst paragraph is 2.7x the benchmark's largest and the worst
  sentence 1.6x its longest. Unlike getting-started.md (where the pass before
  last found the page already at the bar) this page is genuinely below it —
  the counts and the reading agree, as they did for lifecycle.md and did not
  for getting-started.md.

  A CENSUS CAVEAT I should state rather than hide: 4 of the 41 "prose
  paragraphs" are bullet continuations (`:29`, `:33`, `:36`, `:47`), not real
  paragraphs — an indented wrapped line of a list item. Their SENTENCE counts
  are valid and I fixed the one real defect among them (a 46w semicolon-spliced
  sentence in the `coverable:` bullet at :46-51); their paragraph totals are
  not meaningful. 37 genuine prose paragraphs is the honest denominator.

STEP 3 — claims re-verified BEFORE rephrasing (P6/P7). This page has no
  feature-status dispute on it: `grep -n adopt docs/coverage.md` -> no match,
  before or after, so the plan's §10 F1 (`refdes keys adopt`) does NOT touch
  this page and there was no disputed sentence to freeze. Everything with an
  observable consequence was checked against source or by execution, and
  every claim I rephrased around was checked first.

  CLI verified against THIS checkout first:
    PYTHONPATH=$PWD/src /tmp/pypdf4/bin/python3 -c "import refdes; print(refdes.__file__)"
    -> /home/jorb/.paseo/worktrees/16msma8v/towering-wolf/src/refdes/__init__.py
  Caveat carried forward and NOT resolved: third-party deps come from another
  worktree's venv (/tmp/pypdf4). I installed nothing.

  VERIFIED AGAINST SOURCE:
  - "The stage shown is the highest reached." and the whole ladder, plus "a
    requirement can be verified without any log entry ever mentioning it" —
    `model.py:637-646` returns `verified` first, so an item with no
    `addressed_by` can still be `verified`. Both halves of :16-18 hold.
  - "`claimed` only appears for types that declare `satisfying_statuses:`" and
    "A type that doesn't declare it never produces a `claimed` requirement" —
    `build.py:780-781` claims only when `allowed is not None and status not in
    allowed`, so an unconfigured type settles every link.
  - `coverable_statuses:` — `build.py:629-633` (`_excluded_by_status`'s own
    docstring) says the page's two sentences almost word for word: "Unset:
    falls back to excluding `status == "retired"` if a status field exists ...
    Set: inclusion list".
  - Only the three backlinks feed coverage — `build.py:761-803` reads
    `addressed_by` / `satisfied_by` / `verified_by` and nothing else, and the
    bundled standard's own header comment (`v3/base.yaml:33-36`) says so and
    cites this page by name. The page's "checked, not assumed" is earned.
  - The symmetric `verified_by` read, `build._verifier_type_names` — verified,
    and that function's docstring (`build.py:582-592`) states the page's
    legacy-spelling claim in its own words ("the legacy convention: a
    requirement declaring `verified_by: [test]`"), which is why I was free to
    reword around the sentence I broke up.
  - "`test.links.verifies: [requirement, bound]` is always the spelling in
    `base.yaml`" — VERIFIED, `v3/base.yaml:254`, and the bundled standard
    never authors a `verified_by:` anywhere (`grep verified_by base.yaml` finds
    only the inverse declaration at `:163` and a prose comment at `:33`).
  - "Imported items are excluded regardless" — `build.py:911` iterates
    `project.local_items`.
  - "Declaring `satisfying_statuses:` requires the type to have a `status`
    field; the project fails to load otherwise" — `schema.py:640-642` raises
    `SchemaError`.
  - The three quoted summary lines — `build.py:973` (`N item(s) with no
    coverage — see coverage.html`), `:977` (`N requirement(s) satisfied but not
    verified`), `:985` (`N requirement(s) unsettled because <root> is
    <status> — see coverage.html`; the " is on_hold" shape is
    `status_text = f" is {status}"` at `:983`). All three verbatim.
  - The per-item `claimed but not verified (no test links to it)` warning and
    the `claimed by <id>, which is blocked_by A <- B (<status>)` chain the page
    quotes — `build.py:959-966`. Both match, including the ` <- ` join.
  - "Deliberately conservative: ... traces to **exactly one** root" — the
    `unsettled_by_root` comment at `build.py:909-912` and the `< 1` guard.
  - The `coverage.html` table header, the page's table row for it —
    `src/refdes/templates/coverage.html.j2:40-41` is
    `ID | Title | Stage | Addressed by | Claimed by | Satisfied by | Verified by`,
    exactly the page's :112 header, in that order.
  - `not yet satisfied on boards: board-b` — `coverage.html.j2:48`, exact
    string. `<h2>Conforming contracts` — `coverage.html.j2:78`. The per-board
    page name `coverage-<board>.html` — `render.py:1137`.
  - `coverage.group_inherited` defaults to true — `configcheck.py:252`
    (`block.get("group_inherited", True)`), read at `blocks.py:250`. So
    "show subtype items under the parent unless ... is `false`" is right.
  - `-v`/`--verbose` is on `check` AND `build` and nothing else relevant —
    `cli.py:1420` (p_build) and `cli.py:1457` (p_check), both with the help
    "also show info-level diagnostics (routine states hidden by default)".
  - The token/prefix lint warning the page quotes — `boards.py:189`
    (`f"id prefix {prefix!r} does not contain that token"`).

  VERIFIED BY EXECUTION (the `stub-tests` section, run end to end in
  `.scratch/cvp4`):
  - "writes a starter test for every coverable item with no verifying test
    yet, `verifies:` already pointing at it" — ran it; the generated file
    carries `type: test / title: Verify <REQ> / status: planned /
    verifies: [<REQ>]` per item.
  - "one multi-item markdown file per board (or workspace), not one file per
    item" — three requirements, three stubs, ONE `items/stub-tests.md`.
  - "an item that already has a test (`planned` or otherwise, allocated an id
    or not) is skipped" — tested all four cases: an existing `planned`, then
    `failing`, then `passing` test each skipped the target; and a test with NO
    id yet also skipped it. This is `_already_covered`
    (`stub_tests.py:34-63`), whose docstring explains the pending case is the
    two-phase author-then-allocate flow.
  - "so running it again after adding new requirements is safe and only ever
    adds what's newly missing" and "A prior run's file is appended to, never
    overwritten" — re-ran after `refdes id`: "no coverable item is missing a
    verifying test", the file still had exactly its 3 stubs. The append is
    structural, not incidental: `open(target, "ab")` at `stub_tests.py:165`.
  - The page's load-bearing caveat at :296-302, "Coverage stays exactly as
    honest immediately after a `stub-tests` run as it was the moment before" —
    DEMONSTRATED, not just read: after the full `stub-tests` + `refdes id`
    round trip, all three requirements were still `stage: open` with
    `verified_by: []`. A generated stub does not retroactively verify its
    target, because `status: planned` is not in `verifying_statuses: [passing]`.
    This is the strongest single check on the page and it passed.
  - The page's own bash block (`refdes stub-tests` then `refdes id`) is what I
    ran; `refdes id` printed "allocated 3 id(s)".

  NOT VERIFIED, AND NOT ASSERTED:
  - I did not build a multi-board project, so the page's per-board
    `conforms_to:` paragraph (:129-137) is verified by source and by the
    `Conforming contracts` / `not yet satisfied on boards` strings, NOT by
    execution. Its wording and its claims are untouched in strength.
  - I did not run `refdes build` against a project that produces a
    `blocked_by` cascade warning, so the quoted chain warning at :180-184 is
    verified against `build.py:959-966` only.

STEP 4 — the rewrite. DONE. Rubric P1-P7 / H1-H8 (plan §6). 13 changed
  regions at `-U0`, 70 insertions / 58 deletions, all prose.
  - :91-104, the 139-word paragraph — the dominant defect on the page, 2.7x
    the benchmark. Its 64-word sentence held a colon-introduced aside and a
    "to support X" purpose clause welded to the mechanism it explains. Now two
    paragraphs: the flag and the legacy spelling, then what the bundled
    standard does about it. Longest sentence 64w -> 31w.
  - :71-79 (75w) — the "Deliberate convention" em-dash splice between the
    active-voice rule and the computation split at the dash into two
    sentences.
  - :81-89 (84w) — split into two paragraphs at the rule/example seam, the
    "If what you're authoring is" throat-clear dropped (H1), and the semicolon
    splice between the no-link case and `satisfies` broken.
  - :119-122 — a 42-word colon-spliced sentence about the **Claimed by**
    column became three short ones.
  - :129-137 (94w) — "Coverage per board" became three paragraphs, splitting a
    43-word sentence that carried three facts (recomputed stages, the
    per-board page, the inline note) behind one colon.
  - :141-144 — a 49-word sentence with an em-dash aside became three.
  - :46-51 — the `coverable: true` bullet's 46-word semicolon splice (two
    independent claims) became two sentences.
  - :169-173 — semicolon splice after "that's `info`" broken.
  - :194-201 (83w) — split at the "where to see it" seam.
  - :254-259 (67w) — the `planned`/`failing` vs `passing` contrast split into
    two paragraphs, semicolon splice broken.
  - :288-294 (80w) — a 44-word sentence carrying the dedup rule AND its safety
    consequence split into two; the paragraph split at the same seam.
  - :296-302 — the 43-word caveat sentence split, and its second half joined
    with "and" so both claims survive in one breath.
  - :318-324 (67w) — semicolon splice between the "one test, many
    requirements" pair broken; paragraph split at "The generated ... file".

  Deliberately NOT done (R3, "over-editing into blandness"):
  - The two stage tables, the five-stages table, the "Closing the gaps" table
    and the per-board table row are untouched, as are all 9 fenced blocks and
    all 14 headings. `grep` over the diff for any line starting `|`, ``` or
    `#` returns nothing: no table row, no fence line, no heading is even in the
    diff.
  - :16-18, :20-23, :27, :42-44, :52-57 (the `coverable_statuses:` bullet — max
    sentence 28w), :59-64, :108, :124, :151-154, :156, :165, :177, :186, :205,
    :222, :227-231, :240, :275, :279, :303, :314, :340 all left
    byte-identical. Several of those are already at or near the benchmark.
  - I specifically considered and rejected splitting :227-231 (52w, four
    sentences of 16/13/14/9 words) — the only available break left a 9-word
    orphan paragraph, and 52w is within a word of the benchmark.
  - No `**Remedy:**`-style convention invented (H8 — this page has none, and
    still has none), and the page's own bolded lead-ins ("**Claimed by** is
    its own column", "**The prerequisite is ...**", "**Refdes does not own
    test items once they're written.**") are all kept as lead-ins.
  - Every added line is <= 78 columns. The 23 prose/table lines over 78 columns
    are all pre-existing (25 before, 23 after) and none of them is a line I
    wrote.

ACCEPTANCE CHECKS (plan §8) — my own results, re-runnable by a reviewer.
  Harness: `.scratch/doccheck.py {extract,compare,census}`. Baseline is
  `git show HEAD:docs/coverage.md` in `.scratch/coverage.HEAD.md`; "after" is
  the working tree. Reproduce:
    python3 .scratch/doccheck.py extract .scratch/coverage.HEAD.md .scratch/cv-before
    python3 .scratch/doccheck.py extract docs/coverage.md .scratch/cv-after
    python3 .scratch/doccheck.py compare .scratch/cv-before .scratch/cv-after
  System python3 3.13.5 is enough for the harness (stdlib only); the gates in
  A8 need the borrowed interpreter.

  A1 Scoped diff and ownership. PASS.
    `git status` before editing: "nothing to commit, working tree clean";
    `git diff -- docs/coverage.md`: empty. Ownership confirmed clean BEFORE
    any edit (STEP 0). Nothing was staged, stashed, reset, or cleaned at any
    point. `git diff --stat -- docs/coverage.md` -> 1 file, 70 insertions(+),
    58 deletions(-), 13 hunks at -U0, and every hunk is prose.
  A2 Fenced-block byte equality. PASS. 9 blocks before, 9 after, 0 differing
    bodies, info strings unchanged (`'' x4`, `yaml`, `yaml`, `bash`, `''`,
    `json`). The edit adds 12 lines, so all 9 blocks shift position; the
    harness reports that as INFO and compares bodies, per trap (iv).
  A3 Inline code-span multiset. PASS. 164 spans before, 164 after (the
    CommonMark count); sorted multiset byte-identical, so no span was added,
    dropped, renamed, or reworded. 0 spans counted inside any fence on either
    side. NOTE for a reviewer who re-implements this naively: the naive
    line-local regex reports 162 before and 163 after, because the
    `test.links.verifies: [requirement, bound]` span stopped straddling a line
    break when I rewrapped it. Its normalized content is unchanged and it
    matches — A3 passes. A naive harness would report a spurious 162-vs-163
    mismatch here, and on the "before" side it would not have been checking
    that span at all.
  A4 Link/anchor preservation. PASS. 16 `](...)` targets before and after,
    byte-identical; 0 reference definitions. Anchor resolution with a
    GitHub-slug resolver over the real heading set of each target file: 16 of
    16 resolve, 0 dead. This page has none of the pilot's DISPUTE 2-style
    broken anchor. (My first resolver reported 12 dead anchors including
    same-page `#the-five-stages`; the resolver was wrong, not the docs — it was
    not skipping fenced regions and its trailing-`\s*$` spanned lines. Fixed
    and re-run before I believed either number.)
  A5 Heading set/order. PASS. 14 headings, text and order identical, 0 added,
    0 removed.
  A6 No new identifiers. PASS. 76 unique span contents before and after,
    set-equal; added=[] and removed=[]. Every identifier in the new prose was
    already on the page.
  A7 Word count. PASS. 2477 -> 2465, -0.5%, budget +/-15%. Prose-only
    paragraph count 41 -> 49 and prose words 1776 -> 1764, so nothing was
    gutted and nothing was padded: the word count fell slightly while the
    paragraph count rose, which is what splitting should look like.
  A8 Repo gates. PASS.
    `pytest tests/test_docs_examples.py tests/test_vocabulary_page.py
     tests/test_themes_page.py -q` -> 35 passed in 2.01s.
    `python docs-site/gen_examples.py --check` -> "docs/schema-reference.md is
    up to date." / "docs/vocabulary.md is up to date.", exit 0.
    `pytest tests/test_pages.py -q` -> 9 passed. (It is the only test that
    mentions `coverage.md`, and it is about a PROJECT's `pages/coverage.md`
    shadowing the coverage report, not about this page's prose or nav.)
  A9 Spot-verify rephrased claims. DONE, thoroughly — see STEP 3, which
    verified every claim carrying an observable consequence before I reworded
    around it, and executed the whole `stub-tests` walkthrough. Per the plan's
    "not a full audit" limit I did not audit the 9 fenced blocks' internal
    claims: A2 proves they are byte-identical to HEAD and I changed no byte
    inside them. The one quoted `WARNING` block I did re-check against source
    anyway (build.py:973/977/985), because it is quoted output a reader will
    pattern-match against.

BEFORE / AFTER, worst case (the measurement the brief asked for).

                        before       after     concepts.md (benchmark)
  longest paragraph     139 w (:91)  77 w (:91)   51 w (:33)
  longest sentence      64 w (:91)   38 w (:47)   39 w (:106)
  prose paragraphs      41           49          18
  prose words           1776         1764        590
  paragraphs w/ >=40w sentence  7   0           0
  paragraphs > 51w      14           9           0
  lines / wc -w words   341 / 2477   353 / 2465  117 / 875
  real fenced blocks    9            9           1

  Honest reading of those numbers, rather than a victory lap:
  - Longest sentence 64w -> 38w, which puts the page's worst sentence just
    UNDER the benchmark's worst (38 vs 39). That is a real pass, and all seven
    paragraphs that had a 40w-or-longer sentence are fixed, not shaved to just
    under the line.
  - Longest paragraph 139w -> 77w, a 1.8x cut and no longer 2.7x the
    benchmark — but 77w is still ABOVE the benchmark's 51w, so like
    lifecycle.md's paragraph metric this one does not clear the bar. I stopped
    there on purpose: the remaining 77w paragraph is four sentences of
    14w/18w/31w/14w (claim, capability, mechanism, consequence) and splitting
    it would sever one explanation. All 9 remaining over-51w paragraphs have a
    longest sentence between 16w and 36w, i.e. every one of them is below the
    benchmark's worst sentence. Paragraph count was not the defect; sentence
    shape was, exactly as the lifecycle pass concluded.
  - `concepts.md` was NOT edited and remains the read-only benchmark (plan
    §7 Tier 0). Measured, never touched.

DISPUTES / NUANCES — REPORTED, NOT RESOLVED. No feature-status dispute was
  found on this page, and no stale or wrong claim. That is worth stating
  plainly, because the plan's §10 F1/F2/F3 all live on OTHER pages
  (troubleshooting.md). Three things I found and deliberately did not touch:

  NUANCE 1 — the `coverable:` fallback warning carries a deprecation the page
    does not mention. `_resolve_coverable` (`build.py:618-622`) emits "Add
    'coverable: true' explicitly -- this fallback is removed in refdes 1.0".
    The page says only "with a one-time warning". Not wrong, and the "one-time"
    part is verified (`spec.name not in warned` guards it), but a reader is not
    told the fallback is going away. P6: report, do not add. Out of bounds for
    a humanizing pass — it is a new fact.
  NUANCE 2 — on that same fallback path, per-item coverage warnings go only to
    items literally named `requirement` (`build.py:932-936`, which calls it a
    compatibility asymmetry). The page describes the fallback as making
    `requirement`/`constraint` coverable and says nothing about which of the
    two get warnings. Again a silence, not an error. Untouched.
  NUANCE 3 — the page's `stub-tests` section does not mention `--dry-run`,
    which `refdes stub-tests --help` documents ("show what would be written
    without writing"). An omission in a section that lists the command's
    behaviour. I did not add it: introducing a flag the page does not
    currently claim is a new factual claim, and the plan puts new CLI flags out
    of bounds for this pass.

  My own two WRONG RESULTS this session, recorded because each one nearly
  became a false finding in this log:
  - I concluded the page's "allocated an id or not" dedup claim was FALSE,
    because a test run wrote a stub for a requirement that already had a
    test. The run was invalid: I had corrupted the test item file myself (a
    stray `id:` line above the `---`, left over from a botched edit in an
    earlier probe, plus a `key:` and a composite `REQ-PWR-001@nx850w78b5h`
    target a prior run had written back), so the project reported "no YAML
    front-matter" and the item never loaded. A clean rerun in a fresh project
    (`.scratch/cvp3`) printed "no coverable item is missing a verifying test"
    and the claim is TRUE. Had I not re-run it, this log would have carried a
    confident, wrong "the docs are wrong" finding.
  - I read "3 items, 3 errors" from a freshly generated stub file as a
    generator bug (the file looked malformed). The errors are `item has no id
    -- run 'refdes id' to allocate one`, i.e. the documented two-phase flow;
    after `refdes id` the same file loads clean at 6 items, 0 errors. No bug.

SELF-REVIEW AGAINST THE PLAN'S §9 R TARGETS (for the reviewer, not a
substitute).
  R1 meaning survived. The riskiest rewrites were the two in "Which links feed
    coverage", because that section is a chain of reasons and the
    feature-status-adjacent claim ("checked, not assumed") sits at the top of
    it. Every one of the nine link names (`satisfies`, `verifies`,
    `addresses`, `satisfied_by`, `verified_by`, `addressed_by`,
    `constrained_by`, `governed_by`, `blocked_by`, `constrains`, `governs`,
    `blocks`, `..._by`, `X_by`) survives as a code span, and A6 proves the
    unique-span set is unchanged, so none was dropped or renamed. The one
    deliberate condensation is the "Deliberately conservative" sentence's
    em-dash aside, which became its own sentence with both clauses intact.
  R2 status wording preserved, nothing to surface. The page carries no
    landed/design-only statement about an unbuilt feature; the nearest thing is
    the "deliberately not one of `verifying_statuses:`" design intent, which
    is stated at the same strength and is now backed by the round-trip run in
    STEP 3.
  R3 voice. The page's genuinely good human lines are byte-identical, and I
    want to name them so a reviewer knows they were seen and spared: "A
    decision that hasn't settled is a claim, not a fact yet." "The name is the
    signal: if you're authoring a link to make something count as done, reach
    for the active form." "a misleading one-line summary would be worse than
    not summarizing it." "Read `items.json`, never scrape the HTML." "it is
    much cheaper to fix beforehand than after." I did not flatten the page into
    a uniform register, and I added no structure the page lacked.
  R4 claims untouched. Zero facts changed. A6 proves no identifier was added,
    dropped, or renamed; A3 proves the code-span multiset is identical; A2
    proves all 9 fenced blocks are byte-identical, and that is where this
    page's quoted tool output lives.
  R5 warnings and caveats present. "Deliberate convention, not an accident of
    naming", "never a `claimed` requirement", "exactly like before this
    existed", "the original behavior", "not just \"open\"", "Imported items are
    excluded regardless", "**`constrained_by` does not feed coverage**,
    however strongly the name suggests otherwise", "Deliberately
    conservative", "**exactly one**", "a misleading one-line summary would be
    worse than not summarizing it", "These are warnings, not errors", "the
    moment the first one is added, these become real findings again", "so a
    fresh stub never retroactively marks its target `verified`", "Coverage
    stays exactly as honest", "**Refdes does not own test items once they're
    written.**", "an id is frozen once allocated", "never scrape the HTML" —
    all survive at original strength. No warning was softened, and the two
    hedges the plan singles out ("checked, not assumed", "it is a
    standard-library authoring choice, not a rule the schema engine itself
    enforces") are both still there and still point the same way.
  R6 cross-page consistency. No term was renamed, so no neighbour can have
    drifted. `docs/index.md` was not touched.

WHAT I DID NOT DO, DELIBERATELY.
  - Did not resolve NUANCE 1, 2, or 3, and did not add `--dry-run`, the 1.0
    removal note, or the fallback asymmetry note to make them go away.
  - Did not run `refdes keys adopt`; the page does not mention it.
  - Did not touch the 9 fenced blocks, including the four quoted WARNING
    blocks and the `items.json` export — all byte-identical, all correct as
    they stand (the three summary lines re-verified against source anyway).
  - Did not touch any of the 4 tables, any of the 14 headings, any of the 16
    link targets, or any other page.
  - Did not edit `docs/concepts.md`. It stayed the read-only benchmark.
  - Did not normalise the page's mixed em-dash / `--` punctuation, and did not
    rewrap the 23 pre-existing lines over 78 columns. Both are consistency
    decisions for a reviewer.
  - Did not run `ruff` — no Python was changed, and AGENTS.md records that
    `ruff check .` is not a clean baseline and is not a valid gate.
  - Did not add a test. The guarantee here is the harness plus the existing
    docs gates; a test asserting my own prose would be the wrong shape, and
    the only test that names `coverage.md` is about a different file entirely.
  - Did not build a multi-board project, so the per-board paragraph is
    source-verified but not execution-verified (STEP 3).

FOLLOW-UPS FOR THE ORCHESTRATOR (not done here).
  1. NUANCE 1-3 above are candidates for a factual pass on this page, not for
     a humanizing one. NUANCE 1 (the fallback "removed in refdes 1.0") is the
     one with a real reader consequence.
  2. Plan §2/§7's fence accounting is wrong for this page the same way it is
     wrong for every other page measured so far: 9 blocks, not the "18"
     quoted above (18 is the ```-line count). The lifecycle pass already
     found this systematic across the Tier 2 queue (12->6, 30->14, 2->1);
     coverage.md is the fifth instance. Correct it in the plan before
     queueing change-tracking.md / design-log.md, or every remaining worker
     will inherit it.
  3. The prior passes' PARAGRAPH and SENTENCE word metrics are not
     independently reproducible, and mine differ from them slightly. On
     lifecycle.md's pre-edit file I measure the famous 226w paragraph as 232w
     and its famous 103w sentence as 104w, and 1673 prose words against the
     logged 1684; on getting-started.md I measure 27 prose paragraphs / 498
     words against the logged 23 / 517. Their STRUCTURAL counts (spans,
     blocks, headings) I reproduce exactly. The prior harness did not survive
     into either worktree, and the lifecycle log says it validated its
     reconstruction only against the structural counts. I am not claiming the
     prior numbers are wrong — only that nobody can currently re-derive them,
     so a reviewer should treat any prose-shape number in these logs as
     "measured by a harness that no longer exists". Worth pinning down in
     `.scratch/doccheck.py` for the remaining queue.
  4. Adopt `.scratch/doccheck.py` as the standing A2-A7 harness. Five traps
     are now documented in its own docstring: fence lines vs blocks, wrapped
     code spans, headings inside fences, line numbers vs contents, and the
     fence-stripping that silently renumbers lines. Traps 1 and 2 both fire on
     this page; trap 3 does not, but it fires on lifecycle.md.
