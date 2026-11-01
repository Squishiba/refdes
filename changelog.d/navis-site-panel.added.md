- **The Navis panel on the published site.** A project with Navis gets
  a fixed, read-only panel on every page of `refdes build` output: the
  active Navis (6-character key, link to the source item, text) behind
  a `Navis (n)` pill, and a Show-all disclosure that adds the archived
  ones marked `[archived]` — by their snapshot text, with a
  `marker text has changed since archived` note when the live marker
  text has moved on, and a `marker not found` label when the marker was
  hand-deleted. Restore is shown disabled with the
  `refdes navis restore <key>` command that does act (the published
  site is read-only). Like the task pane's pair, the panel's stylesheet
  and `<link>` ship only for projects that have Navis — a Navi-free
  project publishes byte-identical output — and the panel is a plain
  `<details>`: no JavaScript, no fetch, hidden in print.
  See `docs/output.md`.
