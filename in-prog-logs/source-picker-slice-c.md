# Source picker Slice C progress

- Read the full `docs/design/editor-source-picker.md` and checked the clean worktree before editing.
- Verified the live service payloads in `src/refdes/serve/sources.py` and the `pin` request shape in `src/refdes/serve/api.py` and `edit.py`.
- Added `sourcepicker.js` with file, key, and confirmation steps. The unit starts empty; proposals and calc lines come from the service. The picker displays row context, pinned value, drift, and reader problems.
- Wired the picker beside the body textarea. Its Accept callback places the proposed line inside an existing calc fence, saves it through `setDraftBody`, persists the accompanying pin in the same draft, and calls the editor's existing `set_body` Save path. A missing calc fence is refused without changing the draft.
- Added read-only browsing for sealed/imported bodies, styling, four named static tests, and an HTTP flow test that checks the refreshed preview after accept.
- Difficulty: the sandbox forbids loopback sockets, so the HTTP test needed escalated execution. The static test's simple brace scanner treated literal backticks in a regular expression as JavaScript strings; the fence matcher now uses an escaped code point.
- Verification: `pytest -q -x` passed with 2,543 passed and 2 skipped; `ruff check src/refdes/serve/static tests/test_serve_static.py --select I` passed; the focused static module passed with 38 tests. The final review caught and fixed named `calc` fence matching, followed by another 38-test static pass. The strengthened real HTTP test passed (1 test), checking the calc table's result cell rather than incidental text on the page.
- §9: followed the recommendations for live values beside pins, server-side filtering, broken rows remaining visible, read-only browsing, and no remembered unit defaults. Q1 is implemented by Slice B's existing transaction; Q2's decided empty state is retained.
- Status: implementation and verification finished. Commit, push, and PR are the remaining publication steps.
