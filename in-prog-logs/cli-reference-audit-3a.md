# CLI reference audit — chunk 3a (keys, revise, calc-rewrite)

Date: 2026-09-25. File under audit: `docs/cli-reference.md` only.
Method: every command run as
`python -c "import sys;from refdes.cli import main;sys.exit(main(sys.argv[1:]))" <args>`
from throwaway projects under `.scratch/proj` … `.scratch/projD`
(never `cd`; workdir parameter used). Source and tests were not edited.

## Scratch projects used

| dir | what it is |
|---|---|
| `.scratch/proj` | `hardware@3`, two boards, a sealed log, a stamped baseline, a page under `pages/`. The main workbench. |
| `.scratch/proj2` | two items, `rev-a` baseline; used for the calc-rewrite hash carry-forward test. |
| `.scratch/proj3` / `proj4` / `projA` | hand-rolled `refdes-schema.yaml` projects for the type/field-rename ordering tests. |
| `.scratch/proj5` | baseline + seal + membership manifest, one entry edited after the stamp → `uncomparable`. |
| `.scratch/proj6` | minimal adoption; duplicate-key membership manifest → `unidentified`. |
| `.scratch/proj7` | board-b check/bound pair (unused after the key-shape error). |
| `.scratch/proj8` | stale `boards:`/`workspaces:` manifest entries → `dropped 2 stale …`. |
| `.scratch/proj9` | broken project (dangling link) → adoption refusal; then a bound+decision with a `checks:` entry → `expanded 1 check reference(s)`. |
| `.scratch/projB` / `projC` | `--no-write keys adopt`; `revise --dry-run` mint plan. |
| `.scratch/projD` | clean hand-rolled schema, used for the optional-field-rename case. |

## Verified correct in the docs (no change needed)

### `refdes calc-rewrite`
- `--help` matches the documented flag set exactly: only `--dry-run`.
- Rewrites only lines inside ```` ```calc ```` fences in item regions. A
  `name : unit = expression` line in prose (inline backticks) and one inside a
  ```` ```text ```` fence were both left alone; `{{P}}` references untouched.
- Indentation, the trailing comment and its leading whitespace, and the
  equals-column alignment are preserved:
  `Q   : mW   = P * 1000    # aligned block` →
  `Q          = P * 1000 | mW    # aligned block`.
- Idempotent: a second run prints
  `nothing to rewrite -- no old-spelling calc lines found`, exit 0.
- Transactional: `refused:` (or `would refuse:` under `--dry-run`) with the
  offending diagnostics, exit 1, nothing written.
- Content hash carried forward in a stamped baseline: stamped `rev-a`, put the
  old spelling back, ran `calc-rewrite`, then `audit` reported
  `changed 0 / added 0 / removed 0` for the rewritten item.
- Sealed append-only entries are listed and left as written, and the retired
  spelling still evaluates there — `_site/log-a-001.html` contains `14.4`.

### `refdes revise`
- `--help` matches the documented flag set: one positional `mapping`, plus
  `--dry-run`.
- All four mapping keys work: `types:`, `fields:` (keyed by the OLD type
  name), `links:`, `prefixes:`.
- Ambiguous mapping refused up front, exit 1:
  `type rename collides: both 'spec' and 'decision' would become 'x'`.
  Target-already-in-use refused too:
  `type rename 'constraint' -> 'bound': 'bound' already names an existing type`.
- Refuses up front on a project with other build errors, exit 1, nothing written.
- Prose-mention report matches the documented wording and shape
  (`N prose mention(s) of a renamed id left behind …`, then
  `  <rel>:<line>  OLD -> NEW`).
- Both structured link spellings are rewritten, and so is `checks: … against:`:
  a flow-style list, a block sequence, `constrained_by:` and `against:` all moved
  together with the id.
- Hash carried forward in both a stamped baseline (`baselines carried forward: rev-a`)
  and a seal file (a sealed log entry's hash survived a prefix rename; the next
  `check` reported no seal mismatch).

### `refdes keys adopt`
- `--help` matches: only `--dry-run`, documented in the options table.
- Every bullet in the section is accurate: key minting (`key: <11-char>` in the
  source), link + `checks: against:` expansion to `DISPLAY-ID@key`, `follows:`
  freezing, baseline/seal/manifest rebasing, `.refdes/keys-adopted.yaml`.
- No bundled standard declares `follows:` — confirmed by grepping
  `src/refdes/standards/hardware/v3/base.yaml` (only `derives_from`'s doc string
  contains the word).
- Every report line in the documented sample reproduced verbatim, including
  `Review the diff before committing.`, the `N/M entries carried` suffixes,
  `uncomparable baseline entry rev-a: <id>`, and
  `unidentified membership entry boards: <id>`.
- `dropped 2 stale membership entries: boards: REQ-OLD-001, workspaces: REQ-OLD-004`
  reproduced exactly, and `would drop …` under `--dry-run`.
- Idempotent: `nothing to do -- project already adopted`, exit 0.
- Refuses on a project with build errors, exit 1.
- `refdes --no-write keys adopt` reports the full plan and writes nothing, exit 0.

## Proven discrepancies, and what was done about them

1. **`revise` + a hand-rolled schema: the "pair it with your own schema edit, in
   whichever order" advice does not work — neither order does.** Fixed in the
   docs (see the new paragraph under `refdes revise`).
   - Type rename, revise first: `refused: rewritten project has parse errors --
     rolled back: ERROR items/i.yaml:2 — unknown type 'spec2'. Did you mean 'spec'?`
   - Type rename, schema first: `refused: project has existing build errors --
     fix those first … ERROR items/i.yaml:2 — unknown type 'spec'. Did you mean 'spec2'?`
   - Required-field rename, revise first: `refused: rewritten project has build
     errors -- rolled back: ERROR … missing required field 'title'`
   - Required-field rename, schema first: `refused: project has existing build
     errors … ERROR … missing required field 'label'`
   - The only rename `revise` completes alone on a hand-rolled schema is an
     **optional** field rename, which leaves the new key as an
     `unknown field 'X' on <type>` warning. Verified.
   - The code path that does move both together exists
     (`revise.apply(..., mutate_config=...)`, used by
     `refdes standard upgrade` per `tests/test_revise.py:71`) but is not
     reachable from the `refdes revise` CLI.

2. **`calc-rewrite` and a tolerance in the old annotation.** The documented
   example `P : W ± 10% = V * I` → `P = V * I ± 10% | W` is the right
   *transformation* (the build error quotes exactly that string) but the command
   refuses the file containing that line. Docs corrected, and the contradiction
   recorded here and in the report.

3. **Global `--no-write` table omitted `calc-rewrite`.** Added.

4. **"Files the tool writes" omitted `.refdes/keys-adopted.yaml`.** Added.

5. Minor undocumented outputs added: `nothing to do -- mapping doesn't apply to
   this project`, revise's `baselines carried forward:` line, and revise
   `--dry-run`'s "would first mint/expand to composite form" block.

## Source bugs found (recorded, NOT fixed — source edits are out of scope)

- **`calc-rewrite` refuses exactly the line its own build error tells you to run
  it for.** With `P : W ± 10% = V * I` in an item body:
  `refdes check` says
  `a tolerance belongs on the right-hand side, and the ': unit =' spelling was
  retired — write 'P = V * I ± 10% | W'; run 'refdes calc-rewrite' to fix a whole
  project`, and `refdes calc-rewrite --dry-run` answers
  `would fail: a rewritten calc changes meaning: items/…:7 P: was '' in unit
  'W ± 10%', now evaluates to '14.4 W' in unit 'W' -- a rewrite must not change
  what a calc computes` (exit 1, nothing written). The before-picture records
  the line's unit as `W ± 10%` with an empty result, so the equality check can
  never pass. Reproduced three times, in three different projects, sealed and
  unsealed. A user following the build error's advice is stuck.
- **`refdes revise` with a nonexistent mapping file crashes.** `refdes revise
  nope.yaml` raises an unhandled `FileNotFoundError` out of
  `revise.load_mapping` (`src/refdes/cli.py:930`) and prints a Python traceback
  with exit 1, rather than the exit-2 configuration error the global exit-code
  table promises for a bad path.
- **`revise` does not check that a link rename's target verb exists in the
  schema.** `links: {refines: narrows}` on a `hardware@3` project rewrote the
  data to `narrows:` and then only warned `unknown field 'narrows' on
  requirement`. A type or field rename is validated in both directions; a link
  rename is not. Not documented as a bug fix here (the docs never promised the
  check), but worth knowing.
- **`calc-rewrite` never reports `seals carried forward:` in practice.** Sealed
  entries are the one thing it refuses to rewrite, so a seal entry's content
  hash cannot change and `_carry_forward_seals` has nothing to migrate. The
  doc's "and seal files" is therefore inert for this command. Left as written
  (not disproven — the code path exists and is harmless), but noted.

## Gate

`python -m pytest -q -x` and `python -m ruff check --select E9,F src tests` run
at the end; results in the report to the orchestrator.

## Conflict resolution (PR #40)

`main` advanced under PRs #39 (chunk 3b: stub-tests/former-ids/history) and
#41 (getting-started, authoring, concepts, ids, checks, coverage), so
`git merge origin/main` reported one content conflict, in
`docs/cli-reference.md`.

It was a single-line conflict: both sides had independently edited the global
`--no-write` table row.

- **My side** (chunk 3a) added `calc-rewrite` to the "commands with
  `--dry-run` that report and write nothing" list.
- **main's side** (chunk 3b) added `history capture`, `history redact` and
  `history migrate-seals` to the "refuse to run under `--no-write`" list.

These are different lists in the same row, so the resolution keeps both: the
dry-run list reads `id`, `revise`, `calc-rewrite`, `stub-tests`, and the
refusal list reads `fetch`, `init`, `standard upgrade`, `standard add-preset`,
`standard remove-preset`, `former-ids propose --confirm`, `history capture`,
`history redact`, `history migrate-seals`. Every write command is now covered
in exactly one of the two lists.

I had deliberately backed the `history` addition out of my own version,
because verifying it was chunk 3b's scope and not mine; main has now verified
and landed it, so it stays.

Other shared tables auto-merged, and both sides' edits survived — checked
explicitly rather than trusting the auto-merge:

- "Files the tool writes": my `.refdes/keys-adopted.yaml` row and my
  `refdes calc-rewrite` addition to the baselines row are both present
  alongside main's `.refdes/history/` row.
- No conflict markers remain anywhere in the file.

Re-verified after the merge, rather than carried over from the earlier run,
because the merged row now asserts more than either side did alone:
`refdes --no-write calc-rewrite` on a project with an old-spelling line still
prints `would rewrite 1 calc line(s) in 1 file(s):` and leaves the file
byte-identical, exit 0. Worth noting that the installed CLI's own `--no-write`
help string still does *not* list `calc-rewrite` among the reporting commands —
the docs are more accurate than the built-in help here, which is consistent
with the source-bug list above.

Gate re-run after the merge: `python -m pytest -q -x` → 2154 passed;
`python -m ruff check --select E9,F src tests` → all checks passed. GitHub
reports the PR `MERGEABLE` / `mergeStateStatus: CLEAN`. Not merged.

