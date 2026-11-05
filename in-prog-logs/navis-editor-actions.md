# N5d-2: editor Navis panel Archive/Restore

Goal: add Archive/Restore actions to the browser editor's Navis panel,
keeping the N5d-1 panel data path and reusing the preview panel's action
rules.

Done:

- `navis-panel.js` now wires Archive on keyed active rows in the top
  list and Restore on keyed archived rows in Show-all. The Archive pill
  deliberately appears in one place so Show-all's repeated active rows
  do not create two controls for the same marker.
- Orphaned archived rows keep Restore disabled with the preview panel's
  hand-restore title. Keyless rows receive no API control.
- Buttons post the full key to `/api/navis/archive` and
  `/api/navis/restore` through the shared API helper. Success refreshes
  the panel, leaves it open, and never reloads the SPA.
- Non-403 failures re-enable the clicked button and reuse one
  `p.navis-error[role=alert]` at the panel top. TextContent rendering
  keeps hostile server text literal.
- A 403 locks the panel for the session. The flag is module-scoped, so
  a refresh arriving after the catch draws disabled buttons and keeps
  the refusal message. Success clears the message; closing/reopening
  also clears it.
- Added pill/error CSS. Node harness `test_editor_navis_panel_actions.py`
  covers the full rule set and the late-refresh race. The targeted node
  suite was 9/9, including existing panel and preview action tests.

Difficulty: the real-browser race exposed that the original design's
per-render button registry was not enough. Opening the panel starts a
GET; on the read-only server, a POST's 403 catch can finish first, then
the GET redraws the panel. The alert and lockout must belong to the
mount, not the current render.

Real-browser status: Chromium evidence is recorded in
`.scratch/navis-e2e/run2-chromium.json`. It proves the 403 message,
all-button lockout, panel-open/alert placement, orphan and keyless
rules, 375px fit, the hostile row, and the writable panel's Archive POST
plus refresh. The suite's state-loop assertions were not usable as
proof: the sandboxed e2e server returned archive POST 200 while its
subsequent `GET /api/navis` counts and archive records were volatile.
That is a server record-lifecycle/sandbox interaction, not the panel
module's rendering path, and was left unpursued to keep this slice in
scope. The Firefox slice run was not completed, so docs claim Chromium
only.

Status: implementation, targeted checks, docs, changelog, and this log
complete. Full suite, commit, and PR are the remaining gates.
