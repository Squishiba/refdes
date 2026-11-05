# design-fence-shortcut-row (docs-only)

Task: drop the self-contradicting Ctrl/Cmd+Alt+C "code fence" shortcut
row from `editor-format-toolbar-design-20261029.md` §B and record
Jared's 2026-11-04 decision (no code-fence shortcut) as §H-6.

Verified before writing (grep output quoted):
- `src/refdes/serve/static/formatbar.js` SHORTCUTS table: ops are
  bold, italic, link, strike only — no fence shortcut.
- `docs/browser-editor.md` lines 50-53: shortcuts listed as
  Ctrl/Cmd+B/I/K + Alt+Shift+5, "no shortcuts for the heading, list,
  quote, table, or rule buttons" — no fence shortcut mentioned.
- Decision-text claims checked too: formatbar.js:719 `code` op =
  `applyInline(..., '`', ...)` (inline backticks only);
  browser-editor.md:77 `calc` inserts the fence skeleton (only
  fence-inserting button).

Changes: deleted the §B table row (row ~399); "Never bound" paragraph
left untouched; added §H-6 in the existing numbered DECIDED format.
No code/test changes, no suite run, no changelog (design record only,
per brief). Finished.
