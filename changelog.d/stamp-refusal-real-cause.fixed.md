- `refdes revision`/`release` now report a stamp refused by a full disk as a
  full disk. The stamp refusal (`error: cannot write .refdes/baselines/<name>.yaml …`)
  and the revision engine's carried-baseline refusal hardcoded the
  `(read-only tree?)` marker and the "make the tree writable" remedy, so
  ENOSPC and friends were answered with a permission hunt on a fully writable
  tree — the same false hint DIAG-WORD-008 (PR #230) removed from `id`'s
  write-back, in the two destination refusals that change did not reach
  (run-7 finding F14). Both refusals now pass the caught `OSError` through
  `model.destination_refusal`: the marker stays for a failure a read-only tree
  could produce (byte-identical, so CI filters keep matching), and for the
  rest the parenthetical is the operating system's own reason —
  `(No space left on device)` — with a remedy that says fix the reported
  failure. The seal-carry refusal of `rename`/`calc-rewrite`/`standard
  upgrade` keeps the marker: it is reported by `seal.save_seals` as a
  boolean, with no `OSError` to read a cause from. Pinned by injection tests
  in `tests/test_run7_f13_f14_f16.py`.
