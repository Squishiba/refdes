# CLI reference audit — chunk 3b (stub-tests, former-ids, history)

Scope: `docs/cli-reference.md`, sections `refdes stub-tests`,
`refdes former-ids propose`, `refdes history capture` / `redact` /
`migrate-seals`. Docs-only changes; no source or test edits.

Branch: `ao/refdes-176/docs-cli-stub-history` (from `origin/main` @ 81adbae).

Scratch project: `.scratch/p3b` (`refdes init`, then hand-added `boards:`
with tokens P/T). Run as:
`python -c "import sys;from refdes.cli import main;sys.exit(main(sys.argv[1:]))" <args>`
with `PYTHONPATH=src` (no installed venv in this worktree).

## stub-tests — verified, no flag discrepancies

`--help` gives exactly `--type NAME`, `--dry-run`. Docs table matches.

Proven by running:
- Refuses on build error, prints the report, exit 1, writes nothing.
- Output lines match the documented transcript verbatim in shape:
  `wrote N stub(s) to <path>: <ids>` / `wrote N stub test(s) across M file(s)` /
  `Run 'refdes id' to allocate ids for the new items.`
- `status: planned` written from the verifier type's own default. **No
  `method:` line** — the bundled standard's `test` type declares no `method`
  field, which is exactly what the docs' "if the type declares one" says.
- One file per (workspace, board): `items/power/stub-tests.md` and
  `items/thermal/stub-tests.md` both appeared, split by board.
- Append-only: adding a coverable item to `power` and re-running left the
  existing `items/power/stub-tests.md` untouched and wrote only the new stub.
- Dedup by declared links: second run printed
  `no coverable item is missing a verifying test` (exit 0). Deleting the
  whole generated file made all three targets eligible again on the next run.
- `--type requirement` → `configuration error: 'requirement' does not
  declare a 'verifies' link (types that do: test)`, exit 2.
- `--no-write stub-tests` behaves as `--dry-run` (no refusal).
- `refdes id` on the generated stubs allocates `TST-001..`, and in a project
  whose board declares `token: P` each stub then trips
  `WARNING ... item is on board 'power' (token 'P'), but its id prefix 'TST'
  does not contain that token`. Confirms the doc's TST/prefix claim. Note
  the token lint is a **warning**, not an error.

Discrepancy found (fixed): the documented example transcript lists
`REQ-PWR-004, REQ-PWR-005, BND-THM-002` for a single file. Real output sorts
ids within each file (`sorted(project.coverage)` in
`src/refdes/stub_tests.py`), and one board's file never holds another
board's items. Example corrected to sorted, same-board ids.

## former-ids propose — verified; two documentation gaps found

`--help` gives exactly `--baseline NAME`, `--confirm OLD_ID[,OLD_ID...]`.
Docs table matches.

Proven by running:
- `refdes revision rev-a` stamps a baseline; with no baseline at all the
  command prints `error: no baseline stamped yet -- nothing to compare
  against. Run 'refdes revision <name>' first.` and exits 1.
- `--baseline nope` → `error: no baseline named 'nope'`, exit 1.
- `--confirm` naming an id that is not a current candidate → the candidate
  list is still printed, then
  `error: not a currently proposed candidate: NOPE-999 -- run 'refdes
  former-ids propose' again to see current candidates`, exit 1. Nothing
  written. Matches the docs' "refused, not guessed at".
- `--no-write former-ids propose --confirm REQ-001` refuses, exit 2, with
  `--no-write: former-ids propose --confirm writes former_ids: into the item
  files; refusing to run it under --no-write. Drop --no-write to run it for
  real.` Plain `--no-write propose` still reports candidates and writes
  nothing, exit 0.
- The documented load-error path is exact: a file that fails to parse has its
  error printed to stderr, and the quiet answer becomes
  `no candidate former-id mappings found -- 1 load error(s); files that
  failed to load were not searched`, exit 1.

Gap 1 (fixed): the docs only ever show the similarity-scored candidate line,
  `... confidence 94%`. That is the **legacy keyless-baseline** path. A
  baseline stamped today carries surrogate keys, and there the same line ends
  in `exact match (surrogate key)` with the old title printed as `''` —
  verified by running both paths. Since keys are minted automatically, the
  exact form is what a current user normally sees. Added to the docs.

Gap 2 (fixed): `error: no baseline named 'nope'` / `no baseline stamped yet`
  (both exit 1) were undocumented.

Source observation, NOT fixed (per instructions): on the keyed path the old
  title always prints as `''`. `src/refdes/former_ids.py:109` does
  `baseline.items.get(_key) or {}`, but a §5-shape baseline is keyed by
  *display id* with the surrogate key stored as a `key:` field inside the
  entry, so the lookup misses and `entry.get("title", "")` yields `''`. The
  real old title is sitting in `baseline.items[old_id]["title"]`. Cosmetic
  (the old title is only echoed in the display line), but it is why the
  keyed transcript looks half-empty.

## history capture / redact / migrate-seals — verified; gaps added

`--help` for all three matches the docs exactly (`capture ITEM`;
`redact TARGET [--confirm]`; `migrate-seals [--capture-current]`). No
undocumented flags. All three refuse under `--no-write` with exit 2, as the
section already claimed.

### capture
- `captured REQ-PWR-004: manual capture` — matches the documented line.
- Second run: `REQ-PWR-004 is already captured; nothing was written`, exit 0.
- A surrogate key works and announces the display id.
- The stored event is `kind: captured`, `reason: manual capture`, and
  **does carry `occurred_at`** — the docs' clockless-automatic-vs-clocked-
  manual claim verified against the written file.
- Unknown item -> exit 2, `error: no item 'NOPE-999' in this project (looked
  up by display id, then surrogate key)`. **Undocumented; added.**

### redact
- `redacted 1 object(s) and 1 event(s)` +
  `wrote redaction event <uuid> naming what was removed (by digest and event
  id only -- its content is not repeated anywhere in this output)` + the Git
  warning. Exit 0.
- The written `redaction` event's reason is
  `redacted 1 object(s) and 1 event(s): objects <digest>; events <uuid>` —
  digests and event ids only, **no content**. The doc's core claim verified
  against the file on disk, not just the console.
- Without `--confirm`: refuses, exit 2, writes nothing, and prints the
  irreversible warning to stderr. Docs accurate.
- Redaction by full 64-hex object digest works identically.
- Audit-trail claim verified: redacting the same item a second time reports
  `no history objects or events matched ...` — the earlier redaction event
  is never a target.
- Shared-object claim verified concretely: two byte-identical requirements
  captured to **one** object; redacting one reported
  `redacted 0 object(s) and 1 event(s)` and the object file stayed on disk.
- Undocumented, now added: a target that names no item and is not 64-hex is
  refused with exit 2; a target that resolves with nothing captured exits 0
  with `no history objects or events matched <T>; nothing was redacted` and
  does **not** print the Git warning (verified — the warning is only on the
  success path).

### migrate-seals
- Produced two real legacy seal files by adding log entries and building:
  `.refdes/log-seal.yaml` (board-less) and `.refdes/log-seal-power.yaml`.
- First run output matches the documented transcript exactly.
- A `legacy-seal` marker event is written with **no** `object:` field and a
  reason naming the seal file and the recorded hash
  (`legacy seal for LOG-001 in .refdes/log-seal-power.yaml; recorded hash
  8a7e8e2ec15cd178; original content was not captured`). The doc's
  "recorded hash only; nothing may imply the text is recoverable" verified.
- Both seal files still on disk afterwards — never modified, as documented.
- Repeat run prints `LOG-002: already migrated (.refdes/log-seal.yaml)` and
  `0 legacy-seal marker(s) written, 2 already present`. **Undocumented line
  form; added.**
- `--capture-current` on an unchanged item: `captured current content of
  LOG-A-001 as a migrated-current event -- clearly dated, not seal-time
  text`, and the event carries `occurred_at` plus reason `current content
  captured at seal migration; this is not seal-time text`. Verified.
- `--capture-current` on drifted content: `LOG-002: live content differs
  from the recorded hash; no migrated-current snapshot was taken`. Docs
  already said this; verified.
- `--capture-current` where the sealed item no longer exists:
  `LOG-002: no live item for this seal record; no migrated-current snapshot
  was taken`. **Undocumented third outcome; added.**
- A project with no seal files at all: `no legacy seal files found; nothing
  to migrate`, exit 0, with and without `--capture-current`.
  **Undocumented; added.**
- Re-running `--capture-current` immediately does not duplicate a capture
  (event count in `.refdes/history/events/` stayed at 1 across three runs) —
  the `append_event` no-op on a derived id. Verified before documenting.

### Not-a-bug worth knowing
Marker event ids derive from `item_key`, and `item_key` is resolved from
the live item when one exists, falling back to the display id when it does
not. Deleting a sealed item and re-running `migrate-seals` therefore writes
a *second*, differently-keyed marker (`1 legacy-seal marker(s) written, 1
already present`). Idempotency holds for a stable project, which is what the
docs claim; I did not document this edge.

## Source observations, NOT fixed (per instructions)

1. `src/refdes/former_ids.py:109` — on the exact/keyed path the old title
   always prints as `''`. `baseline.items.get(_key) or {}` misses, because a
   current-format baseline is keyed by *display id* with the surrogate key
   held in a `key:` field inside the entry. The real old title is in
   `baseline.items[old_id]["title"]`. Cosmetic — the old title is only
   echoed in the display line, and the candidate pairing itself is derived
   from the key, so it is correct.
2. `src/refdes/history.py` `migrate_seals` — the marker-id instability above.
   Not a correctness problem, but it means "idempotent" is scoped to a
   project whose sealed items still exist.

## Doc changes made (docs/cli-reference.md only)

- Global `--no-write` table: added `history capture`, `history redact`,
  `history migrate-seals` to the refuse list (they were missing even though
  the `history` section and `refdes --help` both list them).
- `stub-tests`: sample output ids were unsorted and mixed another board's id
  into one board's file. Corrected to sorted, same-board ids, with a sentence
  on the sorting and the per-(workspace, board) scope.
- `former-ids propose`: split the two candidate-output shapes (keyed
  `exact match (surrogate key)` vs legacy `confidence NN%`), noted the empty
  old title on the keyed path and pointed at `propose`; documented the
  `--confirm` non-candidate refusal transcript, the two baseline-resolution
  errors (both exit 1), the load-error transcript, and that `--confirm`
  writes in the order listed.
- `history capture`: added the unknown-item exit-2 refusal.
- `history redact`: added the exit-2 unknown-target refusal and the exit-0
  no-match line (and that the Git warning is *not* printed there); made the
  shared-object claim concrete with the observed `0 object(s) and 1 event(s)`.
- `history migrate-seals`: added the `already migrated` repeat-run
  transcript, the no-seal-files exit-0 line, the `unresolved` third
  `--capture-current` outcome, and the re-run safety note.

Changelog fragment: `changelog.d/cli-reference-audit-3b.fixed.md`.

## Verification gate

`python -m pytest -q -x` and `python -m ruff check --select E9,F src tests`
run clean (see final report). No source or test files were modified —
`git status` shows only `docs/cli-reference.md`,
`changelog.d/cli-reference-audit-3b.fixed.md` and this notes file.
