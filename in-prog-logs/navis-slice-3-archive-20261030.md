# Navis slice 3: archive store, `archive` / `restore`

Task (from in-prog-logs/navis-design-20261025.md §5, §7.3, §9, §12): the
archive store under `.refdes/navis/` and the two write verbs, preserving
the hard invariant — archive/restore write only store records, never an
item source. Red-first: `tests/test_navis_archive.py` (34) +
`tests/test_navis_archive_cli.py` (18) were written and captured failing
before the module existed.

## What landed

- `src/refdes/navis_archive.py` (new): gzip YAML records
  `.refdes/navis/<navi-key>.yaml.gz`, `archive_format: 1` with
  `navi_key`, `item_key`, `source: {file, line}`, `text`, `archived_at`.
  Store is pure-filesystem: it never imports the loader.
  `load_records(root) -> (records, diagnostics)`; every unreadable record
  (not gzip, not YAML, not a mapping, foreign `archive_format`, bad key
  grammar, key not its own file's name, missing `text`/`source`) is a
  `navis.archive_corrupt` warning naming the record's project-relative
  path — skipped, never deleted; the rest of the store loads. Dot-prefixed
  temp files are skipped as not-yet-committed.
  `archive_record` / `restore_record` run under `project_write_lock`,
  refuse when `.refdes/editor-transaction/` exists (`JournalPending`), and
  land every write as temp file + `os.replace` (0600->final mode). A
  gzip write that fails mid-stream deletes the temp and re-raises.
- `navis.projection(project)` merges marker rows with store records:
  active rows first (file/line order) then archived rows; rows carry
  `archived`, `snapshot {text, archived_at}`, `text_changed` (archived
  marker whose live text differs — show prints the snapshot plus a
  "marker text has changed" note, never re-snapshots). Records with no
  live marker are orphan rows (`source.marker_found: False`).
  `navis.archive_diagnostics(project)` = store diagnostics + one
  `navis.archived_orphan` warning per orphan; `build.py` appends it so
  `build`/`check`/`serve` see it too.
- CLI: `navis archive|restore <selector>`, selector shared with `show`
  (full key → 6..10-char unique prefix → Show-all ordinal). Exit posture:
  clean 0; selector names nothing 2; archive-already-archived 0; restore
  of a non-archived Navi 2; restore of an orphan 1 (refuses — writing a
  marker back would edit a body); `--no-write` refusal 2; keyless marker
  2 (names the minting writable command); journal in flight 2; `OSError`
  → "could not write", exit 2, no traceback. `ls` lists active rows;
  `all` is the Show-all (active, then `[archived]`); `show` on an archived
  Navi adds the archived lines.
- docs: cli-reference.md navis section rewritten (console block captured
  from a real scratch-project run, verb table incl. archive/restore,
  corrupt/orphan posture); markdown.md gained the "removal is archival"
  paragraph; anchor links updated to the renamed section heading
  (`tests/test_docs_anchors.py` pins the site slug, which is
  `refdes-navis-ls-all-show-archive-restore` — the docs site slugifier
  collapses the ` / ` separators, unlike GitHub's).

## Verified

- New suites: 34 + 18 green. Slice 1/2 suites (`navis`, `navis_cli`,
  `navis_mint`, `navis_matrix`): 395 green.
- Full suite green: `python -m pytest -q -p no:cacheprovider` →
  5594 passed, 2 skipped.
- Invariant tests: item bytes/hashes/seals/history content frozen across
  archive+restore (incl. sealed append-only entry); differential build of
  a Navi-free project vs `origin/main` tree is byte-identical with and
  without a pre-existing `.refdes/`.
- Concurrency: two processes archiving the same Navi → one record;
  distinct Navis → both records; kill-mid-write (real SIGKILL of a
  subprocess during `os.replace`) → store unchanged, no temp files, CLI
  exits 2 "could not write", no traceback.
- Huge marker (1 MB single line) archives and restores.

## Notes / decisions

- Keyless markers cannot be archived — the record is named by the key.
- Ordinals are race-sensitive by design; the docs say the key is the
  stable name. Concurrency tests use full keys.
- Writable loads mint item keys too, shifting marker lines; invariant
  tests read live scan positions, not fixture literals.
- `cli.py:3:1 I001` is pre-existing on `origin/main` and left alone per
  AGENTS.md; ruff is clean on every file this slice touched.

Status: complete. PR title/body/decisions per the task brief.
