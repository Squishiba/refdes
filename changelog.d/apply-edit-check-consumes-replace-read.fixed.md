- `serve`: an edit save no longer has a window in which a file that
  moved after the revision check is written over. The check of the
  edited file and of the citations lockfile is now consumed by the
  write itself: the replace compares the destination against the
  expected revision at the instant it reads the bytes it is replacing,
  so a file that moved between the last check and that read lands
  nowhere -- the save returns a 422 conflict naming the file, the
  entry pins are restored, and the file keeps the bytes that moved it
  into place. The guarantee is against writers that take the project's
  write lock (every `refdes` command and every serve save); a writer
  that bypasses the lock can still land in the last instant between
  the replace's read and its `os.replace` -- no check-and-replace on
  a plain file closes that, and this does not claim to.
