- The docs no longer present `follows:` as a link verb an author can write
  today. No bundled standard (hardware@1, @2 or @3) declares it, so writing
  `follows:` in an item is an unknown-link error; `docs/links.md`,
  `docs/design-log.md` and the `refdes keys adopt` entry in
  `docs/cli-reference.md` said otherwise. What the verb will do — continue a
  thread, frozen to the thread tip on first writable load — is still
  described, now as behaviour that ships with the threads work rather than
  as current authoring surface.
