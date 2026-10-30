Task: editor font setting slice 3

Finished: yes.

Implemented a browser-only font preference for the body editor. The setting
stores family, size, and line height in `localStorage` under
`refdes.editor.font`. It applies only CSS custom properties to the body
textarea, so body text, drafts, saves, preview, and project settings are
unchanged.

Files touched:
- `src/refdes/serve/static/fontsetting.js`
- `src/refdes/serve/static/editor.js`
- `src/refdes/serve/static/item.js`
- `src/refdes/serve/static/style.css`
- `tests/test_editor_font_setting.py`
- `tests/test_serve_static.py`
- `changelog.d/editor-font-setting.added.md`

Testing:
- Red-first node harness passed after the module and wiring landed.
- `python -m pytest tests/test_editor_font_setting.py tests/test_serve_static.py -q`
  passed: 57 tests.
- Fixed radio checked-state updates after choosing a line-height option.
- Real Chromium and Firefox drivers were rerun from a local `refdes serve`
  origin on port 8752.
- Browser checks passed for:
  - initial, changed, and persisted radio checked state
  - mouse and keyboard popover open/close
  - visible computed font family, size, and line-height changes
  - reload persistence
  - item-switch persistence
  - live-calc panel coexistence
  - corrupt `localStorage` fallback
  - native undo history after font changes

Notes:
- CSP measurement showed CSSOM custom-property writes apply while injected
  `<style>` remains blocked, so the implementation uses CSSOM writes only.
- The Chromium driver needed CDP `Input.insertText` for reliable native
  textarea input and undo grouping.
- The Firefox driver uses Playwright's native `insertText` path for the same
  reason.
