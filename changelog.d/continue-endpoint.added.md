- The editor server gains `POST /api/item/<ref>/continue`, the HTTP face of
  the continuation operation: a JSON body of `{"ticks": [[task id, wanted
  state], ...], "expected_revision": "<file revision>"}` appends an entry to
  the tip's thread carrying the tip's ticked-up task list, answering with the
  same shapes as `/edit` (200 applied, 409 conflict with the current file,
  422 refusal, 400 malformed request) under the same launch-token, Origin and
  `--no-write` gates. The task pane's Save UI reaches it in this same
  release.
