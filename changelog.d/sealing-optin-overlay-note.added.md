- `refdes check` and `refdes build` now say when the project opted an
  append-only type back into build sealing. Three lines in
  `refdes-schema.yaml` — `types: { log: { sealing: build } }` — put the
  build-time hash lock back on the `hardware@3` `log`, which ships as
  `sealing: history` (`base.yaml:298`): with the overlay an edit to an entry is
  a build error again instead of the `edited after captured` warning. Nothing
  reported that the overlay resolved (run-5 F3, friction (low)) — "The only way
  to confirm it took effect is to edit an entry and see whether the build
  fails" — and a project whose author meant to add the overlay and forgot looks
  identical to one that chose history-backed sealing on purpose. Both commands
  now print one line:

  `note: refdes-schema.yaml opts the 'log' type back into build sealing -- an
  edit to a sealed entry is a build error again, not the history-backed 'edited
  after captured' warning`

  A note on stderr, not a diagnostic: it carries no severity, joins no
  `N errors, M warnings` count, and changes no exit code. It names the type and
  the file, because the two questions an author has are "did it take effect" and
  "is this here on purpose, or did someone forget it".

  It is printed only for a type the standard had actually moved off `build`.
  `build` is the engine default, so a project declaring it for a type of its own
  — or for a subtype, which never inherits `sealing:` — has changed nothing and
  hears nothing, and neither does a project with no overlay at all, which is
  most of them. `docs/design-log.md` quotes the line where it documents the
  overlay; `tests/test_sealing_optin_note.py` pins the note, the two things it
  names, the silence without the overlay, and the unchanged summary and exit
  codes.
