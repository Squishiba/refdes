- A save on Windows no longer fails with "Access is denied" when another
  process (the server's poller, an editor, antivirus) briefly has the
  destination file open: the rename is retried for up to about a second
  before the write is refused. POSIX behavior is unchanged.
