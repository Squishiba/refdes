- **The remaining user-facing doc pointers now name the published docs site, not a
  repo-relative path.** `refdes init`'s candidate-parts pointer was fixed earlier;
  six other messages a user can actually reach still printed a `docs/<page>.md`
  path, which resolves only inside a git checkout — and the wheel ships no `.md`
  files at all, so those diagnostics pointed at a file that does not exist for
  anyone who installed from PyPI. They now print the published URL:
  - the imported lost-key error ends `… not typed by hand — see
    https://squishiba.github.io/refdes/multi-board.html.`
  - the unknown-key error for a `boards:` entry ends `See
    https://squishiba.github.io/refdes/multi-board.html.`, and the one for a
    `workspaces:` entry ends `See https://squishiba.github.io/refdes/workspaces.html.`
  - the four "run without `--no-write`" info lines (no key yet, and the link,
    `checks: against:`, and cross-item calc references not yet expanded) end
    `… or see https://squishiba.github.io/refdes/troubleshooting.html#surrogate-keys.`
    The design-doc path they used to cite is published as `design-keys.html`, but
    it is aimed at contributors; the user docs for surrogate keys,
    `keys restore`, and a composite nobody typed are the Troubleshooting page's
    own `## Surrogate keys` section, which is what those four are answering.
  - `refdes check --help`'s description of what a writable load writes now ends
    `(https://squishiba.github.io/refdes/troubleshooting.html#surrogate-keys)`
    instead of `(docs/design/keys.md §2)`.

  Every other word of every message is unchanged, and no behaviour changes: same
  diagnostics, same levels, same exit codes, same remedies. `DOCS_URL` moved to a
  new `refdes/docs_url.py` (imported by `build`/`keys`/`links`/`configcheck`,
  which cannot import `cli` back without a cycle) and `refdes.cli` re-exports it,
  so `from refdes.cli import DOCS_URL` is unchanged. Comments and docstrings that
  cite `docs/...` are left verbatim: those are for people reading the source, who
  are in a checkout.
