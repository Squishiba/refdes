# Editor source-value picker — design spec

Task: write `docs/design/editor-source-picker.md`, the design proposal for the
browser editor's source-value picker — the editor half of the requirement Jared
recorded in `docs/design/calc-sources.md` §1 (2026-09-19: "importing data from
an outside file should have some form of picker... he is not fond of adding
more places where a user has to manually type the things they want out of a
file"), and of the confirm-before-accept rule he added for the PDF case
(2026-09-21: the picker *tries*, then asks the author to verify before
accepting).

## Status

Finished. Design only — no behaviour changed, nothing implemented. Branch
`ao/refdes-165/editor-source-picker`, PR against `main`, **not merged** (Jared
reviews and lands).

## What landed

- **One new file:** `docs/design/editor-source-picker.md`, status *proposed*.
  Sections: problem, proposal, the confirm step, accept-as-one-operation, one
  reader in Python, path confinement, names/units/composition, non-goals, seven
  open questions with recommendations, named tests, phasing A–C + Later.
- **Two cross-reference notes** added where the requirement lives:
  `docs/design/browser-editor.md` ("Source-value picker") and
  `docs/design/calc-sources.md` §1 (a dated note above the 2026-09-21 note).
  Both point at the new doc and say plainly that its status is proposed.
- **No changelog fragment.** Precedent checked: the design-only commits for
  this same file family add none — `ac96faa` ("docs: design calc source
  values") touched `docs/design/calc-sources.md`, `docs/design/backlog.md`, and
  an in-prog-log, and no `changelog.d/` fragment. A proposed spec changes no
  author-visible behaviour, so there is nothing for `release.py` to fold.

## The finding that shaped the document

The obvious design — a button that inserts `source("…", "…")` text into the
body textarea — does not work, and neither half of the reason was written down
anywhere before this spec:

1. A `source()` line whose key is not pinned is an **item error**: the
   resolver raises (`build.py:_make_source_resolver`, "has no locked value —
   run `refdes fetch --path …`"), `_evaluate_source_line` turns it into a
   failed `CalcOutcome` (`calc.py:1442-1459`), and `build.py:1175-1203` reports
   it as a project error attributed to the item.
2. The editor's save path blocks any newly introduced item error
   (`serve/edit.py:_blocking_diagnostics`, `blocking = [d for key, d in
   after_errors.items() if key not in before_errors]`).
3. And `refdes fetch` learns which keys to extract by walking **saved** item
   bodies (`citations.collect_source_uses`, `citations.py:516-527`).

So: save-without-pinning is refused by the gate, and fetch-without-saving never
sees the key. A text-insert picker produces an item that cannot be saved.
Hence §4 — Accept is one operation over two files (item body + `.refdes/
citations.yaml`), inside the existing per-project write lock, with the lockfile
restored if the gate refuses. It is the editor's first two-file transaction,
and the spec says out loud that it is not crash-atomic before the transaction
journal lands, what the window is, and why the failure state is inert.

## Decisions taken in the spec (recommendations, all reversible)

- **No second CSV parser in the browser.** The reader gains one optional
  `list_entries(path) -> list[SourceEntry]` method, dispatched through the
  existing `reader_for()` registry, reusing `_read_rows`, `_header_column`, and
  `parse_decimal` unchanged. Row-level problems mark a row unselectable instead
  of aborting the listing (a picker showing "this row is broken, here is why"
  beats an empty panel); header-level failures stay fatal, because a file fetch
  cannot read is a file the picker must not browse. A duplicated key marks
  *both* rows unselectable — offering one would be the tool making the choice
  the reader exists to refuse.
- **Live file for the key list, lockfile for the pinned value, shown side by
  side.** Lockfile-only could not offer a key that is not already in use, which
  is the whole feature. This does not contradict "the source resolver never
  opens the CSV" — that rule is about evaluation, and the in-tree precedent for
  a diagnostic read of a live citation is `_resolve_local()` rehashing it on
  every build.
- **The browser never re-pins a changed file.** Accept extracts under fetch's
  non-`--update` policy; a hash mismatch passes fetch's own refusal through and
  directs `refdes fetch --update` to a terminal. Jared's acceptance gate for
  drift stays a terminal act where the `old -> new` diff prints.
- **The server composes the line**, and asserts it round-trips through
  `parse_source_call`. The unit field starts empty and Accept stays disabled
  until the author fills it — a default unit is exactly the silent 1000x wrong
  answer `calc-sources.md` §6 exists to prevent. Existing units in the item are
  clickable suggestions, never a pre-selection.
- **Adding a missing `citations:` entry is out of scope** and is the spec's
  honest gap: an item that cites no CSV gets an empty picker, which explains
  the same-item rule and shows the YAML to paste. Citations are in
  `NON_SCALAR_FIELD_TYPES` (`serve/edit.py:546`) and the patcher replaces scalar
  spans only. When the citations row editor lands, "cite a new file" comes with
  it for free.

## Verification done

Claims were read out of source, not remembered:

- `src/refdes/sources.py` — `SourceReader` protocol, `CsvReader.extract`,
  `_read_rows`, `_header_column`, `parse_decimal`, `reader_for`,
  `SourceExtractionError.problems`.
- `src/refdes/citations.py` — `LOCKFILE`, `authorize_source_path` (475-502),
  `collect_source_uses` (516-527), `locked_source_value` (530), `_source_drift`
  (687), `_resolve_local` (856-905), `fetch_all` (1107).
- `src/refdes/calc.py` — `SOURCE_CALL_RE`/`parse_source_call` (963-979),
  `_evaluate_source_line` (1413-1459), `source_calls_in_block` (1464),
  `_to_pint_units` (355), `quantity` (412), whole-item duplicate-name origins
  (1145-1148).
- `src/refdes/build.py` — `_make_source_resolver` (the "no locked value" raise)
  and the calc-error reporting block (1170-1203) that turns a failed outcome
  into `project.error`.
- `src/refdes/serve/{api,edit,state}.py` — `handle` routing, `_item_view` (no
  citations in the payload), `edit_state`, `_apply_edit`'s four-result mapping
  and `shown()`, `apply_edit`/`_apply_locked`/`write_lock_for`/
  `_blocking_diagnostics`/`_atomic_replace`, `NON_SCALAR_FIELD_TYPES`,
  `file_revision`, `project_inputs` (so a CLI `fetch` moves the revision and
  the poller refreshes).
- `src/refdes/serve/static/{editor,drafts,links}.js` — the body textarea, the
  `set_body` op, `setDraftBody`, and the link picker as the wiring precedent.
- Docs: `calc-sources.md` §1/§5/§6/§10/§11, `browser-editor.md` (bodies,
  drafts, diagnostic gate, security, phasing, "Source-value picker" + "PDF
  datasheet values").
- Test-name and format conventions from `tests/test_sources_csv.py`,
  `tests/test_serve_edit_http.py`, `tests/test_serve_static.py`, and
  `tests/serve_support.py:snapshot_tree`.

NOT done: no code was written, so nothing was executed beyond the repo gate
(`pytest`, `ruff`) on the branch, which is unchanged from `origin/main` apart
from three markdown files.

## Biggest open question left for Jared

Whether Accept should pin at all. The recommendation is yes (§9 Q1), because
the alternative is not simpler but broken — the only way to make a text-only
insert work is to widen the diagnostic gate to tolerate a state that is a build
error everywhere else in the tool. The virtue of the alternative is real,
though: it keeps the editor out of `.refdes/citations.yaml` entirely, leaving
the lockfile a file only the CLI writes.
