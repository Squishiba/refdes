# Source-picker Slice A — the service reads

Task: implement Slice A of `docs/design/editor-source-picker.md` §11 exactly as
scoped there — `sources.list_entries` + `SourceEntry`, the three read endpoints,
their authorization and caps, and the reader/endpoint tests. No UI (Slice C), no
lockfile write (Slice B), no Accept.

Branch `editor/source-picker-slice-a`, off `origin/main` (`16bbc64`).

## Status

Done and committed. Full suite green (2335 passed, 1 skipped — up from 2292 on
`main`, so +43 new tests), `ruff check --select E9,F src tests` clean. PR #49
against `main`, run 36215022947, all three jobs green. **Not merged** (Jared
reviews and lands).

CI, which is the part that actually counts:

```
success  windows-latest          3.11   2336 passed in 204.11s
success  ubuntu-latest / py3.13  3.13   2335 passed, 1 skipped in 148.65s
success  ubuntu-latest           3.11   (also runs ruff --select E9,F: "All checks passed!")
```

The Windows job is the one worth noting for this change: it is where the
`test_the_picker_never_returns_an_absolute_server_path` assertion has teeth,
because `os.path.join` yields backslashes there and `_relativise` has to
normalise the target's separators before folding the reader's diagnostics back
to a project-relative spelling. The 2336-vs-2335 difference is the existing
Windows-only citation test, not anything from this slice.

## What landed

- **`src/refdes/sources.py`** — `SourceEntry` (the six fields §5 sketches, plus
  a `selectable` property), `SourceListing`, `CsvReader.list_entries()`, the
  module-level `sources.list_entries()` dispatch, and a `max_rows` parameter on
  `_read_rows`. `MAX_LIST_ROWS = 5000` / `MAX_LIST_BYTES = 1 << 20` live here, in
  the module that reads the file, not in the HTTP layer.
- **`src/refdes/citations.py`** — `_item_specs` renamed to `item_specs` (public).
  Two internal callers, unchanged behaviour, plus the docstring saying why it is
  now public. Nothing else in citations.py was touched.
- **`src/refdes/serve/sources.py`** (new) — the read service, HTTP-free, in the
  shape `serve/edit.py` and `serve/filters.py` already have: `files_payload`,
  `entries_payload`, `propose_payload`, and `SourceRefusal`.
- **`src/refdes/serve/api.py`** — three routes in `handle()`, three thin
  handlers, and the status mapping. 118 lines.
- **`tests/test_sources_list.py`** (new, 15 tests) and
  **`tests/test_serve_sources.py`** (new, 28 tests).
- **`changelog.d/source-picker-reads.added.md`**, a §11 status update in the
  design doc, and a matching note in `browser-editor.md`'s "Source-value
  picker" section (which asserted "nothing is implemented" and would otherwise
  have become false).

## The three endpoints, and how I read the design's numbering

§11 says "the three read endpoints" and §2 counts three, but the brief's
(a)/(b)/(c) do not line up one-to-one with §2's list, so I re-read §2, §5, §6
and §7 and built the three that §2's "three read endpoints and one widened
write" describes:

1. `GET /api/item/<ref>/sources` — §2.1. The item's own cited files a reader can
   read, each with pin state and the values already pinned for it. **This is
   (b)**: the pinned-lockfile-value side.
2. `GET /api/item/<ref>/sources/entries?path=&q=` — §2.2 + §5 + §6. The rows of
   one cited file, live, with `?q=` and the caps. **This is (a)**, and each
   entry also carries `pinned` + `changed`, so the "live value labelled beside
   the pinned lockfile value" requirement is met on the row itself as §5 says
   ("the pinned value comes from the lockfile and is shown beside it").
3. `GET /api/item/<ref>/sources/propose?path=&key=&unit=&name=` — §7, named
   explicitly in the design and listed among §10's endpoint tests. **This is
   (c)**: the server composes the line, validates the unit through the same pint
   path evaluation uses, proposes a name, and refuses a collision.

So (b) is not a fourth endpoint: §5 puts the pinned value *beside the key list*,
and putting it on the row (and on the file summary) satisfies that without
inventing a route §2 does not describe. If Jared wanted a separate
`…/sources/pinned` route, it is a thin wrapper over `_lockfile` and I would
rather add it than guess now.

## The reader: three judgement calls

**`list_entries` returns `SourceListing`, not `list[SourceEntry]`.** §5 sketches
`def list_entries(path: Path) -> list[SourceEntry]`, but §6 requires "a
truncated result carries `truncated: true` and the row count that was skipped",
and a bare list cannot carry that. I kept `SourceEntry` exactly as §5 sketches
it and wrapped the return. Noted as a deviation.

**The row cap stops the parse; the byte cap refuses before opening.** §9 Q4
recommends "the cap is enforced where the file is read", and the brief asks
whether the current reader supports that "cleanly, rather than forcing a fragile
change". It does, with one parameter: `_read_rows(fh, label, max_rows=None)`
breaks out of the `csv.reader` loop once `max_rows` data records are kept and
returns `truncated` as a fourth element. One csv-reading implementation, both
callers, `extract()` unaffected (it passes no cap). The byte cap is
`path.stat().st_size` checked *before* `open()`, which is cheaper than reading
and refuses rather than truncates — §6 says "a listing refuses above 1 MiB or
5000 rows", and the 1 MiB half is a refusal in both readings while the 5000-row
half can only be a truncation (a file of 6000 rows cannot be refused *and*
listed). `test_list_entries_stops_reading_at_the_row_cap_instead_of_loading_the_file`
asserts `rows_read == 5000` on a 20,000-row file and `truncated is True`.

**"Rows skipped" is honestly absent.** Because the parse stops, the number of
rows past the cap is genuinely unknown — the payload says `truncated: true`,
`rows: 5000`, and a `truncation` string naming the cap and saying the rest was
not read. §6's "the row count that was skipped" is not satisfiable at the same
time as "the cap is enforced where the file is read"; I chose the latter, which
is also what §9 Q4 recommended, and said so in the payload.

## Endpoint shape decisions

- **A refusal is 422 with the reason verbatim**, in the edit route's
  `{"kind": "refused", ...}` vocabulary, for all three of: not cited, no
  registered reader, unselectable row. 400 for a missing `path`/`key`, 404 for
  no such item, 405 for a non-GET. The design wants the reason *shown*, not
  paraphrased, so it rides in the payload rather than becoming a routing
  failure.
- **A file the reader cannot read is 200 with `problems` and no rows**, not an
  error status. §5: "the picker shows the reader's `problems` verbatim and
  offers no rows" — a panel state, not a request failure. "No registered reader"
  is different (§10 names that test "refuses") and is a 422.
- **The pin state is the build's own `CitationStatus`**, read off `item.citations`
  after the snapshot's `verify()` — so the picker says `hash_mismatch` in the
  same words a `refdes build` warning would, with no second hash of the same
  bytes. `unpinned` when the lockfile has no record; `missing` for a pinned
  citation whose file is gone (a state the build only reaches for local
  citations, so it is worked out from `os.path.isfile`).
- **The lockfile is read through `project._source_lock`** when the loaded model
  already holds the parsed copy (`build.py:1112,1266`), else
  `citations.load_lockfile`. Read-only either way; writing it is Slice B.
- **No absolute server path leaves the process.** This one needed real care: a
  reader names the file it was handed, and what it is handed is
  `project.root + canon`, so its diagnostics carry the absolute path. Every
  `SourceExtractionError.problems` list is folded back to the canonical
  project-relative spelling before it is put in a payload
  (`_relativise`). `test_the_picker_never_returns_an_absolute_server_path` walks
  every string in six payloads — including a reader's own "no 'value' column"
  text and a refused `/etc/passwd` — and asserts none of them is absolute, starts
  with `/`, or contains a backslash.

## `?q=`

Server-side substring on the key, case-insensitive, on the reasoning that this
is a search box and not a key lookup (key matching itself stays byte-exact, in
`extract()` and in `propose`). It changes *which rows are shown*, never *what a
row is*: a duplicated or non-numeric row filtered in is still marked
unselectable, and a `q` matching nothing is an empty list, not a fallback to the
whole file. The cap counts rows **read**, so a narrow filter cannot buy a
bigger file.

## Q6, and the one place I had to choose

Sealed and imported items read fine — no gate, and
`test_the_picker_reads_a_sealed_item_and_an_imported_one` proves both against a
genuinely sealed fixture (`log-seal.yaml` on disk) and a genuine
`items.json` import. Two things I had to work out:

- An **imported** item's citations are not in `item.citations` (`verify()`
  walks `project.local_items`), so there is no build-computed pin state for one.
  The file list falls back to the lockfile, which is honest: it says `unpinned`
  because this project has pinned nothing for it, and it still reads the file.
- The **imported** item needs a real file at the declared path in the
  *importing* project for the read to succeed. That is what the fixture does,
  and it is the realistic shape: an upstream entry naming a file the downstream
  repo also has.

## Not in this slice, deliberately

- No lockfile write, no Accept, no widened `set_body` (Slice B).
- No `sourcepicker.js`, no panel, no static or end-to-end tests (Slice C).
  `tests/test_serve_static.py` is untouched; there is no JS to wire.
- No CLI (`refdes sources list`) — §11 calls it a *future* consumer of this API,
  not part of the slice.
- `citations.item_specs` is public now, but only because the read service needs
  to walk one item's own declarations. I did not add a second public wrapper.
- The unit *suggestions* (`["1", ...this item's declared units]`) are served by
  `propose` because §7 defines them as part of that endpoint's contract. They
  are labelled suggestions; there is no default and no stored per-key choice
  (§9 Q7).

## Environment gotcha worth writing down

The shared venv at `/home/jorb/work/venv-refdes` has refdes installed
**editable from `/home/jorb/work/refdes`** — a different checkout, on `main` at
`16bbc64`. Running `/home/jorb/work/venv-refdes/bin/python -m pytest` from this
worktree imports the *other* tree's `src/refdes`, and the new tests fail on a
missing `list_entries` rather than on anything real. The correct invocation here
is:

```
PYTHONPATH=src /home/jorb/work/venv-refdes/bin/python -m pytest -q
```

`PYTHONPATH` precedes site-packages `.pth` entries, so this worktree's `src`
wins. CI is unaffected: `.github/workflows/tests.yml` does
`pip install -e ".[dev]"` inside the repo it checks out. **A bare
`…/bin/python -m pytest` in this worktree is not evidence of anything** — worth
knowing before trusting a green run here.

## Test names vs §10

Every §10 name in the Reader and Endpoints groups is implemented with the name
§10 gives, except the two §10 groups that belong to later slices (Accept, and
UI/static + end-to-end). Additions beyond §10's list, because the brief and the
design both call for them and §10 is a minimum:

- `test_list_entries_stops_reading_at_the_row_cap_instead_of_loading_the_file`
- `test_list_entries_refuses_a_file_above_the_byte_cap_before_opening_it`
- `test_list_entries_caps_context_columns_and_marks_what_it_cut`
- `test_the_picker_reads_a_sealed_item_and_an_imported_one` (§9 Q6)
- `test_the_entries_endpoint_filters_server_side`
- `test_the_picker_is_not_a_write_surface`
- `test_reading_the_picker_writes_nothing_anywhere` (one `snapshot_tree` over
  the whole surface, plus a byte comparison of the lockfile across all of it)
- `test_a_no_write_server_still_offers_the_picker`
- `test_the_proposal_refuses_a_key_source_cannot_express`

## Verified, not remembered

Every claim in the code comments was read out of the tree, not recalled:
`authorize_source_path` and `classify` (`citations.py:131-183`, `481-506`),
`item_specs`/`collect`/`collect_source_uses`, `load_lockfile` and
`locked_source_value`, `verify()`'s state vocabulary (`model.py:341-367`),
`_source_drift`'s "reading the file here is diagnostic only" docstring
(`citations.py:693-705`), the §5/§6/§10 text of `calc-sources.md`, the "Reading
a value from a source file" section of `docs/math.md` (its heading is *not*
"Calc values from a repo-local file" as the brief said), the three reader
helpers in `sources.py`, `EditorApp`/`Client`/`snapshot_tree` in
`serve_support.py`, `_build_at` in `helpers.py`, and the `sealed`/`external`
fixture shapes from `test_serve_edit_http.py` and `test_imports.py`.

Two things I got wrong by reading rather than running, both caught by the suite:
the `" 1"` / `"1 "` entries in `test_sources_csv.py`'s hazard list are
**U+00A0 NO-BREAK SPACE**, not an ASCII space (`cat -A` shows `M-BM-`; ASCII
space and tab are trimmed and stay valid), and `"watts"`, `"W/s"` and `"Ω"` are
all real pint units, so the unknown-unit test uses `bananas`/`notaunit`/`Watt`.
