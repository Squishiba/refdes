- Docs: three run-16 gaps closed, each verified by running the current build
  first. `docs/upgrading.md` now quotes the item-level `history:` →
  `on_change:` hard error a 0.5.0 project with a `history: log` entry hits
  on its first current load (step 2's error list, with the rename that clears
  it and why `calc-rewrite` refuses until then), and the `decision`-retired
  table row names the two extra renames the "declare the four types
  yourself" remedy needs inside the copied overlay. The `refdes serve`
  section of `docs/cli-reference.md` describes the task pane as it now
  behaves: preview tick checkboxes, a per-tab unsaved draft with a count,
  Discard and a leave prompt on a writable server; built pages and a
  `--no-write` server keep the read-only pane with no tick controls at all.
  `docs/navis.md` says plainly that a marker in the body of an item with no
  `id:` is listed by no navis verb, no `refdes index`, and neither panel
  until `refdes id` mints the item an id, and `docs/getting-started.md`
  points at that fact where its own write-bodies-first flow walks into it.
