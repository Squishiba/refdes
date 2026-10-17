# R11-F1 — warn on an unclosed fenced code block in an item body

Finding (user-sim run 11, moderate): a fenced example whose closing fence
line carries an info string (```yaml ... ```yaml) is unclosed markdown — a
closing fence cannot carry an info string — so the `---` inside it splits
(unclosed openers protect nothing, per #331) and the pasted front matter
becomes a live phantom item with `refdes check` reporting 0 warnings. Goal:
make that loud without changing what parses.

## What was done

- `src/refdes/parse.py`: the warning is emitted from the existing fence
  state machine in `_split_and_fences` (no second scanner). The `opener`
  tuple gained its 0-based line; at end of walk, `opener is not None` adds
  one `(message, opener_line)` pair to `fence_warnings` — the same
  (lowest-severity) channel #322/#331 use, so loader/`check`/`build`/`index`
  parity is by construction. When the file's last non-blank line matches the
  new `_FENCE_INFO_TAIL_RE` (3+ fence chars then text, closer than the
  opener), the message names it with its line as the likely cause. Front
  matter stays opaque (no opener opens there), a closed `~~~` fence
  containing ``` lines is silent, closing fences with trailing spaces close.
- Splitting untouched: the new code appends to `warnings` only, after
  `split_idx.extend(pending)`.
- Message first said "keeps splitting as item front matter"; "front matter"
  collides with the #332 inert-sweep test filter (`"front matter" in line`)
  and tripped 2 tests whose fixtures legitimately end with an unclosed
  opener. Reworded to "any `---` under this line splits as an item" — the
  #332 sweeps keep asserting their own diagnostic, unchanged.
- Tests: 9 new in `tests/test_fenced_frontmatter_split.py` (unclosed single
  item; unclosed + later items, split pinned; closer-with-info-string names
  cause; ~~~-contains-``` and ```-contains-~~~ mixes; closed pair silent
  incl. trailing-space closer; list-item opener; loader e2e file:line;
  check/build parity via the CLI). Two existing tests asserted the old
  silence for unclosed fences (`test_unclosed_fence_opener_protects_nothing`,
  `..._loads_silently`) — updated to keep the split pins and pin the new
  warning. Parity test needs `--no-write` (key minting rewrites the file
  mid-load and shifts the reported line) and an `items/board-a/` path (the
  `log` type declares its own `board` field, so only the path scopes it).
- Docs: one sentence each in `docs/authoring.md` (fences paragraph) and
  `docs/troubleshooting.md` (front-matter-block entry). Changelog fragment
  `unclosed-fence-warning.added.md`.

## Verification

- Differential proof: `.scratch/r11f1/fuzz2.py` (copy of the x1probe
  harness), `origin/main` src via `git archive` into `.scratch/main-src`.
  Seeds 2, 1, 3 × 6000 files: blocks+errors (first two fields) identical in
  all 18000; warning counts rise on ~2900/6000 per seed (pool is full of
  unclosed fences — expected, it is the change).
- Repo's own items: `refdes --no-write ... check` on this project, main src
  vs new src — output byte-identical (20 items, 1 pre-existing error, 2
  pre-existing warnings; 0 new warnings).
- Full suite: 4116 passed, 2 skipped. `ruff check <touched files> --select
  E9,F` clean. `test_docs_anchors` passes.
- Manual: the R11-F1 file through the CLI prints
  `WARNING items/unclosed.md:7 — unclosed fenced code block: ... the file
  ends with '```yaml' (line 14), ...` and stays at 0 errors.

Finished: complete. Split behavior byte-for-byte unchanged (proven above);
the phantom-promotion symptom (and the `refdes id` key minting into the
example) remains by design — it is #331's documented "protects nothing"
fallback — what is new is that it is announced.
