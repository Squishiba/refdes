- One dangling key, one diagnostic. A reference pointing at a surrogate key no
  live item declares was reported three ways depending on the shape of the
  reference, and only one of the three named the way out: a composite whose
  label happened to name a live item ended with
  `run `refdes keys restore REQ-PWR-002@k7f3m2q9x4a --dry-run``, while a
  composite with a stale label and a still-bare key each ended with "Check git
  history before restoring the original key or removing the reference" — the
  same trap, sent either to the command that fixes it or to archaeology
  (run-5 gate finding F8). Every local shape now gets the same explanation and
  the same remedy, with the command spelled out with that reference's own label
  and key; a bare key carries no label, so its command names the metavar
  `refdes keys restore --help` itself prints:

  ```
  ERROR   items/req.yaml:6 [REQ-002] — refines points at key '1qdn93k2nf4',
          which no item declares. The target may have been deleted or its key
          lost or changed. The label is not used as a fallback. Check git
          history to confirm identity. If it is the same item, run `refdes keys
          restore DISPLAY-ID@1qdn93k2nf4 --dry-run`, then repeat without
          --dry-run to restore the original key.
  ```

  What still varies is what is true rather than how it is said: when the label
  does name a live item, the report still adds that item's current key (or that
  it has none), which `docs/troubleshooting.md` promises. The imported-target
  ending stays different on purpose — `keys restore` writes a file in *this*
  project and cannot reach a key that lives upstream, so that shape still says
  to restore it upstream and names the docs page. Resolution itself is
  unchanged: the key resolves, the display label never does.
