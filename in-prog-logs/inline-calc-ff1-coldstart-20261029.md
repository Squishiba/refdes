# ff1 cold-start failure — reproduced, root-caused, fixed (PR #388 follow-up)

## The reported failure

Orchestrator's Firefox run (results in the harness's
`.scratch/` run-ff.json): ff1 failed with
`warned=false, settled=false, text="Rail \`Vbad := 2 V * 2 = 5 V\`"` —
typed text intact, never a warn row, never an auto-fill. Re-runs passed;
Chromium cold passed.

## Reproduction (exact replication)

Kit in `.scratch/pptr/`: `cold_loop.sh` (kill serve → `dirty4.py` pre-dirty
4 V → fresh `serve_run.py` → harness writes 5 V fixture → fresh browser,
single ff1 case, instrumented net/console/panel capture), `cold_ff1.mjs` /
`cold_item1.mjs`. The orchestrator's ff.mjs flow is identical (fixture
write → poll-serve-rebuilt gate → launch), so the replication is faithful.

Counts, unfixed tree: **Firefox 6/30, Chromium 0/10.** First 10 Firefox
runs passed; runs 11-30 failed 6 times with the exact signature.

## Confirmed mechanism (from the failure net timelines, all 6 identical)

Boot-order race between app.js's two boot fetches and the watcher rebuild.
The serve answers GETs on parallel handler threads (`process_request_thread`
in serve.log tracebacks). A failure timeline (coldff2_6.json, ms from
fixture write):

- 1679 GET /api/item/DEC-001 → revision `9fe1a4ab…` (pre-swap build)
- 1749 POST /calc → 200, spans for the new build, revision `a8417dc…`
- 1762 GET /api/revision → serial=2 (post-swap) → `lastServed=2`

The watcher's build swap landed between the item handler and the revision
handler. The form carries the pre-swap revision, the baseline serial is
already the new one, so no `refdes:rebuilt` event ever fires, and
live-calc's revision guard (live-calc.js:252) silently drops every /calc
response for the life of the draft: warned=false, settled=false, typed
text intact, permanent. The window is cold-serve specific (first item-view
build is slow, the watcher tick from the harness's fixture write lands ~1s
later, right in it), first-page-load specific, and per-browser timing —
Firefox hit it 6/30, Chromium 0/10.

## Fix (app.js + live-calc.js)

1. app.js: baseline first — `poll().then(renderRoute)` replaces the
   view-first boot (`renderRoute(); … poll();`). The captured serial is
   then never newer than the view's build at issue time.
2. Recovery for the residual window (serve threads can still schedule the
   revision handler after the view handler): a revision-guard drop in
   live-calc.js now dispatches `refdes:stale-calc`; app.js re-renders the
   view (the draft survives, drafts.js) and re-captures the baseline. The
   drop itself stays silent (§3.6) — the panel never shows stale rows.

## Regression test

tests/test_editor_live_calc.py: new `appBootRace` scenario. The harness
gained a deferred-handler server model (`__serverQueue`/`__flushPath`,
handlers read the build current when RUN) so the scenario can schedule the
adversarial interleaving: view handler on build 1, revision handler on
build 2. Asserts (a) the drop happens (premise) and (b) the panel recovers
(rows render after `refdes:stale-calc`). Verified: passes on the fixed
tree; fails on a18bd7d's app.js with "the stale-model drop left the panel
silent" (rows 0).

## Verification

- Firefox cold 20 on the fixed tree: **0/20 failed** (`coldfix_*.json`).
- `tests/test_editor_live_calc.py` green; full suite 5101 passed / 2 skipped.
- Windows CI failed the first push (WinError 206: the harness outgrew the
  32k `node -e` command-line limit); fixed by running it from a tmp file.

## Status

Fixed and pushed. Counts: reproduced 6/30 ff (unfixed), 0/20 ff (fixed),
0/10 chromium. The ordering fix alone leaves the thread-inversion window
open (serve handler threads schedule independently of request order —
proved by the harness scenario, which kills the ordering-only fix), so the
`refdes:stale-calc` recovery signal is the load-bearing half.
