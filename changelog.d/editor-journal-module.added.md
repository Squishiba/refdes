- New internal module `editor_journal.py`: the transaction journal behind
browser-editor saves -- record a save's originals in
`.refdes/editor-transaction/` before touching any live file, remove it on
success, and `recover()` the originals after a crash. Internal building
block only: editor saves are not journaled yet and no command reads the
journal.
