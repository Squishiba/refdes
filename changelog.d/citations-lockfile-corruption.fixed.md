- Citations: a `.refdes/citations.yaml` that cannot be read is a diagnostic
  instead of a traceback, and `refdes fetch` refuses it rather than overwriting
  it. Finding F5 of `in-prog-logs/remote-fetch-exercise.md`: the file is
  committed and hand-mergeable, so a bad merge of two branches that both ran
  `refdes fetch` is the ordinary way to get one, and
  `load_lockfile` handed whatever it parsed straight to `dict()` — a
  `citations:` holding a list produced
  `ValueError: dictionary update sequence element #0 has length 21` out of both
  `fetch` and `check`. Twenty shapes now each say what is wrong, name the file
  and the line, and say how to get the pins back (the file is committed, so
  `git checkout` restores them exactly; re-pinning re-downloads, since refdes
  sends no conditional request): merge markers, invalid YAML, a document or
  `citations:` that is not a mapping, a key that appears twice, a record that is
  not a pin record, a `sha256` that is not a 64-character hex digest, a missing
  or mistyped `fetched`/`kept_copy`/`bytes`/`sections`/`values`, or a
  `page_count:`/`page_count_error:` pair (added by #137) that is mistyped or
  carries both at once — a count and the reason there is none are opposites.
  Every field `refdes fetch` writes is accepted, including `page_count: 0`,
  which is what a document pypdf opens and finds no pages in is recorded as: a
  validator that reported its own writer's output as malformed would be the one
  failure this could not be allowed to cause.
  `fetch` leaves the corrupt file **byte-identical** — it writes this file whole,
  from the records it just fetched, so a lockfile it could not read is one it
  must not overwrite: every pin it cannot see would be replaced with nothing
  left in the tree to say so. Readers (`check`, `build`, `audit`, `revision`,
  `release`, the source picker) report the error and treat no citation as
  unpinned, which is what an unreadable lockfile does not tell them; `audit`
  exits `1` rather than silently omitting the "Citations:" section it cannot
  produce, and `index` keeps its documented exit `0` and carries the message in
  its JSON `diagnostics`. A repeated key is the shape that used to lose a pin
  with no word at all, since loading is where the repeat disappears.
