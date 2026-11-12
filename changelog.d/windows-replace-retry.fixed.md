- Writes on Windows no longer fail with "Access is denied" when another
  process (the server's poller, an editor, antivirus) briefly has the
  destination file open: the rename behind a save, a seal write, and
  every atomic store rewrite is retried for up to about a second before
  the write is refused. POSIX behavior is unchanged.
