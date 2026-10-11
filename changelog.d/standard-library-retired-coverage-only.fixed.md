- **The standard-library status table says what `retired` actually does.**
  The `retired` row claimed a retired requirement or bound "drops out of
  coverage and its warnings entirely". Coverage it does -- the status gate
  (`coverable_statuses: [active]`) lives in the coverage builders alone --
  but nothing else goes quiet: a retired item's own diagnostics still fire
  (a retired requirement with a dangling `refines:` is still a build
  error). The row now says coverage and coverage's warnings about it, and
  says the rest does not.
