# navis-preview-mint (slice M2: Mint keys button on the preview Navis panel)

Status: finished. PR title `feat(serve): Mint keys button on the preview
Navis panel (M2)`.

## What was asked

Jared 2026-11-05: keyless Navis markers get no Archive button, so the
served preview panel must OFFER the mint (the M1 route,
`POST /api/navis/mint`, is merged). Add the Mint UI to
`src/refdes/serve/static/navis-preview.js` per the shared UI spec: a
`Mint keys (N)` pill when N rows are keyless, POST `{}`, success reloads
the way a successful archive reloads on this surface, a status line on the
reloaded page (`Minted K key(s).` / refusal sentence / `Nothing to mint.`),
non-200 alert + re-arm, 403 lockout incl. Mint, keyless-row discoverability
title, status clears on the next action. Red-first tests, real browsers,
docs, changelog.

## Design note (the one spec tension)

"On 200: refresh the panel exactly the way a successful archive does on
this surface, then show a status line." On the preview surface a
successful archive is `location.reload()`, so the status line cannot live
on the clicked page. Resolution: the success handler stores the status
text in one-shot sessionStorage (`refdes-navis-mint-status`) and reloads;
the reloaded page (browser case a: rows keyed, status visible) renders it
as `<p class="refdes-navis-note" role="status">` at the top of the panel
and consumes it (reopen shows nothing, like the alert). Class names keep
this surface's `refdes-` prefix (the spec's `navis-mint`/`navis-note` are
the editor panel's prefix; the panel's own CSS lives in bar.css/navis.css,
which style `refdes-navis-*`). The words match the spec exactly.

## What was done, in order

- Red-first: extended `tests/test_navis_preview_actions.py`'s node
  harness (fake sessionStorage, `.mono` key spans in the fixture, new
  scenarios 10-15 + extensions to 5/6/7), one Python test. Red evidence:
  `mintWired` count 0; `mintClick`/`mintStatus`/`mintFailed`/`mintRefused`/
  `statusClears` all `harnessError` (no mint button to click);
  `refused.mintDisabled` null. All green after the module change.
- `navis-preview.js`: mint pill + status store/take + keyless title +
  403 lockout includes mint + clearStatus on every action click.
  `bar.css`: mint pill metrics (same as the archive pill) + disabled/hover.
- Full suite once: 5938 passed, 2 skipped (192 s, -n 4 worksteal).
  Docs tests (test_docs_context_refs, test_pr_size) green after the docs
  edit. ruff on the touched test file: findings all pre-existing
  (module-level-import rule, which the whole tests/ tree carries);
  no new rule kinds added.
- Browsers (ports 8860 writable / 8861 `--no-write`, throwaway project:
  2 keyless markers in note-a, 1 in note-b (hostile text), 1 in a folded
  YAML list body (refused), 1 hand-keyed):
  - Chromium + Firefox, case a: `Mint keys (4)` + 4 keyless titles ->
    status `Minted 3 key(s). 1 marker(s) could not be keyed -- refdes
    will not mint into those bodies (for example a YAML list body).`
    (role=status), 4 Archive buttons, refused row (NOTE-100) still keyless
    with the title, pill now `Mint keys (1)`. Item files reverse-splice to
    the exact originals (only key splices; line counts equal;
    entries.yaml byte-identical). PASS.
  - case b (second click): `Minted 0 key(s). 1 marker(s) could not be
    keyed -- ...` + `Mint keys (1)`. PASS (both).
  - case c (--no-write): alert `this server was started with --no-write:
    navis mint is disabled` (role=alert), mint + archive all disabled, no
    reload, RO tree hashes unchanged after the run. PASS (both).
  - case d: hostile marker text -- 0 img/b elements in the panel, literal
    textContent, no script ran. PASS (both).
  - case e 375x640: mint pill and status line inside the viewport,
    documentElement.scrollWidth == 375. PASS (both).
  - Servers stopped by the PIDs I started (cwd checked via /proc).
- Docs: the preview-panel section of docs/navis.md, only for what was run.
  changelog.d/navis-preview-mint.added.md.

## Notes for the reviewer

- The spec's literal class names (`navis-mint`, `navis-note`) belong to
  the editor panel's namespace; the preview module's surface styles
  `refdes-navis-*` classes, so the button is `refdes-navis-mint` and the
  status paragraph reuses the published sheet's `refdes-navis-note`.
  All visible words match the spec verbatim.
- sessionStorage was chosen for the status because it survives exactly the
  reload (per-tab), and the one-shot read gives the required
  clears-on-reopen. Storage access is wrapped in try/catch (private-mode
  throw = status lost, mint not).
