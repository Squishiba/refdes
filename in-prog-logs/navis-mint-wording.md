# navis-mint-wording (slice MINT-WORDING)

Task: the preview Navis panel's Mint status line disagreed with the
editor's on the K=0,R>0 case -- the preview printed
`Minted 0 key(s). R marker(s) could not be keyed ...` where the spec
(both surfaces' briefs, and the editor panel merged in #430) says the
refusal sentence alone. The fix is preview-only.

## Change

`src/refdes/serve/static/navis-preview.js::mintStatusText`: added
`if (minted === 0) return REFUSED-only;` before the K>0 branches, so
the four cases are K>0&R>0, K>0&R=0, K=0&R>0 (refusal only), K=0&R=0
(`Nothing to mint.`). One added line net; the editor
(`navis-panel.js`) untouched.

Test (red-first): `tests/test_navis_preview_actions.py` scenario 12
(`mintStatus`) -- the K=0,R>0 case now expects the refusal-only text.
Red evidence (before the fix): the stored text was
`Minted 0 key(s). 1 marker(s) could not be keyed ...` at index 2 of
the assertion; green after. All other assertions kept (K>0 with/without
R, K=0/R=0).

## Browser proof (Chromium + Firefox, 2026-11-06)

Recipe copied from the read-only `.scratch/pptr388` into
`.scratch/pptr/` (own copies of drive/ff scripts, own ports 8900/8901,
own token files, servers stopped by the PIDs started). Fixture: one
ordinary keyless marker in `note-a.md` (mintable) + one keyless marker
in a YAML list-file folded `body: >` scalar (refused by `mint_keys`);
each run rewrites `note-a.md` keyless and waits for the rebuild to
report 2 keyless rows.

- Old code (fix reverted): Chromium and Firefox both reproduce the bug
  -- second Mint click shows `Minted 0 key(s). 1 marker(s) could not
  be keyed ...` (drivers report pass=false).
- Fixed code: both browsers, first click `Minted 1 key(s). 1
  marker(s) could not be keyed -- ...`, pill drops to
  `Mint keys (1)`, second click shows ONLY
  `1 marker(s) could not be keyed -- ...` (pass=true on both).
  `notes.yaml` bytes untouched (refusal leaves the folded marker
  keyless); `note-a.md` gains exactly the spliced key.

Two harness notes (not product bugs): the panel `<details>` is closed,
so a real mouse click on the mint pill lands on the summary and
toggles it -- the drivers click the button element via
`element.click()`, which runs the same handler; and the preview page's
W1 revision poll reloads on the mint's rebuild, racing the mint
response (whose stored status rides the response's own reload) -- the
drivers abort `/api/revision` so the mint reload is the one that
lands. The poll race predates this slice and is not what MINT-WORDING
touches.

## Docs / changelog

`docs/navis.md` preview section grepped: it does not quote the
`Minted 0 key(s).` wording (it describes the K>0 shape and the refusal
sentence), so no docs change. Added
`changelog.d/navis-mint-wording.fixed.md`. Status: complete.
