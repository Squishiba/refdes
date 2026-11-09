/* The preview pane's tick note (docs/design/thread-workbench-w5b-plan.md
   W5b.3). The response decoration grows the pane's tick rows in a preview
   page and loads this module beside them; a published page grows neither.
   It records nothing: no draft, no request, no storage. A click toggles a
   checkbox and the Space key does the same, both the checkbox's own native
   behaviour; a reload restores what the file says. W5b.4 adds the save.
   The one thing this file adds is a sentence under the pane title, shown
   when the pane has tick rows: rendered through textContent (no markup is
   ever pasted), it says plainly that the control is preview-only, so the
   pane never implies a save it does not have. */

var heads = document.querySelectorAll(".refdes-taskpane .refdes-taskpane-head");
for (var i = 0; i < heads.length; i++) {
  var head = heads[i];
  var pane = head.closest(".refdes-taskpane");
  if (!pane || !pane.querySelector("input[data-refdes-task]")) continue;
  var note = document.createElement("p");
  note.className = "refdes-taskpane-tick-note small muted";
  note.textContent =
    "Preview: ticking a row changes this page only -- nothing is saved.";
  head.insertAdjacentElement("afterend", note);
}
