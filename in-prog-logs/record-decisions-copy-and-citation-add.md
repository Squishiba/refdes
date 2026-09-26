# Task: record two decisions Jared made in conversation (2026-09-26)

Docs-only, text-supplied. The exact wording of both decision blocks was
drafted by the requester and applied verbatim — no paraphrase, no
improvement, no extra sections. This log records where each went and what
was checked, not new claims about the specs.

## What was done

Two files, two independent edits, each in two places (a summary paragraph
plus the open question it answers).

### `docs/design/editor-image-upload.md`

- New `Update:` paragraph inserted **before** the existing §15.6 update, so
  the "Update:" paragraphs stay in question order (§15.1, §15.8, §15.6 as
  they already were relative to each other — §15.8 now precedes §15.6 by
  request, matching numeric question order rather than the previous
  authoring order). The paragraph records: no copy in either direction;
  external bytes are upload, which always writes into the project; no
  "leave it where it is" mode because `build.py` cannot resolve a path
  outside the project tree and doing so breaks other machines and CI; the
  in-project "duplicate into my directory vs reference in place" toggle was
  considered and rejected as adding a choice for no gain over the existing
  bare-name `site.assets:` search; so Phase 0's picker (§17) needs no copy
  logic.
- §15 open question 8 ("Is the copy half of … in scope?") replaced: was
  **Recommended: no, and it should be its own short spec** (a deferral, with
  a rationale about no binary transport in it and §7 doing double duty); now
  **DECIDED: no, and not later either** (Jared, 2026-09-26), with both
  readings named as (a) and (b) and rejected outright rather than deferred.

### `docs/design/editor-source-picker.md`

- New `Update:` paragraph inserted immediately **after** the `Status:`
  paragraph and before the `# Editor source-value picker` heading, recording
  that §9 Q2 is answered with option (A), to keep this moving rather than
  block on it: an item citing no CSV gets the empty-state message plus the
  exact YAML snippet to paste by hand (§8), and no citation-write patcher
  op ships; the narrower middle option (a patcher op writing only a bare
  `path:` entry, short of a full citations row editor) was set aside for
  later rather than built now.
- §9 open question 2 replaced: option A's label changed from
  `**A. Not in v1 (recommended).**` to `**DECIDED: A** (Jared, 2026-09-26,
  to keep moving rather than block here). Not in v1. §8: show the rule and
  the snippet.`; option B now carries the "not taken" outcome and the real
  cost of A restated as accepted rather than built around, and explicitly
  kept as a candidate for a later pass. The old trailing italic
  "*The real cost of A:*" paragraph is gone — its content moved into B's
  bullet, since with A decided the cost is a consequence of the decision
  rather than a condition on it.

Nothing else in either file changed. The Q2/Q3 boundary in
`editor-source-picker.md` stays contiguous, as it was before the edit (no
blank line between list items there in the original either).

## No changelog.d fragment — house practice, checked not assumed

`changelog.d/README.md` scopes fragments to changes a project reader would
care about: breaking / added / changed / fixed / removed, i.e. behaviour.
Recording a decision in a proposal-stage design spec changes no behaviour,
and the precedent commits are unambiguous:

- `a6c662a` "docs(calc-sources): record Q2 decided" — `docs/design/calc-sources.md`
  only, no fragment.
- `154e8b0` "docs(design): record named-calc-blocks decisions" —
  `docs/design/named-calc-blocks.md` + `in-prog-logs/…`, no fragment.
- `cf7f7e3` "docs(design): record PDF datasheet picker note" — two
  `docs/design/` files + `in-prog-logs/`, no fragment.

By contrast `6d89f75` (a real behaviour fix) does carry fragments. So the
skip is the matching precedent, not an omission.

## Verification

- Both quoted blocks were located and read before editing, and matched
  byte-for-byte, so no insertion point was guessed. `git diff` reviewed in
  full: exactly four hunks, two per file, no incidental rewrapping.
- `python -m pytest -q -x`: **2292 passed, 1 skipped** (104s), via
  `/home/jorb/work/venv-refdes/bin/python`. Unaffected, as expected for
  docs-only.
- `ruff check --select E9,F src tests`: all checks passed. (Per AGENTS.md a
  bare `ruff check .` is not a valid gate today — ~99 pre-existing findings
  — so the gate was run scoped, as instructed.)
- Text re-read in place after editing: the new paragraphs read correctly
  between the surrounding `Status:` / `Update:` blocks, and both
  open-question items keep their list numbering (8 in §15; 2 in §9, with
  Q1 above and Q3 below intact).

## Difficulties

None blocking. One judgement call worth flagging: the §15.8 paragraph is
inserted *before* the §15.6 paragraph, so the header block no longer reads
in ascending question order (it goes 15.1, 15.8, 15.6). That is what was
asked for and it does match numeric question order; leaving it would have
read as a stray out-of-sequence paragraph. Noted only so a later reader
does not "fix" it.

Status: finished. PR opened against main, not merged (per instructions).
