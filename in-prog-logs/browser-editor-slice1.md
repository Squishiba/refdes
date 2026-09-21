# Browser editor — Slice 0 + Slice 1 (chunks 1-3)

Task: docs/design/browser-editor.md (authoritative; not relitigated). Slice 0,
then Slice 1 chunks (1) `refdes serve`, (2) read side, (3) source patcher +
field/body edit with draft/refuse-and-diff. Stop after (3). No Slice 2/3.
Branch ao/refdes-122/root, no push/merge.

## Slice 0 — side-effect-free load with overlay  (done)
- New `src/refdes/loader.py`: `load_tree(config, require_ids, write, overlay)`
  is the old `cli._load` pipeline moved verbatim (cli._load now delegates);
  `load_readonly(config, overlay)` = load_tree(write=False) + build(seal_write=False).
- `Project.source_overlay` (model.py) + `parse.read_source/overlay_key` :
  parse reads overlaid text instead of disk; an overlay-only path under items/
  joins `source_files`. Overlay + write=True raises (write-back addresses real
  files by line).
- tests/test_no_write.py: load_readonly byte-identical tree, overlay shows
  candidate w/o disk change, overlay-only new file, overlay+write refused.
- Note: overlay keys are `normcase(abspath)`, so on Windows an overlay-only new
  file's relpath is lower-cased. Harmless for reading; revisit for Slice 3.
