- When a duplicate `id:` key makes a composite reference in another file
  follow the surviving item, the run now names the file it repointed. An
  entry whose `id:` is written twice keeps the last id, and a
  `DISPLAY-ID@key` reference to the lost id resolves through the key at the
  surviving item, so the plain `check` load refreshed its stale label on
  disk — in a *different, clean* file, named nowhere in the output; the
  only trace was the count-only `(rewrote 1 reference(s) while loading)`
  line. Such a load now also warns, once per affected file, naming it, the
  old and new target text, the file whose duplicate `id:` caused it, and
  the undo (fix the duplicate line, then restore the reference text), and
  says plainly that the rewrite already happened. Under `--no-write`
  nothing is rewritten, so the warning says nothing. Whether the repoint
  itself should happen at all is unchanged and open.
