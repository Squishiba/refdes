- The editor's server can now list the keys of a cited source file, read-only,
  as the first slice of the source-value picker
  (`docs/design/editor-source-picker.md`, §11 Slice A). A new
  `sources.list_entries()` answers "what keys does this file hold?" through the
  same reader registry, the same header rules and the same numeric grammar as
  `extract()` — there is still exactly one parser of a source file, and a row
  the picker offers is a row `refdes fetch` will accept. Three GET endpoints
  serve it, all scoped to one item: `GET /api/item/<ref>/sources` lists that
  item's own cited files a reader can read, with each one's pin state and the
  values already pinned for it; `…/sources/entries?path=&q=` lists one file's
  rows with an optional server-side substring filter; and
  `…/sources/propose?path=&key=&unit=&name=` composes the exact
  `name = source("path", "key") | unit` line and checks it against the
  evaluator's own grammar before returning it, so the browser never assembles
  one. Each path is authorized by the same
  `citations.authorize_source_path()` that `refdes fetch` and the source
  resolver already use, so a file this item has not cited is refused with that
  function's own message, and no absolute server path leaves the process.
  Listings are bounded where the file is read: above 1 MiB a listing refuses
  and names the limit, and above 5000 rows the parse stops and says so rather
  than materialising the whole file. A blank key, a ragged row, a value that is
  not a plain decimal, and a duplicated key all mark *the row* unselectable and
  are shown on it rather than hidden — and a duplicated key marks **both** of
  its rows, because offering either copy would be the tool making the choice
  the reader exists to refuse. The live value from the file and the value the
  lockfile pins are returned side by side, with a `changed` flag, so drift is
  visible before anything is committed. Reads are allowed on sealed and
  imported items: seeing where a value came from is review, and the refusal
  that belongs there is Accept's, because Accept is a body write. Nothing here
  writes anything, and the unit field has no default — with no `unit` the
  proposal returns no line at all. Accept (which writes the lockfile) and the
  editor panel are later slices.
