# serve: the browser editor's refdes buttons

Slice 2 of the editor toolbar design: the formatting bar gains a refdes
group of its own.

- `[[ID]]` opens a picker popover over the textarea: every item in the
  project, sorted by display id, with type-ahead filtering by id and title
  (the same convention as the link picker, now shared in `pickers.js`),
  keyboard activation (arrows/Enter/Escape), an honest notice when the
  fetched page is a prefix of the project, and an honest banner when the
  fetch fails. Picking inserts `[[ID]]` at the caret, or `[[ID|selection]]`
  wrapping the current selection; focus returns to the textarea.
- The skeleton buttons insert the §H-4 snippets that intentionally fail the
  gate until completed: `` `name := 0 | V` `` (name selected), a
  `` ```calc `` block landed after the enclosing fence (name selected),
  `[[fig:]]` and `{{}}` with the caret inside the brackets (a selection is
  wrapped and kept selected). The live-calc panel guides completion; a
  skeleton save is blocked with the gate's own message, and the text
  survives.
- Image and Source buttons focus the existing panels below the textarea.

All seven buttons are real `<button>`s with aria-labels, share the bar's
isSaving gate and the undo-friendly mutator, and are inert in the read-only
editor (no bar at all).
