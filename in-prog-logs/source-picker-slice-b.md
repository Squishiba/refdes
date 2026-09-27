# Editor source picker — Slice B: accept

docs/design/editor-source-picker.md §4, §11 "Slice B — accept". The only slice
of this feature that writes tracked state: one `POST /api/item/<ref>/edit`
carrying the body op plus the keys to pin, committing the item file and
`.refdes/citations.yaml` together inside the existing per-project write lock,
and rolling both back when anything says no.

## Chunk 1 — the shape, from the design and the code

Read: §4 (the six-step sequence, the non-`--update` extraction policy, "the
browser never re-pins a changed file"), §5 ("the number that gets pinned comes
from `extract()` inside the accept operation"), §10's Accept list, §11; then
`serve/edit.py` (`_apply_locked`, `_atomic_replace`, `_atomic_create`,
`_rollback`, `_blocking_diagnostics`), `serve/sources.py` (Slice A:
`propose_payload`, `_compose`, `_authorise`, the `label=` naming pattern that
keeps absolute paths in the process), `citations.py` (`save_lockfile`,
`_refresh_pinned_sources`, `_extract_source_values`, `fetch_all`'s record
shape), `serve/api.py` (`_apply_edit`), `build.py` (the source resolver raises
for an unpinned key, and `run_calcs` reads `load_lockfile(project)` from disk
at load time).

What the reading settled:

- **The op name stays `set_body`** (§4 "carrying the body op plus the keys to
  pin"; §10's static test says "never a new op name"). The request is widened
  with a `pin` field naming `{path, key, unit, name}` — never a value.
- **Re-validation is `propose_payload`, called under the lock.** Not a second
  copy of its rules: authorization, the key still existing and still being
  selectable, the name still usable, the unit still checking out, and the
  composed line all come from the Slice A function itself. Accept adds the two
  things a proposal cannot know: that the body being saved actually names the
  pair, and the pin.
- **The gate must see the pin on disk.** `build.run_calcs` calls
  `citations.load_lockfile(project)`, and the loader's `overlay` covers item
  source files only — `.refdes/citations.yaml` has no in-memory overlay path.
  So the lockfile really is written before the candidate load, exactly §4's
  order, and a gate refusal really does need `_restore`.
- **"The body names the pin" is a parse, not a string match.** The pair is
  collected out of the submitted body with `calc.source_calls_in_block` over
  `calc.extract_blocks_with_lines`, each path through
  `citations.authorize_source_path` — the same walk `collect_source_uses` does,
  on one body instead of a project. A string match on the composed line would
  refuse an indented line the evaluator reads fine; this refuses only a body
  that genuinely does not ask for the key.
- **Byte-for-byte is by construction, not by copying.** `save_lockfile` is
  split so the text builder is `citations.lockfile_text(records)`; the editor
  writes those exact bytes through `_atomic_replace`. Two spellings of the
  lockfile format is the bug this avoids.
- **The record is fetch's record.** For a path already pinned, accept delegates
  to `_refresh_pinned_sources` with the union of the keys already pinned and
  the key being accepted — which is what keeps another key's pinned value
  alive (that function replaces the whole `values` map with what it extracts)
  and what makes the drift refusal fetch's own words. For a path with no
  record, accept writes the same five keys `fetch_all` writes: `sha256`,
  `fetched`, `kept_copy: false`, `bytes`, `values`.
- **No absolute server path.** `reader.extract()` labelled itself with
  `path.as_posix()`, so an extraction failure inside accept would have quoted
  the server root. It now takes `label=`, the same naming-not-scrubbing fix
  Slice A used for `list_entries`, and accept passes `canon`.

## Chunk 2 — the transaction

`serve/edit.py::_apply_locked`, after `new_text` is planned and before anything
is written:

1. `sources.accept_plan(...)` per pin → re-validated tuple + composed line; a
   `SourceRefusal` is a `Refused` with nothing written.
2. every pinned pair must appear in the body being saved; otherwise `Refused`,
   nothing written. This is the "no dead pin" half of §4's "the author must not
   be able to half-commit".
3. `citations.stage_source_pins(...)` extracts each value from the live file
   under fetch's non-`--update` policy and returns the whole staged lockfile
   text plus what it pinned. A refusal here — a changed file, a file that went
   missing, a row that stopped parsing — still writes nothing.
4. write the lockfile (`_atomic_replace`, or `_atomic_create` when the project
   has never been fetched). Skipped when the staged bytes are the bytes already
   on disk, so re-accepting an already-pinned key does not touch the file.
5. load the candidate with the overlay, run the delta gate, write the body.
6. any failure from step 4 onward → `_rollback(lock_path, previous_bytes)`,
   which unlinks a lockfile that did not exist before.

`_apply_locked` grew a `finally`-shaped helper (`_LockfileWrite`) rather than
six copies of the restore call.

## Chunk 3 — tests

`tests/test_serve_sources_accept.py`, through the real HTTP surface on the
Slice A fixture. Named for §10's Accept list. The two that matter most:

- `test_a_diagnostic_gate_refusal_rolls_the_lockfile_back_too` — the pin is
  valid and lands, the body then breaks the build for its own reason, and the
  lockfile has to be back to its original bytes.
- `test_a_failure_after_the_lockfile_landed_leaves_the_body_untouched` — the
  candidate load raises. The item file's bytes *and* mtime are unchanged; the
  lockfile's bytes are.

An mtime is asserted only where nothing was ever written to that file: the
gate's rollback restores bytes, not a timestamp, and §4 says out loud that
this "does not pretend to be crash-atomic".

## Deliberately not here

- The panel (`sourcepicker.js`) — Slice C.
- Editing a `citations:` row or citing a file the item does not yet cite — §9
  Q2, out of scope.
- `fetch --update` semantics — re-accepting a changed source value stays a
  deliberate act in a terminal; accept refuses and points there.
- A transaction journal. The window is one `os.replace` wide and the recovery
  is `_restore` of bytes held in memory, as §4 states.

## Chunk 4 — what landed, and two findings

24 tests in `tests/test_serve_sources_accept.py`; the whole §10 Accept list is
covered by name, plus the cases §10 lists only as prose: the gate refusal that
rolls the lockfile back, a simulated failure in the window between the lockfile
landing and the body landing (both for a project that had a lockfile and for one
that did not), a re-accept that pins nothing new and must not touch the file's
bytes or mtime, a body line for a key that was never pinned still being refused
by the ordinary save, malformed `pin` shapes as 400s, `pin` on a non-`set_body`
op as a 400, the op name still being `set_body`, sealed and imported items
refused with the route's existing words, and a refusal carrying no absolute
server path.

`test_an_accepted_value_resolves_with_no_cli_step_in_between` is the one that
says the slice did its job end to end: accept over HTTP, then a plain
`refdes fetch` in-process answers that there is nothing to do and leaves the
lockfile's bytes alone, then a build resolves the row against the pinned value.
That is the byte-for-byte format claim, tested rather than asserted.

Two things worth recording:

- **A live-file change cannot demonstrate value preservation.** The first draft
  of `test_accept_never_replaces_an_existing_value_for_a_different_key` edited
  the CSV so `rail_load`'s live value differed from its pin, then accepted `eff`
  — and was refused, correctly, by the hash policy. You cannot show another
  key's pinned value surviving while also having changed the file, because
  nothing is allowed to read that file at all. The test now pins a second key
  (`other`, one no body cited before) and accepts a third, which is the case
  that actually distinguishes merge-from-one-key from replace-the-map: a fetch
  would drop `other`, because no body asks for it any more.
- **`CalcLine` has no `value`.** The build's row exposes `result`,
  `source_locked`, `source_path`, `source_key` and `error`; the assertion reads
  `source_locked == "0.93"`, which is the provenance badge the renderer shows,
  so it says something sharper than a float comparison would.

## Gate

`pytest -q` — 2451 passed, 2 skipped. `ruff check --select E9,F src tests` —
clean.
