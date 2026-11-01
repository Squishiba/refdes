# Browser editor user guide — progress log

Task: write docs/browser-editor.md (user guide for `refdes serve`'s editor:
formatting bar, refdes buttons, font setting) plus nav/pointer updates.
Docs-only PR slice 4. Branch docs/browser-editor-user-guide, base d9719a9
(#402 size gate).

## Progress

- Base sync confirmed: HEAD d9719a9 = "ci: PR size gate (src additions
  budget) (#402)", clean tree.
- Read design docs + shipped JS (formatbar.js, fontsetting.js, editor.js,
  live-calc.js, pickers.js, api.py) for the claims to verify.
- Scratch project .scratch/beproj: 4 decisions (one stale inline calc, one
  valid calc fence), one requirement, a custom append-only `note` type whose
  entry NOTE-001 is sealed via `refdes build` (seal written to
  .refdes/log-seal.yaml) for the read-only path. Standard `log` is
  `sealing: history` and never seals — that's why the custom type exists.
- serve on 127.0.0.1:8759 (pty, token file), restarted after sealing.
- Chromium suite (.scratch/pptr/verify.mjs, puppeteer-core): first run
  16/23, all 7 failures were harness bugs (truncated note() is a text node
  not children; 422 arrives after the 'Saving…' text → race; font selectors
  are on the input itself; chained shortcuts wrap prior markers; save note
  is transient because the pane re-renders on save; figure/value caret
  offsets). After harness fixes: 23/23 PASS.
- Firefox suite (.scratch/pptr/verify-ff.mjs, playwright-core firefox
  1555): playwright evaluate() takes one arg (setBody fixed); 9/9 PASS.

## Measured facts (both browsers unless noted)

- Bar: 18 buttons — 11 core (Bold, Italic, Strikethrough, Code, Heading,
  Bulleted list, Numbered list, Block quote, Link, Table, Horizontal rule)
  + 7 refdes ([[ID]] picker, [[fig:]], calc fence skeleton, := span
  skeleton, {{}}, Image panel, Source panel).
- Shortcuts: Ctrl/Cmd+B, +I, +K, Alt+Shift+5 (textarea only). Heading/list/
  quote/table/HR have no shortcuts.
- No selection: placeholder text inserted and selected ('**bold text**' →
  'bold text' selected; link → 'url' selected).
- Heading cycles # → ## … → plain. Table skeleton selects first cell; HR is
  a block insert; caret inside a calc fence → block insert lands after the
  fence.
- Picker: 'filter items…', rows 'ID — title', ArrowDown/Up + Enter picks,
  Escape closes; focus returns to textarea; [[ID]] (caret) / [[ID|text]]
  (selection).
- Skeletons: '```calc\nname = expr | V\n```' with 'name' selected; '`name
  := 0 | V`' with 'name' selected; '[[fig:]]' / '{{}}' caret inside.
  Saving an unfilled skeleton is blocked (422 banner): "blocked: the edit
  would leave 1 error(s): calc 'name': unknown name 'expr'" and "…stored
  result missing; write '= <quantity>'"; draft stays unsaved, disk untouched.
- Font: 'Font' button → 'Editor font setting' popover; Mono/Sans/Serif,
  size 11–20 (default 12, + works, 12px→13px measured), Compact 1.35 /
  Normal 1.5 / Loose 1.7; persists in localStorage refdes.editor.font
  across reload; corrupt value falls back to defaults.
- Live calc: panel 'Live inline calc', checkbox 'update results while I
  type' (on by default), ~400 ms settle; stale span `Vbad := 2 V * 2 = 5 V`
  auto-corrects to '= 4 V' while typing; unfilled span row shows 'stored
  result missing' error.
- Read-only sealed entry (NOTE-001): no format bar, no textarea, no Font
  control, no Save; 'sealed — read only' badge; reason "a sealed entry is
  append-only: a correction is a new entry, not this edit".
- Draft: status 'unsaved', survives reload; Save → 'saved' + file written;
  Discard restores saved text. Save note 'Saved.' is transient (pane
  re-renders).
- Focus returns to the textarea after every bar button; create form has no
  bar; Image button focuses the images panel filter, Source opens/focuses
  the sources panel.

## Status

Finished. Chromium 23/23, Firefox 9/9. Server stopped at PR time.
Screenshots intentionally not committed.
