# Durable reseal audit — BUG 3

## Investigation and decision

Read `user-sim-release-gate-run1.md` BUG 3 first. Clean worktree at start.
Confirmed in `src/refdes/seal.py`: `verify()` replaces the active hash;
`load_seals()`/`save_seals()` persist only `sealed`; `resealed_ids()` reports
outstanding drift. `src/refdes/cli.py::cmd_audit` reads that drift, not events.
Ran `PYTHONPATH=src refdes build --help` and `audit --help` against this
checkout; both describe accepted reseals as auditable. The installed entry
point initially could not import refdes, so subsequent probes explicitly
use this worktree's `src` and the existing dependency venv.

Choose (a), make the promise true. `docs/design/lifecycle.md` §2 treats seal
files as committed manifests; `docs/design/keys.md` §5 requires preserving
identity and format-aware carry-forward. No two-file-only restriction found.
`docs/design/living-notes.md` §3 chooses a dedicated store for captured
snapshots, but a seal hash is not a snapshot. Its event API (`history.py`) is
idempotent by kind/item/successor: that cannot represent repeated accepted
edits, including A -> B -> A -> B, without changing that store's contract.
The future H5 policy in `living-notes-plan.md` explicitly preserves resealing
for build-sealed types. This fix does not implement H5 or claim to recover
old content from a hash.

Persist an append-only `reseals` event list next to `sealed` in each existing
seal file. Record the item label at acceptance, key when available, old/new
hashes and their format markers, action, and UTC timestamp. Update active
hash and append event in one atomic file replacement. Preserve events when
seals are migrated, adopted or carried forward; historical events never get
relabelled or rehashed. Base-file events remain there after lazy board
migration (the board file gets the active seal); audit reads both locations.
No separate ledger and no changes to the display-id allocation ledger.

Accepted deletion through `--reseal` also destroys the active hash, so record
it in the same list with action `remove` and null new hash. An ordinary build,
unchanged reseal, format upgrade, read-only check or preview must append no
event. Preview warnings must not claim durable acceptance. Show accepted
events separately from the existing outstanding-drift section in audit.

Status: implementation and regression coverage in progress.

## Implementation and verification progress

Implemented `seal.py::load_reseals`/`reseal_history`, append-preserving
`save_seals`, and accepted edit/removal events. A temp write + flush/fsync +
replacement commits the active seal and events together; replacement failure
keeps the old bytes. Malformed event lists fail loudly rather than being
overwritten. `adopt.py`'s separate serialization path now retains events;
`revise.py` already routes carry-forward through `save_seals`.

`cli.py::cmd_audit` has a separate accepted-history section, retaining the
existing outstanding-drift section. Help names the durable storage. Preview
warnings say nothing was written. Updated existing docs (no new docs page)
and added `changelog.d/seal-reseal-audit.fixed.md`.

97 targeted tests passed across reseal/audit, seal enforcement, adoption,
image hashes, history commands and revision CLI. Initial regression failures
were fixture assumptions: direct `parse.load_items` does not mint the key
that the later CLI load mints. Fixed the assertion to inspect the reloaded
identity, preserving the explicit hash and audit-output assertions.

Real CLI repro is retained in `.scratch/reseal-cli-repro/transcript.txt`.
Ran `refdes schema` in that probe project and inspected `$defs.log__entry`
before fixing its missing date. `build --reseal` exits 0 and the subsequent
fresh `audit` prints `was 4d34265af98c51b2, now 71059aef2108bb46`; both hashes
are persisted in the probe's `.refdes/log-seal.yaml`. Outstanding drift is
`(none)`, as it should be after acceptance. Current build/audit help also
captured. Probe commands use `PYTHONPATH` pointing to this checkout.

Scoped Ruff E9,F,I passed; the CI E9,F check over all src/tests passed.
The sandboxed full-suite run could not create loopback sockets, confirmed
with a focused HTTP test (`PermissionError` at socket creation). Re-running
the full suite outside the sandbox, with output retained in
`.scratch/pytest-reseal-unsandboxed.txt`. GitHub's sandboxed connection also
failed; the permitted outside-sandbox PR lookup succeeded (no existing PR).

Status: waiting for full-suite validation before commit and PR.

## Final validation

Full suite outside the sandbox: **2638 passed, 2 skipped** in 196.10s,
using `PYTHONPATH=src /home/jorb/work/venv-refdes/bin/python -m pytest -q
--basetemp=.scratch/pytest-reseal-unsandboxed`. The latest dedicated
regression run passed **14 cases**, including the additional keyed-rename
case added while the full suite was running. Ruff E9,F,I on touched Python
files and `git diff --check` passed after the final edits.

Limits: this records acceptance from now on; it cannot reconstruct already
lost hashes or old source text, prevent manual edits to committed manifests,
or add interprocess writer coordination that the existing manifests lack.
UTC timestamps are event metadata; the list's append order is retained.

Implementation, docs, changelog and validation finished. PR publication is
the remaining delivery step.

## Delivery

Committed the fix as `403eb2e`, pushed `royal-sheep`, and opened
[PR #81](https://github.com/Squishiba/refdes/pull/81). Task finished.
