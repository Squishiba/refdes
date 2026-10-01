- Docs: `docs/getting-started.md`'s sample output is what the commands print
  again. Every command that loads a project writable now leads with
  `(minted N key(s) while loading)` — or `(minted N key(s) and rewrote M
  reference(s) while loading)` — but the page's §2 `refdes id` block and §5
  `refdes build` block still showed the pre-notice output, so the two blocks a
  newcomer checks their terminal against were each missing exactly one leading
  line. Both blocks now carry the line the command prints, checked by walking
  the page from top to bottom in a fresh git repository and diffing every
  sample block per stream (`refdes build` sends the error and the
  `build completed` line to stderr and the rest to stdout, as the page says).
  The notice gets one sentence where it first appears — loading also writes a
  `key:` into each item, a surrogate key that survives a later rename of its
  `id:` — linking to [IDs](ids.md#surrogate-keys). Two smaller drifts in the
  same pass: §1's folder listing gained the `.gitignore` that `init` now writes
  to keep its machine-specific `.vscode/settings.json` out of commits, and the
  sentence describing that file says so; §1's generated `refdes-project.yaml`
  block was already byte-identical to a fresh `init` and is unchanged. Nothing
  to do.