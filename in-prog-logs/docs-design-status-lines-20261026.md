# docs: fix the four Status-line mismatches from the 2026-10-26 backlog audit

Task: docs-only. Section 3 of
`in-prog-logs/backlog-status-audit-20261026.md` (read via
`git show origin/docs/backlog-audit-20261026:in-prog-logs/backlog-status-audit-20261026.md`
— not on main) records four `docs/design/*.md` headers that contradict main.
Edited ONLY the Status line / the stale paragraph in each; no design content,
no code. Tree: branch off main at `703f0bd`, tree clean at start.

## RED evidence (stale claim present on main, each re-verified by command)

No code test exists for a prose Status line; the RED state is the false
claim verified present on the pre-edit tree, the same standard #363/#311
used. Each claim re-verified on main before editing:

1. `living-notes.md:1` read "Status: Decided -- ready to plan
   implementation" while `living-notes-plan.md:1` reads "Implemented
   (H1–H8; optional H9 not landed)" and the code is on main:
   `cmd_thread` cli.py:1246, `cmd_work` cli.py:1453, `tasks:`
   v3/base.yaml:302, `follows:`/`addresses:` :165-166, EVENT_KINDS
   history.py:86. d18f76d (#310) / 8b1a387 (#363) fixed neighbouring docs,
   not this header.
2. `vocabulary-review.md:322-326` §1.7 "(not implemented)" / "Both
   documents are unshipped … None of these words is in `base.yaml`, in
   `vocabulary.py`, or in `cli.py` today" — same code evidence as (1),
   plus: `redact` in history.py+cli.py, `open_tasks`/`captured_edits`
   model.py:122-123, `captured_edits` lifecycle.py:735, threads.py
   carries tip/continuation. NOTE: the plan's `recorded_edits` shipped
   as `captured_edits` (grep `recorded_edits` src/ → nothing) — recorded
   in the replacement paragraph.
3. `item-search-hover.md:1` read "no slices scoped, no code written"
   while its own §3.5 (~:196) says "Slice V−1 and Slice V0 have both
   landed" and `da2e44b`(#58)/`0f38619`(#66) are ancestors of HEAD
   (`git merge-base --is-ancestor`), hover facts in
   `editors/vscode/extension.js`. Search itself unlanded, so "proposed"
   stays. (#363's fragment explicitly left this header alone claiming it
   "already true" — that is the miss the audit caught.)
4. `seal-marker-identity.md:1-2` claimed "history.py and its tests are
   untouched" (drafted 2026-09-27) while `git log --since=2026-09-27 --
   src/refdes/history.py` shows 1a1c960(#212), e16a0df(#271),
   af20d76(#272), 6d104be(#323), 944afbb(#330), and the §1 display-id
   fallback is live at history.py:1279. Proposal state kept:
   `grep 'deleted:' src/refdes/history.py` → exit 1 (unlanded), so
   "proposed" stays; only the false "untouched" clause and its
   justification were replaced.

## Edits

- living-notes.md:1 — decided -> decided-and-implemented, citing plan
  header, `d84e123`…#193, #191/#194, cli.py/base.yaml line cites.
- vocabulary-review.md:322+ — heading "(landed since drafting)";
  paragraph rewritten as drafting-time premise marked stale, code cites,
  recorded_edits->captured_edits name note, T0-tier caveat. Table and
  §3.1 untouched (audit scope was 322-326 only).
- item-search-hover.md:1-4 — search stays proposed/"no code … landed";
  header now names the landed adapter slices V−1/V0 with shas + §3.5.
- seal-marker-identity.md:1-6 — "landed: no `deleted:` namespace" +
  "no longer untouched" with the five post-drafting PRs and the live
  fallback cite; Jared's-call sentence kept.
- changelog.d/design-doc-status-lines-audit.fixed.md — precedent:
  #363 shipped `design-doc-status-lines.fixed.md` for docs status fixes.

## Verification (green)

- `refdes build` in docs-site (CI docs.yml command): baseline before
  edits "0 items, 0 errors, 0 warnings"; after edits identical — 0 new
  warnings. Design pages are site pages (`_docs/design-*.html`).
- `python docs-site/gen_examples.py --check` (CI docs.yml step): up to
  date.
- pytest: tests/test_docs_anchors.py + test_docs_examples.py = 8 passed;
  neighbours test_candidate_parts_doc / test_standard_docs_complete /
  test_linkify_anchors / test_render_calc_anchors = 26 passed. venv:
  /home/jorb/work/venv-refdes, PYTHONPATH=src.
- No .py files touched, so no ruff run applies (and per AGENTS.md
  `ruff check .` is not a valid gate anyway).

## Scope notes / not satisfied

- vocabulary-review.md:32-34 (intro "unshipped … about to add") repeats
  the stale premise in the review's findings summary; audit scoped item 2
  to 322-326, so left untouched — flag for a future pass.
- Body line-cites in seal-marker-identity.md §1 (history.py:842/:879)
  have drifted (now :1279 area); audit flagged only the Status lines,
  body citations deliberately left as drafting-time text.
- Task's "write tests first, show RED" is satisfied in prose form above
  (docs-only, no code test possible); the machine-checkable gates (build
  warnings, anchor tests) all ran green pre- and post-edit.
