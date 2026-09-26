Status: **proposed** (2026-09-25). Design only — this document changes no
behaviour. It settles the editor half of the requirement recorded in
`docs/design/calc-sources.md` §1 ("Requirement: a picker for importing values
from an outside file", Jared, 2026-09-19) and is cross-referenced from
`docs/design/browser-editor.md`, "Source-value picker".

Update: §9 Q2 is answered — Jared decided on 2026-09-26 to go with the
simplest option (A), to keep this moving rather than block on it: an item
that cites no CSV yet gets the empty-state message and the exact YAML
snippet to paste in by hand (§8); no citation-write patcher op ships with
this. A narrower middle option — a patcher op that writes only a bare
`path:` entry, short of a full citations row editor — was considered and set
aside for later rather than built now.

# Editor source-value picker

## 1. Problem

`source()` has shipped. An author can write

```calc
eff = source("analysis/power-budget.csv", "tps62913_half_load_eff") | 1
```

and the value is extracted by `refdes fetch`, pinned in the citation lockfile,
and resolved from the lockfile at every later build
(`docs/design/calc-sources.md`; `src/refdes/calc.py:963-979`, `1413-1459`).

What has not shipped is any way to *author* that line without typing it. To
write one today the author must, from memory, produce two strings that have to
be byte-exact:

- the citation path, exactly as it is written under `citations:` on **this**
  item — `citations.authorize_source_path()` rejects a path the item does not
  itself cite, and a path on another item does not authorize this one
  (`src/refdes/citations.py:475-502`); and
- the key, exactly as it appears in the `key` column of that file — the reader
  selects rows by exact key match, never by position, prefix, or label
  (`src/refdes/sources.py:109-180`).

Both strings are invisible in the editor. `GET /api/item/<ref>` returns fields,
links, body, coverage and diagnostics (`src/refdes/serve/api.py:200-259`) — it
does not return the item's citations at all, and citations are a collection
field, which the editor marks read-only
(`src/refdes/serve/edit.py:546`, `NON_SCALAR_FIELD_TYPES`). So the author's
loop for one picked value is: leave the browser, open the CSV, find the row,
copy the key, open the item YAML to copy the path, come back and type it.

Jared asked for a picker precisely to end that
(`docs/design/calc-sources.md` §1): *"he is not fond of adding more places
where a user has to manually type the things they want out of a file, and
intuition and ease of use are key."* What the picker lists, how a key is
chosen, and where the resulting text is emitted were left to this document.

There is a second, harder requirement, and it is the one that shapes the whole
design. It comes from the same place and it is about the PDF case
(`calc-sources.md` §1, Jared, 2026-09-21; repeated verbatim in
`browser-editor.md`, "PDF datasheet values"): the picker **tries** to extract
the value, then **asks the author to verify it before accepting**. Nothing is
pre-selected; accepting is a deliberate step. The failure it guards against is
the silent plausible-but-wrong number — mA read as A, the wrong min/typ/max
column.

This document specifies the CSV picker against that same confirm-before-accept
shape, so the PDF reader arrives as one more source type behind a UI that
already refuses to accept on the author's behalf, rather than as a new
interaction to relearn.

### Why this is not just a text insert

The obvious design — a button that drops `source("…", "…")` text into the body
textarea — fails the first time it is used, and the reason is worth stating
because everything else follows from it.

The editor's save path runs the diagnostic gate: a candidate that introduces a
new item error is refused (`browser-editor.md`, "Diagnostic gate";
`src/refdes/serve/edit.py:_blocking_diagnostics`). A `source()` line whose key
is not yet pinned **is** an item error — the resolver raises, and
`_evaluate_source_line` turns it into a failed `CalcOutcome`
(`src/refdes/calc.py:1442-1458`). And extraction belongs exclusively to
`refdes fetch` (`calc-sources.md` §5), which discovers keys by walking
**saved** item bodies (`citations.collect_source_uses()`,
`src/refdes/citations.py:516-527`).

So the two halves of the naive design are each other's blocker:

- save the body without pinning → the gate refuses the save;
- fetch without saving the body → fetch never learns the key exists.

A picker that only inserts text produces an item that cannot be saved. The
accept step has to write the body **and** the lockfile, together, or it has to
not exist.

## 2. Proposal

Three read endpoints and one widened write, plus a picker panel in the item
editor.

1. **The picker lists the item's own cited files** that a reader can read,
   with each one's pin state and the values already pinned for it. Nothing
   else is listable — see §6.
2. **Picking a file lists its keys**, read by the existing Python CSV reader
   through one new reader method. The browser receives parsed rows; it never
   parses a file (§5).
3. **Picking a key opens a confirm step**, which is the design's centre of
   gravity: it shows the raw cell text, the canonical decimal, the row's line
   number, the row's other columns as context, the value the lockfile pins (if
   any) and whether that differs from the file, the composed calc line, and a
   unit field with no default. The author chooses the unit and confirms. Until
   then nothing has been written and nothing has been inserted (§3).
4. **Accepting writes two files as one operation**: the item body (through the
   existing `set_body` op, revision check, and conflict path) and the lockfile
   record for that path — with the value taken from the Python reader, never
   from the browser. If either half fails, neither stands (§4).

The author never types a path, never types a key, never sees a value the tool
did not read, and never has an insertion happen without being asked.

```
Insert source value → [file] → [key] → [confirm: value, context, unit] → Accept
                                                                     │
                                              body draft + lockfile ─┘  (one op)
```

## 3. The confirm step

"Try, then ask" means the tool does all the reading and all the composing, and
the author does exactly one thing: decide whether what it found is what they
meant. The confirm panel shows, in this order, because that is the order the
questions arrive in:

| Shown | Source | Why it is on the panel |
|---|---|---|
| The key, verbatim | reader | it is the identity being committed |
| The raw cell text, verbatim | reader | `1850` and `1.85` are different decisions; the canonical text alone hides a formatting surprise |
| The canonical decimal | `sources.parse_decimal` | what will actually be pinned |
| Line number in the file | reader | the author can go look |
| The row's other columns, name → text | reader | this is where "half load, 12 V in" tells them they picked the right row |
| Pinned value, and `changed` when it differs from the file | lockfile + reader | the drift the build already warns about, visible *before* the commit instead of after |
| The composed calc line, monospace, uneditable here | server | see §7 — the server composes it, so the browser never learns the grammar |
| Unit field, empty, no placeholder default | author | §7 |
| Variable name, proposed, editable | server proposal + author | §7 |

Nothing is pre-selected. The Accept button is disabled until the unit field has
a value, and it is the only way anything reaches the body.

**What "verify" means for a CSV, honestly.** For a CSV there is no extraction
ambiguity to resolve: the key match is exact or the row is not offered, and the
value is a plain ASCII decimal or the reader raised. So the CSV confirm step
verifies *meaning*, not *reading*: is this the row I meant, and is the unit I am
about to declare the unit that column is really in. That is the 1000x trap
(`calc-sources.md` §6), and it is exactly the thing no parser can catch — which
is why the unit field has no default and why the row's context columns are on
the panel rather than one click away.

The PDF slice reuses this panel and adds the harder half — the highlighted cell
on the rendered page, the min/typ/max candidate list, the visible
"could not read this page" failure. The panel's contract, "the author confirms
before anything is accepted", is set here so that slice does not have to
re-litigate it.

## 4. Accept is one operation over two files

Acceptance writes the item file and `.refdes/citations.yaml`. It is not two
requests; it is one `POST /api/item/<ref>/edit` carrying the body op plus the
keys to pin. Reasons, in order of weight:

- **The gate forces it.** §1: a body with an unpinned key is a new item error,
  so the save cannot pass on its own.
- **One mutation entry point is a stated invariant** of the editor
  (`browser-editor.md`, "Permissions are out of scope for v1 — with one
  seam"): *"No handler writes a file on the side; every change goes through a
  single apply-operation call."* A separate `/api/fetch` endpoint would be a
  second writer of tracked project state, outside the item transaction, with
  its own revision story.
- **The author must not be able to half-commit.** A pinned value with no line
  naming it is dead state in a tracked file; a line naming an unpinned value
  is an item that will not build.

The sequence, inside the existing per-project write lock
(`serve/edit.py:199-209`):

1. Load the before-project, resolve the item, check `expected_revision`,
   check sealed — all unchanged from today's `_apply_locked`.
2. Plan the body patch (`SetBody`, unchanged), producing `new_text`.
3. For each `{path, key}` the request names: re-authorize with
   `citations.authorize_source_path()` against the **server's** copy of the
   item, then extract that key from the live file with the reader. The request
   carries paths and keys only — never a value (§5, §6).
4. Write the lockfile atomically: the path's record gains `values: {key:
   {reader, value}}` in the shape `calc-sources.md` §5 already fixes, staged in
   memory and replaced whole, so a partial value set never lands.
5. Load the candidate with `overlay={item_path: new_text}` — now reading the
   lockfile that was just written, so the new `source()` line resolves and the
   delta gate judges the real candidate.
6. Run the delta gate. Pass → write the body atomically → `Applied`, and
   `state.refresh()` as today. Fail → **restore the previous lockfile bytes**
   and return the gate's `Invalid` diagnostics unchanged.

Step 6's rollback is the first two-file transaction the editor performs, and
`browser-editor.md` puts the general transaction journal in "a later slice".
This does not wait for it, and does not pretend to be crash-atomic: the window
is one `os.replace` wide, the recovery is `_restore` of bytes held in memory,
and the failure mode if the process dies inside the window is a lockfile that
pins a key no item names — which is inert, visible in `git status`, and
cleaned by the next `refdes fetch`. That is stated rather than papered over:
when the journal lands, this operation becomes its first client.

**The browser never re-pins a changed file.** Acceptance extracts under
fetch's existing non-`--update` policy (`calc-sources.md` §5's command
matrix): if the file's hash does not match its pin, plain fetch refuses and
directs `--update`, and the picker passes that refusal through verbatim —
"this file changed since it was pinned; run `refdes fetch --update --path …`
in a terminal". Re-accepting a changed source value is Jared's acceptance gate
(`calc-sources.md` Q2, decided 2026-09-21: drift warns loudly, `fetch
--update` is the acceptance) and it stays a deliberate act in a terminal where
the `old -> new` diff is printed. A file with no record at all is different
and is allowed: fetch pins the hash and extracts in one write, and so does
accept.

## 5. One reader, in Python

The browser does not parse CSV. Not "should not" — there is no second parser.

The reason is not code size, it is that the two parsers would disagree, and the
disagreement is the silent-wrong-value class this project keeps finding.
`src/refdes/sources.py` already encodes the whole contract: strict `csv` with
`strict=True`, UTF-8 with an optional BOM, byte-exact `key`/`value` headers,
exactly one of each, ragged rows rejected, blank keys rejected, duplicate keys
an error rather than first-wins, and a value grammar that is ASCII-only and
rejects `100 mW`, `1,000`, `1_000`, non-ASCII digits, and `1e999999`
(`sources.py:75-180`; the hazard list is §3 of `calc-sources.md`, and
`tests/test_sources_csv.py` pins each case). A JS parser would be a second
authority on which rows exist, and the picker would offer rows the fetcher
refuses, or hide rows it accepts.

So the reader gains one capability, and the picker consumes it:

```python
@dataclass(frozen=True)
class SourceEntry:
    key: str
    raw: str          # the value cell exactly as written
    value: str        # canonical decimal text, or "" when unparseable
    line: int         # physical line, the same numbering extract() reports
    context: tuple[tuple[str, str], ...]  # the row's other columns, header → cell
    problem: str      # "" | why this row is not selectable

def list_entries(path: Path) -> list[SourceEntry]: ...
```

`list_entries` is an optional method on the `SourceReader` protocol
(`sources.py:60-68`); `sources.list_entries()` dispatches through the same
`reader_for()` registry (`sources.py:233-243`) and raises
`SourceExtractionError` when the reader does not implement it, so a future
reader that cannot enumerate is an error, not a silent empty list.

`CsvReader.list_entries` reuses `_read_rows`, `_header_column`, and
`parse_decimal` unchanged — same header rules, same line numbering, same
numeric grammar. The one deliberate difference from `extract()` is failure
policy, and it is a display decision:

- **Header-level failures are fatal**, exactly as in `extract()`: no `key` or
  `value` column, a duplicated header, a malformed CSV, an empty file. The
  picker shows the reader's `problems` verbatim and offers no rows. A file that
  fetch cannot read is a file the picker must not browse.
- **Row-level problems mark the row unselectable** and are shown on it, rather
  than aborting the listing: a blank key, a ragged row, a value that is not a
  plain decimal. `extract()` raises on these because it was asked for a value
  and refuses to invent one; the picker is not being asked for a value, it is
  showing an author their own file, and "this row is broken, here is why" is
  more useful than an empty panel.
- **A duplicated key marks *both* rows unselectable.** `extract()` refuses a
  duplicated key rather than picking first or last (`test_csv_source_duplicate_key_errors_instead_of_first_or_last_wins`),
  so the picker must not offer either copy — offering one would be the tool
  making the exact choice the reader exists to refuse. Both rows are listed,
  both are marked, and the diagnostic says what to fix.

Context columns are capped — at most 8 columns and 80 characters each, with an
explicit `…` when truncated — because they exist for human recognition, not as
a data channel.

**The live file, not the lockfile.** The key list comes from the file on disk;
the pinned value comes from the lockfile and is shown beside it. This is
deliberate and it does not contradict "the source resolver never opens the CSV"
(`calc-sources.md` §5): that rule is about *evaluation*, and this is neither
evaluation nor a build. The precedent is explicit in the codebase: `_resolve_local()`
rehashes the live local citation on every build for drift diagnostics
(`citations.py:856-905`), and `_source_drift()` opens the changed source file
to describe the gap — its own docstring: *"Reading the file here is diagnostic
only. The value a calc row evaluates to came from the lockfile before this ran
and nothing below can alter it"* (`citations.py:687-699`). A read-only listing
for a human who is deciding is the same category. What it must never become is
a value source: the number that gets pinned comes from `extract()` inside the
accept operation, and the number on the panel is labelled as what it is.

Reading live is also the only thing that works: the point of the picker is to
offer keys that are *not yet* pinned, and a lockfile-only picker could only
offer keys already in use.

## 6. Path confinement

The picker can make the server read a file. That is the one genuinely new
capability in this design, and `browser-editor.md`'s security section says
plainly: *"Do not expose a generic file-read endpoint."* These endpoints are
not one, and the difference is enforced server-side in four places, none of
which trusts the client.

**Only a file this item cites.** Every request names an item, and the path is
validated by `citations.authorize_source_path(project, item, path)` — the same
function fetch uses to decide what to extract and evaluation uses to decide
which record to read (`citations.py:475-502`). One rule, three callers, so the
picker can never be authorized for something the fetcher would refuse. A path
cited by another item is refused with that function's own message.

**Canonicalization is not reimplemented.** `authorize_source_path` delegates to
`citations.classify()`, which already rejects an absolute path, a backslash, a
URL scheme, a `..` that escapes the root, and a symlink that resolves outside
it. The picker passes the client's string to that function and uses only the
canonical path it returns; it never joins a client string to a filesystem root
itself. The list endpoint returns canonical paths, and the keys endpoint
re-authorizes the path it is given rather than trusting that it came from the
list.

**Only a file with a registered reader.** Dispatch is `reader_for()` by
extension (`sources.py:233-243`): today that means `.csv`. A cited `.xlsx`,
`.pdf`, `.py`, or extensionless file is reported as "no source reader for
this file type" — the reader's own error, verbatim — and is not opened. There
is no fallback to a text parse, which is the registry's existing posture.

**Bounded, and it says so.** A listing refuses above 1 MiB or 5000 rows and
names the limit; a truncated result carries `truncated: true` and the row count
that was skipped. The cap exists so one large CSV cannot pin the server's
thread, not as a security boundary.

On top of that, the inherited posture applies unchanged and is worth naming
because these are new routes: the launch token is required on reads as well as
writes (decided in `browser-editor.md`, Security), the Host and Origin checks
are the same ones every other `/api/` request passes, responses are
project-relative paths only — the `shown()` posture in
`serve/api.py:310-315` — and no absolute server path leaves the process.
Writes keep `--no-write`'s 403: on a read-only server the picker browses and
offers, and Accept is refused with the existing message.

## 7. Names, units, and who composes the line

**The server composes the text.** `GET /api/item/<ref>/sources/propose` returns
the exact line to insert. `SOURCE_CALL_RE` is the grammar
(`calc.py:963-976`) — two string literals, no escapes, a quote inside a path or
key is not supported — and a browser that assembled the string itself would
need its own idea of that grammar, which is the §5 problem in a smaller hat.
The response round-trips: the server asserts `parse_source_call(line)` returns
the `(path, key)` it was given, so a composition bug is a 500 at compose time
rather than an item that will not parse later.

**The unit is never guessed and never defaulted.** `calc-sources.md` §6 is
decided: the file supplies a bare dimensionless decimal, the declaration owns
the unit, and `| 1` says "dimensionless" out loud. The picker's unit field
starts empty, and Accept stays disabled until the author fills it. Units
already used in this item's other calc lines are offered as clickable
suggestions, next to `1` — suggestions, never a pre-selection, because a
default unit is precisely the silent 1000x wrong answer. The server validates
the unit through the same pint path evaluation uses (`calc._to_pint_units`,
`calc.quantity`, `calc.py:355`, `412`) so an unknown unit is refused on the
panel instead of becoming a failed calc row after save.

**The variable name is proposed, editable, and checked.** Derived from the key
(lowercased, non-alphanumerics to `_`), editable, and validated against the
names this item already assigns — whole-item duplicate detection exists in the
evaluator (`calc.py:1145-1148`), so a collision is a build error the gate would
refuse anyway; catching it on the panel is a courtesy, not a new rule.

**Placement is the browser's, and it is narrow.** The line is inserted as a new
line after the caret when the caret is inside a ```` ```calc ```` fence;
otherwise appended to the last calc fence in the body; and if the body has no
calc fence, the picker refuses and says so rather than inventing a block the
author did not ask for. Insertion writes the textarea through the existing
draft mechanism (`static/drafts.js:72 setDraftBody`), so the draft, dirty
banner, `beforeunload`, save, revision check, and conflict screen all apply to
a picked value exactly as they do to a typed sentence — no second editor state.

## 8. Non-goals

- **xlsx.** Deferred, with CSV proven first, exactly as `calc-sources.md` §4
  frames it. The picker's shape does not depend on the reader: `list_entries`
  is one method on one more reader.
- **PDF datasheet values.** Deferred, and explicitly the *reason* §3's confirm
  contract exists. It needs a PDF text-and-coordinates library plus page
  rendering, and `browser-editor.md` calls it "the heaviest dependency the
  editor has". It is its own slice, behind this panel.
- **Editing, creating, uploading, or writing back to a source file.** A source
  file is read-only to the editor, in every direction (`calc-sources.md` §10).
- **`refdes fetch --update` from the browser.** §4. Re-accepting a changed
  source value stays a terminal act.
- **A generic file browser.** §6. The picker can name a file only when the item
  cites it.
- **Adding a `citations:` entry.** The honest gap: an item that cites no CSV
  gets an empty picker. Citations are a collection field, and the patcher
  replaces scalar spans only — `NON_SCALAR_FIELD_TYPES` marks them read-only
  (`serve/edit.py:546`). The empty state explains the same-item rule and shows
  the exact YAML to paste. A citations row editor is `browser-editor.md` v1
  goal 4 territory and is its own slice; when it lands, the picker gains "cite
  a new file" for free, because the only thing missing is the ability to write
  the citation.
- **Unit inference, tolerance inference, cross-item source reuse, formula
  evaluation in the browser, a JS CSV parser.** Each is decided against
  elsewhere (`calc-sources.md` §2, §6, §10) and nothing here reopens it.

## 9. Open questions

Recommendations are mine; the questions are Jared's to answer.

1. **Should Accept pin, or should it save the body and tell the author to run
   `refdes fetch`?**
   - **A. Pin, as one operation (recommended).** §4. The gate makes an
     unpinned body unsavable, so the alternative is not "simpler", it is
     "broken".
   - B. Widen the diagnostic gate to tolerate an unpinned `source()` line, and
     let the author fetch by hand afterwards.
   - *Why this is still a question:* B keeps the editor out of
     `.refdes/citations.yaml` entirely, which is a real virtue — the lockfile
     stays a file only the CLI writes. It costs a gate exception for a state
     that is a build error everywhere else in the tool, and an author workflow
     with a manual step in the middle, which is what the picker exists to
     remove.
2. **Should the picker be able to add the missing `citations:` entry?**
   - **DECIDED: A** (Jared, 2026-09-26, to keep moving rather than block
     here). Not in v1. §8: show the rule and the snippet.
   - B. Add a narrow `add_citation` patcher op alongside it. Not taken; the
     real cost of A — the picker is useless on an item that has never cited
     a CSV, which is every item the first time — is accepted rather than
     built around, and stays a candidate for a later pass.
3. **Is showing the file's live value acceptable, or should the panel show only
   what the lockfile pins?**
   - **A. Show live, labelled, with the pinned value beside it (recommended).** §5.
   - B. Lockfile-only: the picker offers only keys already pinned somewhere.
   - *Why it matters:* B is more hermetic and much less useful — it cannot pick
     a new key, which is the feature. A is safe only because the pinned number
     is what gets committed, and the panel says so.
4. **Should the keys endpoint filter server-side, or return everything up to the
   cap and filter in the browser?**
   - **A. `?q=` substring filter server-side, cap 5000 rows (recommended)** —
     one code path, and the cap is enforced where the file is read.
   - B. Return all rows, filter client-side. Simpler server, and a 5000-row
     payload for a 20-row panel.
5. **Duplicate keys: list both rows unselectable, or hide them?**
   - **A. List both, unselectable, with the reader's reason (recommended).**
     Hiding them makes a broken file look empty; the author cannot fix what
     they cannot see.
6. **Should the picker work on a sealed or imported item?**
   - **A. Reads allowed, Accept refused with the existing reason (recommended).**
     Seeing where a value came from is review, and review is what a sealed
     entry's readers do. `edit.body.editable` already carries the reason
     (`serve/api.py:125-190`), and Accept is a body write, so the refusal is
     inherited rather than new.
7. **Does the confirm step need to remember the author's unit choice per key?**
   - **A. No (recommended).** A remembered default is a default, and §7 refuses
     defaults. If it later proves genuinely annoying, the fix is a unit column
     in the CSV and a design change to `calc-sources.md` §6, not a cache here.

## 10. Tests

Named as acceptance criteria, in the style of `calc-sources.md` §10 and the
existing `tests/test_serve_edit_http.py` / `test_serve_static.py` posture.
Server tests go through the real HTTP surface with a real fixture project;
static tests assert the JS wiring, because a picker nothing imports is a picker
nobody sees (`test_serve_static.py:118-128`).

Reader:

- `test_list_entries_returns_every_key_with_raw_and_canonical_text`
- `test_list_entries_marks_a_non_numeric_row_unselectable_without_hiding_it`
- `test_list_entries_marks_both_rows_of_a_duplicated_key_unselectable`
- `test_list_entries_fails_on_a_bad_header_like_extract_does`
- `test_list_entries_uses_the_same_number_grammar_as_extract` — the
  `100 mW` / `1,000` / `1_000` / non-ASCII-digit set from
  `test_sources_csv.py` yields unselectable rows, never selectable ones.
- `test_a_reader_without_list_entries_raises_instead_of_returning_nothing`

Endpoints:

- `test_the_source_picker_lists_only_the_citing_item_s_own_files`
- `test_the_picker_refuses_a_path_the_item_does_not_cite` — including a path
  cited by a *different* item, which is the rule in
  `authorize_source_path`'s own message.
- `test_the_picker_refuses_an_absolute_path_and_a_path_that_escapes_the_root`
- `test_the_picker_refuses_a_cited_file_with_no_registered_reader`
- `test_the_picker_requires_the_launch_token_on_reads`
- `test_the_picker_never_returns_an_absolute_server_path`
- `test_the_picker_caps_an_oversized_file_and_names_the_limit`
- `test_the_proposed_line_parses_back_through_parse_source_call`
- `test_the_proposal_refuses_an_unknown_unit_before_anything_is_inserted`
- `test_the_proposal_refuses_a_name_the_item_already_assigns`

Accept:

- `test_accept_writes_the_body_and_the_lockfile_together`
- `test_accept_pins_the_value_the_reader_read_not_the_value_the_browser_sent`
- `test_accept_of_an_unpinned_citation_pins_the_hash_and_the_value_in_one_record`
- `test_accept_refuses_a_changed_file_and_directs_fetch_update`
- `test_a_refused_accept_leaves_both_the_item_file_and_the_lockfile_byte_identical`
  — the `snapshot_tree` posture (`tests/serve_support.py:412`) over both files.
- `test_accept_never_replaces_an_existing_value_for_a_different_key`
- `test_a_no_write_server_offers_the_picker_and_refuses_accept`

UI, static:

- `test_the_picker_is_wired_into_the_editor` — `sourcepicker.js` exists and is
  imported by `editor.js`.
- `test_the_browser_parses_no_csv` — no served JS module splits fetched text on
  `,` or `\n` to read a source file; the only source data the page has is what
  the API handed it.
- `test_the_picker_inserts_through_the_existing_draft_mechanism` — it calls
  `setDraftBody` and posts `set_body`, and never a new op name.
- `test_the_unit_field_starts_empty_and_accept_is_disabled_until_it_is_filled`

End to end:

- `test_a_picked_value_saves_and_resolves_without_a_cli_step` — pick, confirm,
  accept, and the served calc table shows the value; nothing between accept and
  the value appearing.
- `test_a_picked_value_survives_a_rebuild_and_drifts_when_the_csv_changes` —
  after accept, editing the CSV produces the existing loud drift warning and
  the build keeps using the pinned number (`calc-sources.md` Q2's posture).

## 11. Phasing

**Slice A — the service reads.** `sources.list_entries` + `SourceEntry`, the
three read endpoints, their authorization and caps, and the reader/endpoint
tests. No UI. This slice is independently useful: it is the API a CLI
`refdes sources list --item X` or a future xlsx picker both sit on, and it is
where the path-confinement rules get proven.

**Slice B — accept.** The widened `set_body` request, the lockfile write and
its rollback inside the existing write lock, and the accept tests. Land B
before any UI: it is the only part that writes tracked state, and it should be
proven against the CLI's own fetch semantics while the only caller is a test.

**Slice C — the panel.** `sourcepicker.js`, the file → key → confirm flow, the
unit field with no default, insertion through `setDraftBody`, the static and
end-to-end tests. This is the slice the author feels, and it is deliberately
last: with A and B proven, C is composition.

**Later.** The citations row editor, which is what unlocks "cite a new file"
(§8). The xlsx reader behind the same `list_entries` contract. The PDF
datasheet picker behind the same confirm-before-accept panel, with the page
context and candidate-list rules already agreed in `calc-sources.md` §1.
