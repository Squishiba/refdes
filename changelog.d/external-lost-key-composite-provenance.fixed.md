- **The lost-key error on an imported target now says the composite reference
  was written by refdes, not by you.** A downstream project that links into an
  imported item gets its bare reference expanded to `DISPLAY-ID@key` by the next
  **writable** load — `refdes check` included — so the composite sitting in your
  own file can be several commits old in a file you last touched to change a
  title. When the upstream project then loses that key and mints a replacement,
  your build fails with `constrained_by points at key '…' (labelled IFC-CAN-001),
  which no item declares`, and the old ending — `If it is the same item, restore
  its original key upstream.` — described only the upstream half of a problem
  whose local half was a tool rewrite you never asked for. It now continues
  `This composite reference was written into your file by refdes on a load, not
  typed by hand — see docs/multi-board.md.` Nothing about resolution, exit codes,
  or what you have to do changes: the key is still what resolves, the label is
  still never a fallback, and the fix is still upstream (restore the original key
  and rebuild the artifact, or accept the new one and re-point the reference). A
  lost key on a **local** target keeps its `refdes keys restore …` recipe and
  gains none of this text. `docs/multi-board.md` and `docs/troubleshooting.md`
  describe the same case, and `tests/test_keys_restore.py` reproduces the whole
  two-project scenario through the CLI and pins the wording on both branches.
