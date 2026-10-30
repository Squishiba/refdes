# Astral result-slot offsets — round 5 (PR #388)

Confirmed defect from review (live-calc.js, spanOffsets): the server's span
columns (`start`, `end`, `result_start`, `result_end`) are Python string
indices = Unicode code points within the line; JS textarea offsets and
String.slice are UTF-16 code units. `spanOffsets` added the raw column to
the JS line start, so every astral code point earlier on the span's own
line shifted the range by one unit per character. Reproduced on the real
server at the previous head: text `😀 \`a := 1 V * 2 = 5 V\`` gives
result_start=18, result_end=21 (code points), and slicing 18..21 as UTF-16
yields `" 5 "`, not `"5 V"` — Fill/auto-fill replace the wrong text.
Earlier lines were fine (line starts are computed in JS).

## Fix

One helper, `cpToUnits(line, cp)`: advance `cp` code points over the line
text counting UTF-16 units (`codePointAt(units) > 0xffff ? 2 : 1`),
clamping at the line end (a column past the last code point behaves as
textarea setSelectionRange does). Applied inside `spanOffsets` — the ONLY
place server columns are consumed, so every consumer converts: the Fill
button and the auto-fill path (both run through `spanOffsets` →
`applyRanges`/`applyOne`: `setSelectionRange`, `insertText`, the Case B
splice) and the caret-skip test (`selectionSkips` receives converted
offsets). `spanOffsets` now takes the batch `text` to slice the span's own
line. BMP characters (combining marks included) are one unit in both; only
astral code points shift. Lone surrogates: `codePointAt` on a lone
surrogate returns the surrogate (< 0x10000) → counted as one unit, which
is its UTF-16 length — Python counts it one code point: same shift, no
drift.

## Tests (red first)

tests/test_editor_live_calc.py: `cpSpan` emits CODE-POINT columns (as the
real server does; plain `spanOn` is only honest for BMP text). Six
scenarios, fixtures A1 (one emoji before the span, same line), E1 (two
emoji + a combining accent), F1 (emoji line above the span's line):
Fill (a), auto-fill insertText (b), Case B splice (c), caret boundaries
just-before/start-edge/end-edge (d), the E1 mix (e), the later-line guard
(f). RED on the previous head: Fill produced `=4 VV` (replaced `" 5 "`);
GREEN after, all suites touched green (live_calc, serve_static,
live_calc_e2e), ruff clean on the test file. Pref-leak caught while
wiring: the toggle-OFF scenarios reset
`localStorage['refdes.live-calc.autofill']` after themselves (the
DEC-FILL precedent at 907).

Nit from the Qwen approvals: appBootRace now clears DEC-BOOT's draft.
The reviewer-local commits (e07fb0c, ac1ad2d) are not on GitHub
(API shows 0 reviews), so the remaining nits (test-pin gap, log citation
drift, blank lines) are not readable from here.

## Real browser

ff.mjs/drive.mjs grew case (14): typing an emoji at the start of the
stale span's own line (DEC-001), asserting auto-fill lands the exact
`= 4 V` — the full text must byte-match. Chromium 14/14 and Firefox
15/15 pass (in Firefox the case runs after ff12's save, so the body it
types into is the single-Vbad fixture — the emoji-before-stale-span
shape is unchanged). Note the ff12 side effect: the case order means
DEC-001's on-disk body at case 14 is ff12's saved draft, not the header
fixture.

## Full suite

5101 passed, 2 skipped (unchanged baseline; the new scenarios live in
the existing node-harness test).

## Round 6 (2026-10-30, review: test hygiene + save-window drop silence)

CHANGES REQUESTED on the test file only, plus two small src items in the
amendment. Fixed: the astral fixture block had been pasted twice (second
block won, so the effective E1 was precomposed U+00E9 while comments/
messages said combining) — dead duplicate deleted, E1 kept precomposed,
E2 (base e + U+0301) added as its own scenario, labels/messages say
exactly what runs; module imports to one fixture set (verified by
exec'ing the module head, not by eye). Deleted the always-false
`formCarriedPreRebuildRevision` (the /calc body is {text, fields}; it
read body.revision). The listener-leak check is now COUNT-based, not
name-matched (renaming a handler made the old check vacuous): attach
pins 2 input / 1 blur / 1 focus (live-calc owns the only blur/focus
registrations in the served modules), post-teardown only the editor's
one input listener may remain; pinned by mutation — deleting one
`removeEventListener('input', …)` from live-calc's `detachFrom` (scratch
edit, restored) fails the check. appBootRace comments rewritten for the
fixed tree (baseline-first boot, recovery listener clears it, poll
re-captures); triple blank line removed.

Src: guard 3 no longer dispatches `refdes:stale-calc` while
`isSaving()` — mid-save the form's revision advances after saveAll's
first op, a pre-save response is legitimately stale, and re-rendering
the pane mid-save leaves saveAll on detached DOM. RED first (new
`DEC-REVSAVE` scenario: event fired during save on the previous head),
GREEN after; not-saving dispatches as before (ff1 recovery intact).
app.js comment reworded (no seq-guard credit; the loop is self-limiting
because each iteration needs a live model change). slice-b log trimmed
under 150 (merged api.js/mutation bullets; round-6 NIT about
`createLiveCalc` for fields-only editors skipped by review, noted
there). Full suite 5101 passed/2 skipped; Chromium 14/14, Firefox
15/15 at this head.
