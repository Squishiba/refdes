2026-11-05 — Navis-in-VS-Code slice plan (N6), docs-only

Task: turn the deferred slice-6 sentence of the Navis design
(in-prog-logs/navis-design-20261025.md §13 line 424, §14 Q5) into a
slice-ready plan for the VS Code extension, in the W5b §6 format.

Done: docs/design/navis-vscode-panel-plan.md. Branch
docs/navis-vscode-plan off main b9eba32d; docs-only (no src/, no
changelog.d — plan-only PRs get neither, precedent: W5b plan PR).

Evidence-gathering (all citations opened, not recalled):
- editors/vscode/: extension.js (1,002 lines) + serveClient.js (GET-only
  request, TOKEN_HEADER, deepLink) + package.json (no views contribution
  -> TreeView is a NEW surface; status bars x2, output, diagnostics, 4
  providers, 9 commands).
- Serve: api.py dispatch, navis_read (GET /api/navis shape),
  navis_write/navis_mint (statuses, gate-first 403, forced refresh),
  security.py (token/Host/Origin), server.py gates (415/411/413, _deny
  is text/plain -> token 403 distinguishable from JSON kind:refused).
- state.py serial per _build + force-refresh on navis writes -> the
  existing 5s revision poll is the tree's refresh signal.
- Tests: test_vscode_extension.py (text pins + node -e),
  test_vscode_adapter_contract.py (live server), test_docs_anchors.py.

Decisions taken (recommended defaults, Q1-Q7 in the plan):
data path GET /api/navis over the design's index-payload wording (the
extension is a serve client since V0 and actions need the server);
native TreeView (new contribution, cheapest surface, no webview
second-UI tax); lazy ensureServe on expand; click-through via
file+line, the definitionProvider pattern; plain-string TreeItems only
(no MarkdownString from row data); slices S6.1-S6.4, none touching
src/ so the 350-line gate is green by construction.

Difficulties: the adapter doc's §2 line anchors are stale (files grew;
its own header says so) - re-verified every citation against current
files. The index-payload vs /api/navis tension is a real design
deviation, flagged as Q1 rather than buried.

Status: task finished on the docs side; commit + PR pending in this
session. Not verified here: anything a real VS Code window shows (list
in plan §7 manual checklist for Jared).
