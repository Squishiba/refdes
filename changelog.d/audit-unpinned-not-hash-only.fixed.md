- `refdes audit` no longer calls an unpinned citation `hash-only`. A citation
  line reads `<state>  <pin>  cited by <items>`, and for a never-fetched path
  the two columns contradicted each other: `unpinned  hash-only  cited by
  CMP-001` — reproduced by running `refdes audit` against a project citing an
  unfetched URL. "hash-only" is this project's established word for *pinned by
  sha256 with no kept copy* (`docs/markdown.md`, "Pinning vs. keeping a copy"),
  and an unpinned citation has no hash at all: `record is None` returns before
  `kept_copy` is ever read (`src/refdes/citations.py:841-851`), so the old line
  was not merely opaque, it was wrong. Unpinned rows now read `no pin`; pinned
  rows keep their existing words exactly (`hash-only`, `kept`), so anything
  parsing the pinned case is unaffected. Nothing outside the new tests reads
  that column: `git grep -n "hash-only" -- tests editors docs-site` finds only
  docstrings and the new assertions, and the site's own Copy column
  (`src/refdes/templates/references.html.j2:42`) renders a separately labelled
  table rather than this line, so it is left alone here — noted as follow-up
  in `in-prog-logs/run2-lower-severity-polish.txt`.
  `docs/cli-reference.md`'s audit sample was updated to match and now spells out
  both columns and all five states, since nothing in the docs explained the
  pair before (`docs/cli-reference.md`, "Citations").
