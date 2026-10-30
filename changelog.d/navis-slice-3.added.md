# Navis slice 3: the archive store, `refdes navis archive` / `restore`

Removing a Navi is archival. `refdes navis archive <selector>` writes the
Navi's record -- gzip YAML with the format version, the navi and item keys,
the source and text snapshot, and `archived_at` -- to
`.refdes/navis/<navi-key>.yaml.gz`, and the Navi leaves the active list;
`refdes navis restore <selector>` removes the record and the marker is
active again showing its **current** text. The two verbs write *only*
under `.refdes/navis/`: the marker stays in the body, and no item byte,
hash, seal, or history content changes (verified by differential build,
and by a test that freezes the item hashes and seals around an archive and
a restore). `--no-write` refuses both verbs, and both refuse while an
editor transaction is in flight; each store write takes the project's own
write lock and lands atomically, so concurrent archivers never corrupt the
store and an interrupted write leaves the previous state intact.

`ls` lists the active Navis; `all` is the Show-all -- active first, then
the archived rows labelled; `show` on an archived Navi prints the record's
snapshot beside the live text, with a `marker text has changed since
archived` note when the two differ (the snapshot is the archive; nothing
re-snapshots). The selector is shared by all verbs: the full key, a
6-to-10-character key prefix, or the Show-all ordinal. A record the tool
cannot read -- not gzip, not YAML, a foreign `archive_format`, a key that
is not its own file's name -- is a `navis.archive_corrupt` warning naming
the file: skipped, not deleted, the rest of the store loads. A record with
no live marker is `navis.archived_orphan`; restore refuses it (writing a
marker back would edit a body), exit 1.

The published site keeps its read-only posture: it lists archived Navis
with restore disabled.
