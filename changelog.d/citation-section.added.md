- A citation entry can declare `section:` — the title of a heading in the
  cited PDF instead of a page number. `refdes fetch` reads the document's own
  outline (bookmarks) and records the page that title points at in
  `.refdes/citations.yaml`, next to the sha256; builds never open a PDF, so
  `build` and `check` stay offline and hermetic. The resolved page fills both
  places `page:` already did — the `#page=N` fragment on the link and the Page
  column — and an explicit `page:` wins if both are present, with a warning
  naming both when they disagree. Titles are matched exactly and
  case-sensitively after whitespace is collapsed; nothing is fuzzy, and a
  section that cannot be resolved is a `FAILED` line from `refdes fetch` and a
  nonzero exit, never a silent skip or a guessed page: no outline in the PDF,
  no entry with that title (the closest titles are offered), the title appears
  more than once (every page it is on is listed), the file cannot be parsed,
  `pypdf` is not installed, or — on `--update` — the section is gone from the
  new revision, which says so along with the page it used to be on. A failed
  lookup still leaves the pin recorded, and drops the unresolved section from
  the lockfile rather than leaving it pointing at a page the new bytes may not
  have. `section:` needs the bytes, so it is allowed on a local `path:` and on
  a remote citation with `keep_copy: true`, and refused at build time on a
  hash-only remote citation. Resolution needs the new optional extra
  `refdes[pdf]` (`pip install refdes[pdf]`); nothing else in refdes reads a
  PDF, and a project with no `section:` never imports it. A `section:` with no
  resolved page in the lockfile warns at build, and is an error under
  `--require-citations`. A page belongs to the bytes it was read out of: the
  lockfile records the sha256 the pages were resolved against, `build` checks it
  before using one, and a page resolved against different bytes warns and renders
  no page instead of linking into the wrong revision. So re-pinning a path
  re-resolves every section any item cites for it — including items outside the
  run's `--item`/`--path` scope — and drops any section that stopped being
  cited; and a local file that changed since it was pinned is not resolved
  against at all without `--update`, which is what the failure tells you to run.
  See [citing a section by name](markdown.md#citing-a-section-by-name).
