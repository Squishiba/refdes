- New internal module `editor_journal.py`: the transaction journal behind
browser-editor saves -- record a save's originals in
`.refdes/editor-transaction/` before touching any live file, remove it on
success, and `recover()` the originals after a crash. The save wiring and
the `refdes recover` command that reads the journal ship in this same
release.
