# w5b-ratify

Task: record Jared's 2026-11-06 ratification of the ten conservative
defaults (Q1-Q10) in `docs/design/thread-workbench-w5b-plan.md`, in the
style `living-notes-plan.md` uses for its own ratification.

What was done:
- Status line: "Proposed, and blocked on the owner" -> "Proposed, and
  unblocked", naming the ratified date and the now-unblocked phases
  (W5b.1-W5b.5); added the "answers have since landed" sentence to the
  header paragraph that describes the plan as written "before" its answers.
- §6: one `**Ratified 2026-11-06: ...**` line added under each of Q1-Q10,
  copying each question's own "Conservative default"/"Assumed" wording
  verbatim (Q2's line names all three of its defaults: (a)+(i), (iii),
  and the sub-question's (a)); no option text changed.
- §8 lead-in: no longer says the plan "does not decide Q1-Q10"; now says
  the answers are ratified and the table keeps the phase map.

Verification: `tests/test_docs_anchors.py` passes (2 passed). Checked
`docs/index.md` nav: no `design/` links, so the file is not in the docs
site and no site-build check applies. No src/ changes, so the pr-size
gate is not engaged.

Finished: yes.
