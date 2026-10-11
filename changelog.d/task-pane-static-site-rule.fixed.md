- `docs/design/thread-workbench.md` §7a and `docs/design/browser-editor.md`
  now record the owner-approved static-site rule for the read-only task pane
  (2026-10-10): it is progressive enhancement — with JavaScript off the site
  still reads fully and the pane simply doesn't appear — and it shows the
  tip's task list read-only, no checkboxes that write, no token, no write
  API, so it stays within the rule that no editor control is emitted into
  `_site/`. The same Status-header pass names the §7a decisions and phases
  them as W5 (not started, blocked on living-notes-plan H6/H7).
- Stale design-doc references corrected against the current tree: the
  subcommand list in `docs/design/living-notes.md` §6 (`refdes history`
  exists today as the captured-history store command; `serve` and
  `calc-rewrite` were missing from the list), the engine-reserved /
  conditionally-overridable item keys and their `parse.py` line refs in
  `docs/design/browser-editor.md` and `docs/design/living-notes-plan.md`
  (item-level `history:` renamed to `on_change:`, which is now in
  `parse.OVERRIDABLE`; `RESERVED`/`OVERRIDABLE` live at `parse.py:40`/`44`),
  and the `README.md` line citation for the no-server / JavaScript-disabled
  promise in `docs/design/browser-editor.md`.
