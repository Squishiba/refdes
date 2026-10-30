# run 14 release gate -- progress log

Task: USER-SIMULATION RELEASE GATE RUN 14 on branch `user-sim-run14`
(base `7acb47f`). Docs-only user simulation over the 9 user-facing surfaces
landed since run 13's base. Finished: all nine sweeps, report, evidence.

Sweeps (each in the report's section): inline spans/gates #347+#368, page
front-matter #369, keyless handles #370+#372, save journal/recover
#367+#381, XLSX picker #380, history disclosure #384, imported diagnostic
source #361, Navis slices 1+2 #382+#390, live-calc panel + font #386/#388/
#392/#394. Verdicts and findings F14-1..F14-5 in
`user-sim-release-gate-run14.md`; raw evidence in the `-evidence/` dir.

Difficulties:
- Sweep 4's "recover prints already-matched" scare was my probe's fault:
  the scripted replacement targeted a token absent from the live file, so
  the live file already equaled the original hash. Clean real-change repro
  restored correctly. Lesson: check the fixture before the product.
- Sweep 5's fixture needed sheet-scoped defined names defined with the
  qualified `Sheet1!$A$1` attr_text; plain relative destinations made the
  fetch refuse with "defined-name destination not a cell reference".
- Sweep 9's stale/Fill demo needed the span *below* its fence (the
  fence-before-span rule bit three times); span expressions are single
  names, not arithmetic; stored slots need plain quantity literals
  (`13.25 degC` for a `delta_degC` span, `0.93` for a unitless one).
- The `memo` append_only markdown type (schema overlay) was the only shape
  where the Navis mint-cost clause is observable; the shipped log type is
  `sealing: history`, so its mints never meet a build seal.
- Headless Chromium triggers the panel's undo-unavailable note; auto-fill
  stands down for the session there (documented behavior), which is why
  the 0.77 edit stayed stale with a live Fill button.
- Serves on 8755/8756 killed by PID at the end of the run.

Finished: yes. Report and evidence committed on `user-sim-run14`, PR opened.
