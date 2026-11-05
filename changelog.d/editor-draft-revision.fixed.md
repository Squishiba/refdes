- Browser editor: an unsaved edit no longer silently overwrites a change
  that landed on disk while the form was open. The form used to follow the
  file's newest revision on every rebuild, so a draft typed before an
  external change (a CLI edit, a `refdes:rebuilt`, a Navis mint) saved
  last-write-wins and the external change was gone. The first keystroke,
  body edit, pin, or link change now records the revision the form opened
  on, and Save against a moved file shows the conflict screen (keep mine /
  keep theirs / copy my draft) — the same screen a stale second tab already
  met — so nothing is lost without being shown.
