- `serve` preview pane (#481 follow-up): the pane's `data-refdes-revision`
  used to be read from disk at response time while its task rows came from
  the server's last completed build, so an external edit that changed a
  task between the two let an author tick against the old list and save
  against the new bytes with no Conflict. The revision is now the per-file
  hash the snapshot recorded when the model behind the rows was built: a
  page built from old bytes names the old revision, so the save drafted
  from it cannot silently succeed against bytes the author was never
  shown.
