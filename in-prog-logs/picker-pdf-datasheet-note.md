# PDF datasheet picker -- design note, 2026-09-21 (docs-only)

Docs-only task. No code touched. No push, no merge; orchestrator (refdes-2)
lands after review. Branch ao/refdes-136/root, merged origin/main first
(Already up to date: HEAD == origin/main == 9a59f3d).

Recorded Jared's 2026-09-21 approved design note in two places:

- `docs/design/calc-sources.md` -- appended to section 1's
  "Requirement: a picker for importing values from an outside file"
  (after the "Cross-referenced from ..." line, before the `---`).
  Note states the existing requirement already covers CSV/xlsx (picker lists
  keys/values of a pinned source file, author picks one, editor writes
  `source("path", "key")` -- unchanged), then records the new PDF datasheet
  picker item: status NOT DECIDED IMPLEMENTATION / later slice; extracted
  value shown with unit in context (highlighted cell/line), min/typ/max
  candidates all listed, nothing pre-selected, `citations:` entry with file /
  page or section: / quoted text / confirmed value, lockfile pins so changed
  PDF raises the loud drift warning (calc-sources Q2: warns loudly,
  `fetch --update` accepts), fail visibly on scanned/image-only or ambiguous
  pages; the guard is against silent plausible-but-wrong numbers (mA vs A,
  1000x, wrong min/typ/max). Costs: PDF text-and-coordinates library as new
  optional dependency (like openpyxl), pdf.js vendoring or server-side image
  rendering; no Node build step preserved, heaviest dependency the editor
  would have. Sequencing: after the CSV/xlsx picker, as its own later slice,
  one more source type behind the same picker UI and confirm-before-accept.
- `docs/design/browser-editor.md` -- added a "#### PDF datasheet values"
  subsection under "### Source-value picker" (next to the existing
  cross-reference to calc-sources.md §1), mirroring the same note with a
  pointer back to `docs/design/calc-sources.md` §1.

No claims added beyond the approved content. Curly quotes / em-dash style
matched the existing docs. Verification: python -m pytest -q (full suite) run
before reporting as instructed. No changelog fragment: design decision record
only.