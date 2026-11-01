- The `navis.archive_corrupt` warning from any command that loads the
  Navis archive store now leads with the code:
  `navis.archive_corrupt: navis archive record is unreadable (...) -- it
  is skipped, not deleted; the rest of the store loads`. The code was
  already on the diagnostic and documented in `docs/cli-reference.md`,
  and the sibling `navis.archived_orphan` warning has always printed its
  code inline; the rendered line was the one place it went missing. The
  rest of the sentence is unchanged.
