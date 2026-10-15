# SCHEMA-VALID-009 — SourceText.render() drops an untouched CRLF terminator on duplicate lines

Task: verify + (if reachable) fix the finding that `SourceText(...).render()`
after an insertion among duplicate lines emits a `delete` opcode that drops an
untouched CRLF line, violating the byte-preservation contract in
`src/refdes/textio.py:18-22` ("only the lines an edit actually touched
changing").

Branch: `fix/source-text-crlf-delete-20261015`, pinned at main
`7e49a204f4745ca0956742d5ce95a21944bc5ab6` (verified `git rev-parse HEAD` ==
`origin/main`; tree clean at start and at every write below except this log).
Src was NOT modified: the finding is reproduced and root-caused, but is
unreachable from any CLI writer on this code, so per the task rule the result
is evidence + a reviewable design, not an asserted fix.

## Reproduction (REPRODUCED on current main)

Probe: `.scratch/probe_009_textio_delete_crlf.py` (shared main's copy of the
probe was an empty file, so it was reconstructed verbatim from the TSV row
009 description — same fixture, same insertion, same expected opcodes):

    text = "  - id: REQ-001\n  - id: REQ-001\n  - id: REQ-001\r\n"
    lines = SourceText(text).lines
    lines[1:1] = ["    NEW", "    NEW"]
    SourceText(text).render(lines)

Output on 7e49a20:

    '  - id: REQ-001\n    NEW\n    NEW\n  - id: REQ-001\n  - id: REQ-001\n'

The third line — untouched, and the file's only CRLF line — comes back with
LF. Opcodes match the baseline exactly:
`[insert(0,0,0,3), equal(0,2,3,5), delete(2,3,5,5)]`.

## Root cause

`render()` (textio.py:149-183) aligns the edited line list against the
original with `difflib.SequenceMatcher(autojunk=False)`. Content-only
alignment over repeated lines is *ambiguous*: in the probe, two windows of
the same maximal length exist — `a[0:2]↔b[3:5]` and `a[1:3]↔b[3:5]` — and
`find_longest_match` tie-breaks to the smallest `i`
(`Match(a=0, b=3, size=2)` verified in-process). The left-shifted window
pairs the two surviving copies with the two LF originals, and the CRLF
original falls into a spurious `delete`, whose handler (`if tag == "delete":
continue`, textio.py:170-171) discards its terminator. The delete handler is
not the defect — the alignment placed the line there.

The same tie-break bites length-preserving edits too (audit script case 4):

    SourceText("  - A\n  - A\n  - A\r\n").render(["  - B", "  - A", "  - A"])
    # -> "  - B\n  - A\n  - A\n"   (tail CRLF lost; opcodes are
    #    insert(0,0,0,1) + equal(0,2,1,3) + delete(2,3,3,3))

i.e. rewriting copy 0 of a run of 3 identical lines loses the run's CRLF
tail. So the exposure is not insertions only.

## Trigger characterization

The byte loss requires the alignment to be ambiguous about which copy of a
contiguous run of ≥2 identical bare lines each survivor is, AND a CRLF
inside the run at a position the winning window does not pair. Concretely,
one of:

- T1: a pure insertion strictly inside a run of ≥3 identical lines (the
  probe shape),
- T2: a *positional* rewrite of a strict prefix/suffix subset of an
  identical run (leaving identical survivors),
- T3: a positional deletion of ≥1 line from a run of ≥2 identical lines
  (the remaining lines' pairing slides).

## Caller audit — reachability from the CLI

Every `SourceText.render()` caller in `src/` (grep of `SourceText` —
the list is exhaustive):

| site | CLI path | edit geometry | trigger? |
|---|---|---|---|
| ids.py:665 (`ids.allocate`) | `refdes id` | `insert_into_list` (ids.py:481) rewrites the item's own first line 1→2 (`- title:` → `- id: …` + re-indented `  title:`) — content of the pushed line changes; `insert_into_markdown` (ids.py:412) pure-inserts **above the first key line** (boundary: the line above is `---`/front-matter start), or replaces a key line 1→1 by content match | no |
| keys.py:727 (`plan_mint`, incl. load-time `mint_missing`) | every writing `refdes` command | same two helpers, same geometry | no |
| former_ids.py:239 (`confirm`) | `refdes former-ids confirm` | same two helpers | no |
| links.py (4 plan sites, e.g. 658) | link/check/calc expansion | `_rewrite_item_links`/`_rewrite_link_field` (174, 256) replace the *matching* line in place; identical lines all match identically, so rewrites are uniform over a run → one `replace` block whose offset rule (textio.py:175-177) hands every original its own ending | no |
| links.py `_dedupe_follows_field` (210, via 670) | follows expansion/anchor | blanks the duplicate row **in place** (`out[j] = ""`, line 250; docstring: "becomes blank instead of shifting later source positions") — length-preserving, T3 never fires | no |
| calc_rewrite.py:104 | `refdes calc-rewrite` | in-place `out[i] = rewrite_line(line)` for every matching line — uniform over identical lines | no |
| revise.py:1038, 2089, 2105 | `refdes rename` / `standard upgrade` | in-place line substitutions | no |
| image_freeze.py:177 | load-time `freeze_images` (loader.py:177) | `lines[first:last] = after.split("\n")` span replace; `_freeze_span` substitutes src substrings containing no newlines, so line count (and newline count) is preserved — content changes, in-place | no |
| serve/editor | browser editor | appends at EOF via `textio.append_ending` (serve/edit.py:1173) — tail insertion, no mid-list render insert | no |

Supporting facts:

- `.scratch/audit_009_caller_geometry.py` replays each writer's real geometry
  against a run of identical lines with a CRLF in the run: every writer shape
  preserves the terminators (`items:`, boundary insert, blank-in-place,
  uniform rewrite, EOF append all green). Only the T1/T2 shapes lose bytes,
  and no writer produces them.
- The probe's fixture is not itself a loadable project state: three items
  with id `REQ-001` in one file →
  `ERROR items/a.yaml:5 [REQ-001] — duplicate id 'REQ-001' (also defined at
  items/a.yaml:2)` (verified: `.scratch/proj009b`, real CLI
  `python -m refdes.cli -c refdes-project.yaml --no-write check`). A CLI
  writer never sees that file's item lines as render inputs.

Verdict: **PRESENT at the API level, latent — no CLI command reaches it on
current main.** This matches the resweep's own note ("Reachability from a
CLI command remains unverified"); this audit strengthens it to unreachability
for every current writer, and additionally shows the length-preserving T2
shape, which the baseline did not cover.

## Reviewable design (not shipped)

Stabilize the alignment by tie-breaking maximal matches on positional drift:
callers here all edit a list derived from `.lines` in place, so an untouched
line sits at its original index plus the insertion offset above it — the
matching window that keeps `|j - i|` smallest is the one pairing each copy
with the original the caller left in place.

Subclass only `find_longest_match`; render(), the delete/replace/insert
handlers, `_neighbour_end`, `_break_unterminated`, and the contract stay
untouched:

    class _DriftMatcher(difflib.SequenceMatcher):
        def find_longest_match(self, alo, ahi, blo, bhi):
            i, j, k = super().find_longest_match(alo, ahi, blo, bhi)
            if k < 2:
                return i, j, k
            a, b = self.a, self.b
            best = (abs(j - i), i, j)
            for ai in range(alo, ahi - k + 1):
                for bj in self.b2j.get(a[ai], ()):
                    if bj + k > bhi:
                        continue
                    if a[ai : ai + k] == b[bj : bj + k]:
                        cand = (abs(bj - ai), ai, bj)
                        if cand < best:
                            best = cand
            return best[1], best[2], k

(`autojunk=False` stays — the existing comment at textio.py:161-164 is still
required, the two mechanisms are orthogonal.) Cost: the extra scan runs only
inside `find_longest_match` for k≥2 over occurrences of the window's first
element; item files are small.

Validation (in-process monkey-patch, src untouched —
`.scratch/design009_validate.py`):

- probe → GREEN: `'…REQ-001\n    NEW\n    NEW\n…REQ-001\n…REQ-001\r\n'`,
  tail CRLF preserved;
- CRLF mid-run (`"a\na\na\r\na\n"` + interior insertion) →
  `'a\nN\na\na\r\na\n'`: the untouched copies keep the original end multiset;
- controls: legitimate deletion (`["a","c"]`) and replace (`["a","B","c"]`)
  unchanged; T2 case `["  - B","  - A","  - A"]` → tail CRLF preserved;
- real suites with the patched render:
  `tests/test_eol_fidelity.py tests/test_patcher.py tests/test_revise.py` →
  **286 passed** (baseline on unpatched src: same 286 passed).

Regression set the fix PR should add to `tests/test_eol_fidelity.py`
`TestSourceText`: insertion inside a 3-run (LF tail, CRLF tail, CRLF
mid-run), T2 prefix rewrite of a run with CRLF tail, plus the deletion and
replace controls above so the fix cannot over-preserve (a line the caller
legitimately deleted must not resurrect).

## Scope / hygiene

- `atomic_write_text` untouched (PR #247 owns new-file mode in this file;
  disjoint hunks).
- No src, no tests modified on this branch; committed artifact is this log.
- Probes/scripts kept under `.scratch/` (gitignored):
  `probe_009_textio_delete_crlf.py`, `audit_009_caller_geometry.py`,
  `design009_validate.py`, `proj009b/`.
- `ruff check src/refdes/textio.py --select I` → clean (no changes to lint).

## Finish state

COMPLETE as designed-outcome: reproduced (REPRODUCED, exact probe on
7e49a20), root-caused (difflib leftmost-window tie-break over duplicate
runs), audited (all render() callers), judged latent/unreachable from the
CLI, design left reviewable. A follow-up that accepts the drift tie-break
should open the src PR against `src/refdes/textio.py` + the regression set
above.
