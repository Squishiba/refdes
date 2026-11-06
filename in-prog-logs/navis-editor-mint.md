# navis-editor-mint (slice M3)

Task: add the Mint UI to the EDITOR's Navis panel (`navis-panel.js`), per
the M-series spec. Red-first tests, then real browsers.

## What landed

- `src/refdes/serve/static/navis-panel.js`: one `Mint keys (N)` pill at the
  top of the panel, N = rows with an empty `key` in the payload already in
  hand. No pill when N = 0. Click disables it and POSTs `{}` to
  `/api/navis/mint` through the panel's own api helper. On 200: clearError,
  show a `p.navis-note[role=status]` status line (`Minted K key(s).`, the
  refused-marker sentence when `still_keyless` > 0, `Nothing to mint.` when
  K = 0 and none refused, plus the draft sentence when K > 0), then
  `refresh()` — the same in-place refresh a successful Archive does; no
  reload. Non-200: re-enable, `payload.error` in the shared alert. 403: joins
  the session lockout (the mint button is in the registry). Keyless rows gain
  a key-span title `No key yet -- use Mint keys`. Status clears on the next
  action and on reopen, like the alert.
- `style.css`: `.navis-mint` shares the archive/restore pill metrics.
- `tests/test_editor_navis_panel_actions.py`: harness extended (keyless/
  minted/keyed payloads, a mint POST hook). New scenarios M0-M5 cover the
  button by keyless count, the `{}` POST body, the three status shapes, the
  draft sentence, the non-200 alert (hostile literal), the 403 lockout incl.
  the mint, and clear-on-next-action/reopen.
- Docs (`docs/browser-editor.md` Navis panel) + `changelog.d/navis-editor-mint.added.md`.

## Red/green

Both node tests failed first (`'/api/navis/mint' not in panel`; harness threw
on the missing `navis-mint`). Green after the implementation.

## Browsers (Chromium + Firefox, live `refdes serve`)

Ports 8862 writable / 8863 --no-write, own scratch project (two keyless item
markers, one keyed, one folded YAML-list marker refused). Recipe copied from
`.scratch/pptr388` into `.scratch/pptr`. All PASS both browsers:

- (a) `Mint keys (3)` -> status line, NOTE-001/NOTE-002 keyed (Archive
  appears), NOTE-100 (folded) stays keyless, panel open, no reload; the two
  item files differ ONLY by the key splices (un-slice == original, line
  counts equal).
- (b) DRAFT: open NOTE-001, type an unsaved line, Mint, ~4s, Save ->
  `.edit-block .conflict` visible; the minted key is on disk, the draft was
  NOT written. *FINDING:* choosing **Keep mine** writes the draft body over
  the file, dropping the minted key (`keyFinal` = null; draft landed). The
  mint is reported, not kept, on that resolution. This is a finding, not an
  M3 failure.
- (c) draft on NOTE-003 (keyed, untouched by the mint): Save works, no
  conflict, key unchanged, draft lands.
- (d) `--no-write`: `--no-write` refusal in the alert, mint + Archive +
  Restore all disabled, tree unchanged.
- (e) hostile marker text renders literal (no img, no dialog).
- (f) panel + mint pill fit 375x640.

Note: a plain `.save` click after minting needs the panel closed (Escape) —
the fixed panel overlays the Save button; that is a driver artifact, not a
panel bug.

## Status

Complete. Full suite + PR follow.
