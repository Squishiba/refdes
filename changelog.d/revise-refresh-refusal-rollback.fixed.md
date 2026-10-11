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
  byte-identical to how it was found. That snapshot is also no longer gated
  to prefix renames: the refresh runs for *every* mapping kind — a `fields:`
  rename reaches it on the still-old-schema tree, since the full validation
  that would catch the moved field runs only after it — and a first-round
  review caught that with the snapshot gated, the comparison iterated an
  empty dict and the same false "rolled back." survived every
  `types:`/`fields:`/`links:`/`citation_keys:` mapping. The snapshot is now
  taken for every mapping, and the same two-referencing-files refusal is
  tested for a `fields:` rename as well as a prefix one. The printed refusal
  is unchanged — only now it is true — with one addition on a tree that
  cannot be re-read mid-rollback: a file whose re-read fails with an I/O
  error is named as left and possibly rewritten, not rolled back silently
  and not allowed to escape as a traceback over the half-applied rename.
  (`revise.apply`, findings TXN-ROLLBACK-001 and the PR #179 review.)
