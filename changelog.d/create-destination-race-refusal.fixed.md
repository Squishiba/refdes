- `serve`: a create that appends to an existing destination no longer
  silently replaces bytes another writer landed while the create was
  being planned. The final check of the destination now consumes the
  very bytes the replace reads to protect them, so a destination that
  moved between this create's plan and that read writes nothing and
  reserves nothing: the creation re-plans from a fresh load, and a
  destination that keeps moving ends as a 422 naming the file and
  asking for a retry, not a 200 over the top of what someone else
  wrote. The guarantee is against writers that take the project's
  write lock (every `refdes` command and every serve save); a writer
  that bypasses the lock can still land in the last instant between
  the replace's read and its `os.replace` -- no check-and-replace on
  a plain file closes that, and this does not claim to.
