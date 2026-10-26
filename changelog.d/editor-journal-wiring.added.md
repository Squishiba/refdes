- `serve`: every editor save is now journaled. Before an edit or create
replaces an item file, the save records that file's exact current bytes (and
its absence, for a created file) in `.refdes/editor-transaction/`, and
clears the journal once the save has landed. A process killed between those
two points leaves the journal visible, and the project is then gated: every
project-loading command -- `check`, `build`, `index`, `ls`, `id`, `fetch`,
`audit`, `schema`, `rename`, and `serve` itself -- refuses with exit 2 and a
message naming `refdes recover`, which restores every journaled file to the
bytes recorded before the save touched it (deleting files the save created),
verifies each rolled-back replacement against the manifest's sha256, and
clears the journal. A corrupt manifest is refused with exit 2 and kept as
found, as is a live file matching neither recorded hash or missing from
disk -- recover changes nothing when the live state is one the
transaction does not describe; a journal directory with no manifest at
all recorded no transaction and is cleared with exit 0; `recover` on a
clean project exits 0 and writes nothing, and under
`--no-write` a pending journal is a refusal (there is no read-only
recovery). Journal scope is the item files: the accept pair's
`.refdes/citations.yaml` pin and a create's `.refdes/ids.yaml` reservation
are outside the journal's control-namespace rule, so a kill between the
pair's two writes leaves the pin inert and recovery restores the item half
to its complete old state. A save whose journal cannot be armed is refused
with nothing written -- an unwritable `.refdes/`, a target path the journal
refuses (a Windows device name, a colon, a path that escapes the root
through a symlink), a journal left pending from an earlier kill -- an
unarmed save is the kill-with-no-recovery the journal exists to end. A
reported write failure clears the journal only when the disk says nothing
landed; over a write that landed in part, the journal stands and the
refusal names `refdes recover`.
