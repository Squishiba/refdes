- `refdes serve --port P` can now be relaunched on its own port while the
  previous launch's sockets are still finishing their close. A listener bound
  without `SO_REUSEADDR` refuses its own port for as long as one of its old
  accepted connections still lingers in TIME_WAIT (up to a minute), so
  crashing or killing a serve that had a page open -- then starting it again
  on the same `--port`, the ordinary scripted recovery -- could fail with
  `cannot listen on 127.0.0.1:<port>: Address already in use` for a minute
  after nothing actually held the port. The bind now allows that reclaim
  (POSIX only; on Windows the flag means bind-over-anyone, so there the
  strictness stays). A port that is genuinely held -- by another live serve,
  or by any other process -- is still the same refusal and exit 2, though on
  macOS/BSD (standard BSD `SO_REUSEADDR` semantics, as in Python's own
  `HTTPServer` default) a listener on the wildcard address does not block a
  loopback bind.
