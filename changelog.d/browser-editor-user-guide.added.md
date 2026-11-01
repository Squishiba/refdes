- **New docs page: the browser editor guide.** `docs/browser-editor.md`
  documents the `refdes serve` editing surface for authors: the eleven
  formatting buttons and their four keyboard shortcuts (what happens with a
  selection, with a bare caret, and on a second press), the seven refdes
  buttons — the `[[ID]]` picker, the calc-fence and inline-span skeletons
  and the save gate that refuses to write them unfilled, figure/value
  insertions, the images and sources panels — the live inline calc panel
  (stale/ok/error rows, update-while-I-type, the Fill button), the
  per-browser font setting, draft/save/discard, and the read-only rendering
  of a sealed log entry. Nav, CLI-reference, and markdown pointers added;
  design-doc v1 item 5 marked shipped. Every behaviour on the page was
  verified in live browser runs (Chromium and Firefox) against `refdes
  serve`; the create form has no bar, and the skeleton-gate messages quote
  the build verbatim.
