Status: proposed (drafted 2026-09-27) — a design note, not a decision. Nothing here is
landed; `history.py` and its tests are untouched. Jared's call is required before any
implementation.

# What a `legacy-seal` marker is about when its item is gone

## 1. The problem, precisely

`refdes history migrate-seals` writes one `legacy-seal` marker per seal record
(`src/refdes/history.py:842`). The marker's identity comes from this derivation
(`src/refdes/history.py:879`):

```python
item_key = str(key or (item.key if item and item.key else display_id or record_id))
```

Three sources, in order: the surrogate key recorded in the seal entry, the key of the
live item the record resolves to, and then — when both are absent — a **display id**.

The third branch is the problem. A display id is not an identity. `docs/design/keys.md`
is explicit that the identity/display split is the whole point of surrogate keys: after
an item is deleted, "the deleted item's key is simply gone (an ordinary `removed` diff
line), and the new item mints its own, different key, **however it happens to be
labelled**" (`docs/design/keys.md:171-173`). `docs/design/living-notes.md:593-595` says
the store must key by surrogate key "where available" and that "Display ID remains stored
for readability but is never the identity."

So for a seal record whose item was deleted and which carries no key — a pre-keys legacy
record — `migrate_seals` writes a marker whose `item_key` is a recyclable label. The
marker's derived id is `uuid5(kind, item_key, "")` (`src/refdes/history.py:301`), so the
label is baked into the filename too. If a later item is given the same display id, that
later item is the one a reader will resolve the old marker to. The marker says "this is
about LOG-001," and the thing it was about is gone.

The shape test that distinguishes the two kinds of value is already mechanical: display
ids contain `-<digits>` and surrogate keys never contain `-` (`src/refdes/model.py:886-887`),
and a key is 11 characters of Crockford base32 with a check character
(`src/refdes/keys.py:30,36`, `malformed_key_message` at `keys.py:117`). A `deleted:`-style
namespace is unambiguous for the same reason — neither alphabet contains a colon.

## 2. Why it is low severity today

Four independent reasons, each verified:

1. **No reader resolves these markers by `item_key`.** `capture_index` filters to
   `_CAPTURE_KINDS = ("followed", "followed-corrected", "captured")`
   (`src/refdes/history.py:559,612`), which excludes `legacy-seal`. Nothing else joins a
   marker's `item_key` against live items. H4's own log records the same gap: "nothing
   **reads** them yet … the markers are inert-but-true records"
   (`in-prog-logs/living-notes-phase-h4.md:86-92`).
2. **Nothing has run the migration.** `refdes history` is unreleased — the fragment
   `changelog.d/history-commands.added.md` is still pending and `CHANGELOG.md` has no
   `refdes history` entry (last release 0.5.0). This repo's own `.refdes/` has no
   `history/` directory. There are no markers on disk anywhere outside test fixtures.
3. **No silent skip, no data loss.** Two records deriving the same `item_key` collapse to
   one marker, and the seal machinery makes that collision hard to reach: `seal.verify()`
   resolves a legacy display-id record to whatever item now claims the id and errors on a
   hash mismatch (`src/refdes/seal.py:79-107,337`), and its inheritance path *moves* a
   base-file record into a board file rather than duplicating it
   (`src/refdes/seal.py:267,348-350`). One identity, one record, one marker.
4. **The state that produces it is usually a build error.** A sealed record whose identity
   is gone is reported by `_report_deleted` (`src/refdes/seal.py:362`), so the project is
   already red and the user resolves it by restoring the item or `--reseal`-ing the record
   away.

Two caveats that keep this from being a non-issue:

- `_report_deleted` is called with the **base** seal file only (`src/refdes/seal.py:354`).
  A record that was inherited into a *board* file and whose item was deleted afterwards is
  not reported at all. That is a silent path into the affected state.
- H5 plans to turn a missing sealed record from an error into a warning for history-backed
  types (`docs/design/living-notes-plan.md`, H5). Reason 4 is therefore temporary. The
  state stops being self-limiting exactly when markers start being read.

## 3. What a fix is not allowed to do

The store is append-only and never-uneditable. The precedent is `HASH_FORMAT`
(`src/refdes/build.py:1437-1468`): every bump is designed so "no existing item's hash
moves," and carry-forward swaps a stored hash only when it provably reconstructs under the
old definition, otherwise it leaves the record alone and reports it uncomparable.
`docs/design/living-notes.md:341-345` states the rule for this store directly: history
objects "migrate only by an explicit history migration that proves semantic equivalence.
A new `HASH_FORMAT` must never rewrite an object or make an item look edited."

The trap specific to *this* field is that a marker's identity is derived from `item_key`.
Changing the derivation does not rewrite an existing marker — it writes a **second**
marker for the same seal record on the next run, because the derived filename changes and
`append_event` only short-circuits on an existing path (`src/refdes/history.py:355-366`).
`load_events` refuses two ids for the *same* edge (`src/refdes/history.py:406-411`) but
cannot see this: the two edges differ. So any change to the derivation is a format change
with `HASH_FORMAT`-class stakes, and `HISTORY_FORMAT` (`src/refdes/history.py:67`) plus
`_check_format` (`history.py:258-274`) only refuse *newer* files — a bump alone would not
let a reader tell the two generations apart.

That is the asymmetry that makes this worth deciding now: **the `history` group is
unreleased, so a derivation decision is nearly free today and permanent the moment anyone
migrates a project.**

## 4. Options

| | change | cost to existing markers | does it actually fix attribution? |
|---|---|---|---|
| (a) | leave the derivation alone | none | no |
| (b) | mint a surrogate retroactively | n/a — blocked by keys design | yes, illegitimately |
| (c) | namespace the fallback (`deleted:LOG-001`) | duplicate markers in migrated stores | partially |
| (d) | derive the id from the seal record | duplicate markers; breaks two guarantees | yes, at a different cost |
| (e) | refuse such records at migration | none | yes, by declining to write |
| (f) | keep `item_key`, state the identity claim additively | none | makes it resolvable, not wrong |

**(a) Leave it.** The population is narrow and, today, self-limiting (§2). Cost of leaving
it is not zero: the marker's `item_key` field promises identity and sometimes contains a
label, and the first future reader that groups history by `item_key` inherits the trap.
Leaving it *undocumented* is the actual defect here.

**(b) Mint a surrogate for the deleted item.** This is the option the finding flags as
conflicting with the keys design, and the conflict is real. I checked it rather than
trusting the finding, and it holds up — with more support than the finding cited:

- Minting in this codebase is defined over **live items with a source file to write into**:
  `mint_missing` assigns a key to every local item lacking one and writes it back into the
  item's own file (`docs/design/keys.md` §2). A deleted item has no file. The key would
  exist only in the history store — a key no item ever declared, which is precisely what
  Layer 3 treats as an error elsewhere.
- `docs/design/keys.md:968-971` says the quiet part outright, about pre-keys records:
  conditional hash-format carry-forward "**does not manufacture that missing historical
  identity**."
- The 2026-09-15 decision (`docs/design/keys.md:923-953`) refuses to re-mint a deleted
  key before reporting it, because "minting over it would destroy the evidence."
- Mechanically it is worse than merely un-design'd: `mint_missing` draws from
  `secrets.token_bytes`. A random mint is not reproducible, so a re-run after a partial
  failure mints a *different* key and writes a *second* marker for the same seal record —
  breaking the derived-id idempotence the whole store rests on
  (`src/refdes/history.py:16-20,301-313`).

  Where the claim does *not* hold as a blanket statement: keys.md nowhere forbids *naming*
  a dead identity. Layer 5 tolerates old records that reference a key that no longer exists
  (`docs/design/keys.md:975-980`). The design's objection is to manufacturing a new key,
  not to referring to an identity that is gone — which is what makes (c)/(d)/(f) live
  options at all.

  **A narrower (b′) that does not conflict:** don't mint, *recover*. If the deleted item's
  key is recorded somewhere — a key-keyed seal entry, an older baseline, a board manifest —
  reading it is the same move keys.md's deleted-key report already makes
  (`docs/design/keys.md:929-933`). Honest limit: it helps essentially none of the affected
  population. A record that already carries a key never needed it, and the affected records
  are display-id-keyed precisely because they predate keys; pre-keys baselines carry no key
  evidence either (`keys.md:968`), and adoption prunes membership entries with no live
  identity (`keys.md:1099`). Worth naming so nobody re-proposes minting as the fix: for this
  population there is no recorded key to recover.

**(c) Namespace the fallback** — write `deleted:LOG-001` instead of `LOG-001`. Deterministic,
so idempotence survives; unmistakable, since neither id alphabet contains a colon; and it
stops a later holder of `LOG-001` from inheriting the marker. Costs: it changes the derived
id, so any store that already migrated gets a duplicate marker for one seal fact (§3); it
adds a third identity namespace every reader must learn; and it is still ambiguous between
two successive holders of a retired display id. It also makes `history redact <item>`
permanently unable to reach the marker — which is already true today, since the CLI requires
a surrogate key (`src/refdes/cli.py:1260-1266`), but a namespaced value makes it true by
construction.

**(d) Derive from the seal record** — identity from `(seal file, record id)`, the finding's
"most faithful to existing idempotence" suggestion. I think that assessment is wrong on two
counts and want it on record:

- It breaks the documented overlap dedup. `migrate_seals` promises "a record that appears
  in two files (the transitional base-file/board-file overlap `seal.py` documents) yields
  one marker" (`src/refdes/history.py:852-855`). Put the file in the identity and it yields
  two.
- If the recorded hash is part of the identity it is not stable. `verify(write=True)`
  upgrades a matching legacy hash in place and stamps `hash_format`
  (`src/refdes/seal.py:116,317-321`), so a `HASH_FORMAT` bump plus one writable build moves
  the hash and a later migration run writes a second marker. Hash-free record identity keeps
  the first problem and avoids the second.

It does have one genuine merit: it is the only option whose identity is about the *record*,
which is what the marker actually knows.

**(e) Refuse rather than guess.** `migrate_seals` skips and loudly reports any record with
neither a recorded key nor a live item, telling the user to restore the item or `--reseal`
the record away. This is the most idiomatic option in this codebase — the store's own header
says to refuse loudly where the format is ambiguous (`src/refdes/history.py:41-44`), and
keys.md's deleted-key decision is "report before you mint." Costs: §8 wants every valid
legacy seal record to become a marker, so refusing leaves a hole in the migration's
completeness claim; the offending record may be sitting in a board file where nothing
reports it as deleted (§2); and it turns a routine migration into a blocker for a project
that legitimately deleted a sealed entry years ago. Note `--capture-current` already reports
such records as `unresolved` (`src/refdes/history.py:893-895`) — it just doesn't say what
identity it wrote anyway.

**(f) Keep `item_key`, state the identity claim.** No derivation change, so no marker is
ever re-pointed and no duplicate is ever written — `append_event` returns early on an
existing path without rewriting (`src/refdes/history.py:355-366`), so a purely additive
change is invisible to already-written markers. Two halves:

1. *Reader rule, no format change at all:* a `legacy-seal` marker's `item_key` is an
   identity only if it is a well-formed surrogate key; otherwise it is a display-id stand-in
   and must not be attributed to a live item. This is mechanically checkable today with
   `keys.KEY_LEN` + `keys.malformed_key_message` (`src/refdes/keys.py:36,117`) — the exact
   test `history._frozen_follows_key` already performs. Cheap, total, and retroactive: it
   covers markers we cannot rewrite.
2. *Optional additive field on new markers* (`identity_stable: false`, or an explicit
   `item_display_id`) so the distinction is stated in data rather than inferred, plus a line
   in `migrate-seals` output naming any record whose marker identity is a stand-in, so a
   human sees it at migration time. Absent field ⇒ pre-flag marker, which is ambiguous on
   its own — which is why (1) is the load-bearing half and (2) is sugar.

## 5. Recommendation (mine — not a decision)

**(f), with (a)'s derivation left exactly where it is, and (b) ruled out permanently.**

Reasoning: the harm is prospective misattribution, not present corruption (§2); the only
fix that cannot duplicate a marker or re-point an existing one is a fix that does not touch
the derivation; and the distinction the fix needs to express is already mechanically
decidable, so the honest statement costs a documented reader rule rather than a format
change. (e) is the principled alternative if Jared would rather the store never contain a
non-surrogate `item_key` at all — it is defensible and idiomatic, and I would implement
either. (c) and (d) both buy a cleaner label with a duplicate-marker problem, and (d) also
breaks two guarantees `migrate_seals` currently advertises.

Whatever is chosen, **decide it before `refdes history` ships** (§3). After release, every
option above except (f) acquires a migration requirement it does not have today.

## 6. Open questions for Jared

1. Is `item_key` allowed to hold a display id at all, or is that a format violation that
   should be refused at write time (option (e))? The field name promises identity.
2. Given the append-only posture, is *any* change to a derived-id derivation acceptable —
   knowing a re-run then *duplicates* rather than rewrites, and `load_events` cannot detect
   it? If not, (c)/(d) are off the table on principle, not on cost.
3. Should `history redact <item>` be able to reach a marker whose identity is not a live
   item's key? Today it cannot (`cli.py:1260-1266`). If a deleted item's seal marker can
   hold content-adjacent text, is unreachable-by-name a privacy gap as well as an
   attribution one?
4. Does H5's planned downgrade of `_report_deleted` from error to warning change the
   calculus? It removes the mechanism that currently keeps the affected population small,
   and it lands in the same release train as the migration.
5. `_report_deleted` scans the base seal file only (`seal.py:354`). Is that intended, or a
   separate bug? It determines whether the affected population is visible at all.
6. Is the base/board overlap dedup (`history.py:852-855`) a guarantee we must preserve? It
   is what rules out record-derived identity as the finding proposed it.
7. If we ever want a tombstone identity that survives display-id reuse, keys.md's only
   precedent for remembering a retired identity is the ID ledger's burned numbers
   (`docs/design/keys.md:1142-1160`) — display ids, not keys, and kept for external
   citations. Is a per-project deleted-key ledger in scope at all, or is "the marker is
   about a record, not an item" the honest final answer?

## 7. Verification notes

- Confirmed the derivation and its fallback order at `src/refdes/history.py:879`; confirmed
  `legacy-seal` is in `NO_OBJECT_KINDS` (`history.py:96`), so a marker carries no snapshot.
- Confirmed `refdes history` is unreleased (pending `changelog.d` fragment; no
  `refdes history` line in `CHANGELOG.md`), and this repo's `.refdes/` has no `history/`.
- Confirmed adoption cannot heal the population: `plan_surrogate_storage` re-keys a legacy
  seal entry only when its live item is identified and its hash carries; otherwise it keeps
  the display id and reports the record uncomparable (`src/refdes/keys.py:349-358`). So the
  population does **not** shrink through adoption — adoption reaches exactly the records that
  were never affected. It shrinks only when the record itself is deleted (`--reseal`), which
  destroys the historical fact rather than fixing its identity.
- Confirmed `migrate-seals` does not run the seal verifier: it loads via `_load()`
  (`loader.load_tree`), not `load_readonly`, so it will happily write markers into a project
  that `refdes check` would fail. The protections in §2 are properties of the project's
  state, not of the command.
- Verified the keys.md claim in §4(b) against `keys.md:171-173, 923-953, 968-971, 975-980`
  and against `keys.mint_missing`'s live-item definition. It holds, with the one carve-out
  noted there (naming a dead identity is tolerated; manufacturing a new one is not).
