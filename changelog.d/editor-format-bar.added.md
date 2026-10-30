**Formatting bar for the browser editor** (slice 1,
`in-prog-logs/editor-format-toolbar-design-20261029.md`). `formatbar.js` adds
the core body-formatting row: bold, italic, strikethrough, code, heading,
bulleted list, numbered list, block quote, link, table, and horizontal rule.
Every mutation goes through one shared textarea path: Case A tries
`execCommand('insertText')` so a normal browser input event commits the draft
and one toolbar insertion stays one native undo step; Case B splices the
textarea value, dispatches exactly one synthetic `input` event, and records the
shared `refdes.live-calc.fallback` session flag so the bar and the live-calc
panel stand down together. In Case B the bar says undo may need more than one
step in that browser. The bar uses real focusable buttons with labels,
prevents focus stealing on mousedown, gates clicks and shortcuts while a save
is in flight, and binds only the checked shortcuts: `Ctrl/Cmd+B`,
`Ctrl/Cmd+I`, `Ctrl/Cmd+K`, `Alt+Shift+5`, and `Ctrl/Cmd+Alt+C`.
`insertIntoBody` and `insertSourceLine` now use the same mutator.
