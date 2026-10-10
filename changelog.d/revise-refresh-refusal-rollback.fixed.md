- `refdes revise` no longer prints "rolled back." over a half-applied rename
  when the post-rename display-half refresh is refused on its *second* file.
  Reproduced with `REQ-001` referenced from `items/dec_a.md` and
  `items/dec_b.md`, `dec_b.md` made `0444`, and a `REQ -> BUD` prefix rename:
  the refresh walks its files in path order, so `dec_a.md`'s write landed,
  `dec_b.md`'s refusal raised, and the handler rolled back — but its rollback
  restores `refresh_rewrites`, and that list was filled by code that runs only
  *after* the refresh returns. It was still empty, so nothing the refresh had
  already written was put back: `req.yaml` went back to `id: REQ-001` while
  `dec_a.md` stayed rewritten to `satisfies: [BUD-001@key]`, a structured
  composite naming the id this very operation retired and took back — the
  exact state the previous fix's changelog says it eliminates — and exit 1
  said the tree was "exactly as it was found". The comparison against the
  pre-rename snapshot now runs before the rollback as well as after the
  refresh, so the refusal path restores every write that landed; with two or
  more referencing files and a refusal on any but the first, the tree is now
  byte-identical to how it was found. The printed refusal is unchanged — only
  now it is true.
  (`revise.apply`, finding TXN-ROLLBACK-001, PR #163 review.)
