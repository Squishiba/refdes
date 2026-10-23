- Stale `Status:` lines on shipped design docs now say what landed, each
  verified against git history (`git show -s --format=%s`, `gh pr view`):
  `editor-image-upload.md` (all of §17, #50/#52/#53/#60/#63/#69) and
  `editor-source-picker.md` (slices #49/#59/#62, PDF read #57, user guide
  #349) move proposed -> implemented; `editor-vscode-adapter.md`
  (V−1 #58, V0 #66, contract tests #108) to partially implemented, V1/V2 and
  every webview still design only; `inline-calc.md` names slice 1 #333, the
  message fixes #341, the grammar fixes #351 and the release gate #345, with
  the hash-format-6 slice #347 still in review; `living-notes-plan.md`
  (H1 `d84e123` .. H8 #193, optional H9 not landed) proposed -> implemented.
  `item-search-hover.md` is left alone — no code has landed, so its
  "no slices scoped, no code written" is already true.
