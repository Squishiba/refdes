- `refdes check --help` now says what its own "verify (but never create or
  update) append-only seals" costs: a seal exists only once `refdes build` has
  run over the entry, so an entry that has never been built has no append-only
  protection at all, however many clean `check` runs it has behind it. The
  underlying behavior is unchanged and was always correct — the fact was
  documented, the consequence was not, and a `check`-first workflow reads as
  protected when it is not. Verified against a one-entry project: two edits to
  a never-built `LOG-001` between two `refdes check` runs, both exit 0 with no
  seal file on disk; after one `refdes build`, the next edit is an append-only
  ERROR. The same consequence is now spelled out in `docs/design-log.md`'s
  `## Append-only` section, where "so it is safe in CI" was the sentence doing
  the reassuring.
