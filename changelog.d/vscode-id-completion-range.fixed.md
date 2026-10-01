- The VS Code extension's id completion (after `[[` or a `PREFIX-` typed
  inline) now replaces exactly the id text already typed instead of VS
  Code's default word range, which does not treat `-` as part of a word.
  Accepting a completion while partway through typing a hyphenated id (e.g.
  `LOG-MAIN-0`) used to insert the full id after only the trailing run of
  characters since the last hyphen, duplicating the prefix
  (`LOG-MAIN-LOG-MAIN-001`); the same default range is also what VS Code
  filters the open suggestion list against as you keep typing, so entries
  that should still have matched stopped appearing past a hyphen.
