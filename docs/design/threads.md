# Threads: collapsing `log` and `decision` into one append-only type — design spec

## Decision (recap)

`log` and `decision` collapse into a single type, **`thread`**: an
append-only sequence of **entries**. A decision is not a separate kind of
item — it is simply the entry that concludes a thread. Current state is a
**per-field fold**: for each foldable field, the value comes from the most
recent entry that set it. Everything else in the project — coverage,
checks, hashing, baselines, rendering — reads that fold, not a single
item's fields.

The decision is taken. This document specs it; it does not relitigate it.

**Status: design only.** Nothing here is implemented. §9 lists what should
be prototyped before any of it is.

---

## Background: what changed since this was "considered and not adopted"

`docs/design/` had no threads document until now because issue #7's
finding 17 recorded this exact architecture — "event-sourced threads
replacing the log/decision split" — as considered and rejected. Its
analysis holds up well and its objection list is the right one; it is
reproduced here because this document builds directly on top of it rather
than re-deriving it:

> Two of the four objections are easy, and are conceded: **status** ("last
> entry that set one wins") is a straightforward fold; **supersession**
> becomes thread continuation. **Checks** are harder — the projection has to
> be a per-field fold, not a terminal-entry read, because the comparison
> against a bound has to stay live. **Link target identity** is the
> unresolved one: a link needs either a mutable target (the thread, which
> silently changes meaning on every append) or an immutable one (an entry,
> which is stale by design) — "git resolves exactly this with two kinds of
> name... the thread model implies needing both, which is an *addition* to
> the id system, not a simplification of it."
>
> Net assessment: two types collapse into one, in exchange for a projection
> engine, per-field folding, and a two-tier identity scheme — and every
> consumer... stops reading stored state and starts reading computed state.
> That is a different tool, not a refactor.

Two things have changed since that finding was written, and they are why
this is being specced now rather than left closed:

1. **Surrogate keys (`docs/design/keys.md`) already built the two-tier
   identity scheme finding 17 said was missing.** An opaque, immutable key
   plus a mutable, human-facing display label is exactly "git's branches
   and commits." A thread gets a key; each entry gets a key, minted the
   identical way (§1). This was finding 17's hardest, structural objection,
   and it is resolved as a side effect of unrelated work, not by anything
   invented here.

2. **The hashing objection doesn't survive either, and threads arguably
   improve it.** Today one hash (`item.content_hash`) is reused for two
   different questions: "has this content been tampered with since it was
   sealed" (`seal.py`'s `_matches_sealed_hash`, `seal.py:65-104`, compares
   the stored seal directly against `item.content_hash`) and "has this
   content changed since the last baseline" (`lifecycle._items_map`,
   `lifecycle.py:165-183`, stores that same hash). Under threads these
   become genuinely different computations over genuinely different data —
   an **entry hash** (immutable, breaks on any edit to history — tampering)
   and a **fold hash** (moves on every legitimate append — a real update) —
   see §3. Conflating them today isn't wrong, exactly; it just means "was
   this rewritten" and "did this change" have always been the same
   question because an item was always a single, atomic thing. A thread
   isn't, and the two-hash model is what keeps them from re-collapsing into
   one by accident.

What genuinely remains, per finding 17 and confirmed by working through the
rest of this document: **per-field folding, the checks question, and the
breadth of the change across every consumer that reads stored state.**
Those are specced below, not waved away. §8 in particular is written to
name every consumer concretely, per finding 17's own closing complaint that
"every consumer... stops reading stored state and starts reading computed
state" deserves an actual list, not a gesture.

---

## 1. The type and its entries

### The shape

One type, `thread`, replacing `log` and `decision` in the standard. A
thread has:

- **Thread-level fields** — set once, not per-entry: `id`, `key`, `type`,
  `prefix`/`board`/`workspace` overrides, `former_ids`, item-level
  `history` overrides. These are exactly the reserved/overridable keys
  `parse.RESERVED`/`OVERRIDABLE` already recognize on any item — nothing
  new here.
- **`entries:`** — a new reserved key, an ordered list of entries. Reserved
  the same way `key:` is (`parse.RESERVED`, alongside `id`, `type`,
  `history`, `body`, `former_ids`) — not an overridable field a type could
  shadow, for the same reason identity-adjacent keys aren't shadowable.

Each entry is a small record, not an item:

```yaml
entries:
  - key: k7f3m2q9x4b
    date: 2026-02-24
    author: J. Bin
    body: |
      Back of the envelope: (12 V − 3.3 V) × 1.2 A is 10.4 W in the pass
      element. The enclosure budget is under a watt for the whole power
      stage. Not a marginal call, so I did not model it further.
    addresses: [REQ-PWR-002]

  - key: k2p9w3x1r7
    date: 2026-03-19
    author: J. Bin
    body: |
      Re-read my own bench notes. The 93% figure was at 12V in, not worst
      case; at 36V it drops to 91%.
    status: in_progress

  - key: kb4h8m1z2t
    date: 2026-04-02
    author: J. Bin
    title: Buck converter, not LDO, for the 3V3 rail
    status: accepted
    rationale: LDO dissipates 10.4W worst case against a <1W enclosure
      budget; buck topology meets efficiency and thermal bounds together.
    satisfies: [REQ-PWR-002, REQ-PWR-003]
    constrained_by: [BND-THM-001]
    checks:
      - value: eff
        against: BND-THM-002
    body: |
      Buck at 92% typ / 88% worst-case efficiency clears BND-THM-002 with
      margin; LDO analysis above is the ruled-out alternative.
    ```calc
    eff = 0.88
    ```
```

- **`key:`** — every entry's own opaque identity, minted the identical way
  and at the identical moment an item's `key:` is (`keys.mint_missing`,
  §2 of `docs/design/keys.md`), just scoped one level down: instead of one
  key per item, one key per item *and* one per entry in its `entries:`
  list. No new minting mechanism, no new alphabet, no new check character —
  the existing 11-character Crockford-base32-plus-Damm key, generated and
  validated identically. This is the concrete form of "a thread has a key,
  each entry has a key" from the brief, and it is what actually closes
  finding 17's link-target-identity gap (§4).
- **`date:`** — required, exactly as on a `log` entry today. Display/sort
  field for the rendered timeline, **not** what determines fold order —
  see "ordering," below.
- **`author:`**, **`body:`** — unchanged from today's `log` entry.
- Everything else on an entry is a **foldable field**: any scalar field the
  type declares (`status`, `title`, `rationale`), any structured field
  (`options`, `checks`), and any link name the type declares
  (`satisfies`, `constrained_by`, `selects`, `blocked_by`, `addresses`,
  `supersedes`). An entry declares only the fields it actually has
  something to say about — most entries are log-shaped (a `body` and
  maybe one link), and only the terminal entry looks decision-shaped
  (`status: accepted`, `rationale`, `checks`). This is precisely the
  "several paragraphs of I²C-vs-SPI deliberation living inside what is
  nominally a verdict" problem finding 17 named — under threads that
  deliberation is its own entries, and the verdict entry can be short.

### Ordering: append position, not `date:`

Fold order is **physical position in `entries:`**, the same thing
append-only sealing already treats as ground truth (an entry is sealed the
moment it is first built, in place — `seal.py`'s whole model already
assumes "sealed" means "this position in this file, at this point in
time"). `date:` stays a **display-only** field for the rendered timeline,
decoupled from fold order, exactly as it already is decoupled from log
entries' physical order today (`docs/design-log.md`: "`date` — required;
orders the timeline" is a rendering statement, not a data-model one).

This has to be decoupled on purpose: a backdated entry ("writing up notes
from last week's bench session") must not retroactively change what the
fold currently resolves to. If fold order followed `date:`, appending an
entry dated in the past could silently reorder the fold and flip which
entry is "most recent" for some field — a correction with a surprising
side effect on unrelated fields. Pinning fold order to append position
means the fold only ever moves forward, matching the append-only guarantee
entries already carry individually (§3).

### Physical format — a real gap, not glossed over

**This is the one place where the shape doesn't fall out for free, and it
deserves to be named plainly rather than assumed away.** Today's two
physical item shapes (`parse.py`'s module docstring; schema-reference.md's
`schema_json.md` §12 "two document shapes") are:

- a bare `.md` file, front matter plus one prose body
- a list-file `.yaml` entry, `{id, ..., body}` inside an `items:` array

Neither shape has a slot for "one item, several independently-timestamped
prose bodies." A `.yaml` list-file thread works today's `entries:` shape
cleanly — this is exactly the shape `docs/design-log.md`'s `body: |` block
scalars already use, just nested one level deeper. But **a single-item
`.md` file, the format most real decisions use today** (`checks.md`'s own
example item lives at
`items/decisions/dec-pwr-001-regulator-topology.md`) **has no way to
represent a thread's multiple entries at all** — front matter is one YAML
document, and the body is "everything after the closing fence," singular.

Two ways forward, neither free:

- **Threads are YAML-list-file-only.** Cheapest to implement — `entries:`
  is just another list-valued field, no parser change beyond making
  `entries:` reserved. Cost: every decision currently authored as its own
  `.md` file for readability (a `.yaml` list-file `body: |` block scalar
  is legal but reads worse than a real Markdown file for a paragraph of
  prose) loses that authoring ergonomics. This is a real, disclosed
  regression for exactly the kind of item — a substantial, prose-heavy
  decision — this design is aimed at, not an edge case.
- **A new `.md` multi-entry shape** — some delimiter marking entry
  boundaries inside one Markdown file (a repeated front-matter block, one
  per entry, similar to a multi-document YAML stream). This keeps the
  authoring ergonomics but is real, unbuilt parser surface: `parse.py` is
  740 lines built around exactly two shapes, and a third shape means a new
  boundary-detection pass, new source-line tracking per entry (today
  `item.source_line` is one number; an entry needs its own), and a new
  write-back target for `keys.mint_missing` to append an entry's `key:`
  into the right sub-block.

**Recommendation: start with the list-file-only shape, and prototype the
`.md` shape as a fast-follow if the ergonomics regression proves painful in
practice (§9 item 1).** Shipping the smaller, real thing first and
measuring is cheaper than guessing at a new document format's shape before
anyone has written a thread by hand.

---

## 2. The per-field fold

### The rule

For thread `T` with entries `e₁ ... eₙ` in append order, and foldable field
`F`:

> `fold(T, F)` = the value of `F` on the highest-indexed `eᵢ` that declares
> `F` at all. If no entry ever declares `F`, `fold(T, F)` is undefined —
> exactly like an item today that never sets an optional field.

The crucial part, easy to get wrong: **an entry that omits `F` does not
clear it.** The fold is "most recent entry *that set this field*," not
"most recent entry, whichever fields it happens to carry." This has to be
the rule, not a simplification of it, because the alternative — the whole
latest entry wins, field by field, present or absent — silently loses
history the moment a later entry doesn't restate something an earlier one
said. Worked example, using the thread above:

| Field | Fold source | Fold value |
|---|---|---|
| `status` | entry 3 (`kb4h8m1z2t`) — last to set it | `accepted` |
| `addresses` | entry 1 (`k7f3m2q9x4b`) — the only entry to set it; entries 2–3 never mention it | `[REQ-PWR-002]` |
| `satisfies` | entry 3 — the only entry to set it | `[REQ-PWR-002, REQ-PWR-003]` |
| `title` | entry 3 — the only entry to set it | `Buck converter, not LDO, for the 3V3 rail` |
| `rationale` | entry 3 | the LDO-vs-buck sentence |
| `checks` | entry 3 | `[{value: eff, against: BND-THM-002}]` |

Note `addresses` and `satisfies` **coexist** in the fold — the requirement
is simultaneously "addressed" (from entry 1, never retracted) and
"satisfied" (from entry 3). That is not an accident of this example; it is
the load-bearing property that makes the fold correct for coverage (§5)
without inventing a retraction mechanism: a thread's arc from
investigation to verdict naturally *adds* link names as it goes
(`addresses` early, `satisfies` once settled) rather than replacing one
with another, so "last entry to set each field" already produces the right
cumulative picture without every entry having to restate everything that
still applies.

**Retraction, if ever needed, is explicit.** An entry can set a field to
`null` to clear a prior fold value on purpose — the identical convention
`docs/design/standard-library.md` §2 already uses for a project overlay
removing an inherited schema field (`field: null` deletes it). This is
listed as available, not as something the MVP needs: nothing in this
design requires it, since the ordinary case (a link that stops being
declared) is already handled correctly by "absence doesn't clear."

### What folds, what doesn't

| Kind | Folds? |
|---|---|
| `status`, `title`, `rationale`, and any other scalar field the type declares | yes |
| `options`, `checks` (structured fields) | yes — whole value, most recent entry to declare it |
| Any link name (`satisfies`, `addresses`, `constrained_by`, `blocked_by`, `selects`) | yes |
| `body` | **no** — every entry's body renders in the timeline; there is no single "current body," only the sequence. This is the thing the fold explicitly does not collapse, because collapsing it is exactly what would lose the deliberation. |
| `date`, `author`, entry `key` | not foldable — per-entry metadata, not thread state |
| Thread-level fields (`id`, `key`, `prefix`, `board`, `workspace`, `former_ids`) | not foldable — set once, outside `entries:` entirely |

### `required:` against a fold

`required: true` (and `required_when:`) validates **against the fold, once,
at build time** — not per-entry. A field can legitimately be unset on
every entry except the one that finally sets it (the common case: `status`
absent on every investigation entry, present only on the terminal one),
and that is not a validation failure at any point along the way, because
validation only ever asks "what does the fold currently say," the same
question it asks of an ordinary item's `fields` dict today.

`required_when:` composes with the fold exactly the same way:
`decision.rationale`'s existing rule, `required_when: {status: rejected}`,
becomes `required_when: {status: rejected}` evaluated against
`fold(T, "status")` and `fold(T, "rationale")` — a thread whose folded
status is `rejected` and whose folded rationale is undefined fails the
build, at the thread's own `id`/`source_line` (of the terminal entry that
set `status: rejected`, so the diagnostic points at the entry someone
would actually edit):

```
ERROR items/main-io/threads.yaml:50 [THR-IO-002] — 'rationale' is required
  when status is 'rejected' (required_when: {status: rejected}); entry
  k2p9w3x1r7 set status: rejected but no entry has set rationale
```

This is a genuinely new diagnostic shape (naming the offending *entry*, not
just the item), but it is a small, mechanical extension of the existing
`required_when` error — no new validation *rule*, just a fold-aware source
for the value it checks and a fold-aware source for the location it blames.

---

## 3. Hashing, seals and baselines — the two-hash model

### What each hash covers

Two hashes, deliberately answering different questions, replacing the one
hash (`item.content_hash`) that answers both today:

**Entry hash** — computed once, the first time an entry is built (the
moment it is sealed), over that entry's own on-disk content: every field it
declares (regardless of `on_change`; today's append-only seal already
hashes the *whole* item this way, not just `invalidate` fields — see
`seal._matches_sealed_hash`, which compares against `item.content_hash`,
which in turn is `invalidate`-only... which is itself worth flagging as a
**pre-existing gap this design does not need to inherit**: a `log` field
marked `on_change: log`/`ignore` today can be edited on a sealed entry
without tripping the seal, because sealing piggybacks on the
content-invalidation hash instead of hashing the entry's full content. An
entry hash under threads should hash **everything** the entry declares,
full stop — sealing is a tamper question, not a significance question, and
those are exactly the two questions §"Background" above says this design
separates. This closes a real, latent gap as a side effect, not a new
requirement invented for its own sake) plus its `body`, normalized the same
way body hashing already normalizes whitespace.

```yaml
sealed:
  k7f3m2q9x4b: {thread: THR-PWR-002, hash: b85d98cb24ab9e56}
  k2p9w3x1r7:  {thread: THR-PWR-002, hash: 4a1f7c30ee92b108}
  kb4h8m1z2t:  {thread: THR-PWR-002, hash: 9f03e6b7a1cd4402}
```

Immutable forever once sealed. Editing entry `k2p9w3x1r7`'s body — or
adding a link to it, or changing its `date:` — is caught exactly the way an
edited `log` entry is caught today: `refdes check` verifies without
writing, `refdes build` seals anything new, `--reseal` is the same
disclosed escape hatch. **Appending a new entry to the thread never touches
an existing entry's seal**, because the seal is keyed on the entry's own
key, not the thread's — this is the direct payoff of giving entries their
own identity rather than only sealing at the thread level.

**Fold hash** — a *thread-level* hash, over the current fold's
`invalidate`-mode fields (and folded links, and whichever entry's body
currently backs the thread's `body_on_change`, if any type declares one) —
structurally identical to `_hash_payload` (`build.py:666-692`) today,
except every `item.fields[fname]` lookup becomes `fold(T, fname)`, and
every `item.links[lname]` becomes `fold(T, lname)`. This is what a baseline
stores and what a suspect-link comparison uses (change-tracking.md's whole
mechanism): it moves every time an entry legitimately changes what the
fold currently says, because that's precisely what a content hash is for —
detecting a real change, not detecting tampering.

```yaml
# .refdes/baselines/rev-c.yaml
items:
  kb4h8m1z2t: {id: THR-PWR-002, hash: 673e6ba11269f350, type: thread,
               title: "Buck converter, not LDO, for the 3V3 rail",
               hash_format: 3}
```

Note the baseline entry keys on **the thread's own key**, per
`docs/design/keys.md` §5's existing spec (baselines key on the surrogate,
not the id) — nothing new here, threads simply are the item being keyed.
`hash_format: 3` marks this as a fold hash rather than a hash_format-2
single-item hash, so a mixed-era project (some items, some threads) stays
precisely describable the same way §5's `hash_format` field already
handles the keys-adoption transition — see §7 for what a project with
existing hash_format-2 baselines needs when it migrates.

### Why two hashes and not one

Restating the mechanism from "Background" concretely: appending entry 3
above (the verdict) changes the **fold hash** (status, satisfies, checks
all newly set) but touches **no existing entry hash** — entries 1 and 2's
seals are exactly as they were. A baseline diff correctly reports "this
thread changed" (fold hash moved); `refdes check` correctly reports "no
tampering" (every entry hash still matches its seal). Today, with one hash
serving both jobs, this same append would either have to *not* be an
append-only item at all (so the content hash can move freely — today's
`decision`), or it would have to be forbidden entirely (today's `log`,
where the only way to add information is a brand-new item). Threads are
the first type where "this content is allowed to keep growing" and "this
content, once written, must never be silently rewritten" are simultaneously
true of the *same* record — which is exactly why one hash stops being
enough.

### Baselines: what "removed"/"changed"/"added" mean now

`lifecycle.diff_against` (`lifecycle.py:551-590`) is item-scoped and
hash-only; under threads it stays exactly that shape, just diffing fold
hashes instead of item hashes — no change to its *logic*, only to what
populates `current = _items_map(project)` for a thread (the fold hash and
folded title, not a single item's own hash/title). One genuinely new
question: **a thread with a new entry appended, but whose fold is
byte-identical to before** (an entry that only adds `body` prose, setting
no foldable field at all — a pure narrative addition) has an unchanged
fold hash. Is that `changed` or not? **Recommendation: not changed**,
consistent with the hash's whole job description ("has this item's
*substance* changed") — but this means a baseline diff can under-report
thread activity purely narrative appends don't move. `refdes audit`'s
"Since last revision" summary should therefore report entry counts
alongside the hash-based changed/added/removed columns for threads
specifically, so a reviewer isn't misled into thinking a thread with five
new entries and no status change is quiet:

```
Since last revision (rev-c, 2026-08-10T09:12:00Z):
  changed   2   THR-PWR-002, THR-IO-005
  added     1   THR-PWR-004
  removed   0
  threads with new entries but unchanged fold: 1
    THR-PWR-006 — 3 new entries, fold unchanged
  (36 unchanged)
```

This is new surface, not a reuse of anything existing — flagged rather
than folded silently into the existing counts, because it answers a
question ("did anyone write anything") the changed/unchanged hash split
was never built to answer and shouldn't be stretched to cover.

---

## 4. Links

### Which key a link targets

**By default, a link targets the thread, not an entry** — the mutable,
"current state of this deliberation" identity, resolved and hashed exactly
the way an item is today (`links.expand_missing` writes
`satisfies: [THR-PWR-002@kb4...]` — the thread's own key, minted at thread
creation, never an entry's key). This is the right default because it
matches what an author means the overwhelming majority of the time:
`REQ-PWR-003`'s `satisfied_by` should mean "whatever this thread currently
concludes," tracking the thread as it evolves (including a later
`superseded`/re-litigated status), not "what entry `kb4h8m1z2t` specifically
said on 2026-04-02."

**Pinning to a specific entry is the deliberate exception**, written with
an entry-scoped composite: `THR-PWR-002@kb4h8m1z2t#k2p9w3x1r7` — the
thread's own display-id-and-key composite, plus a second `#`-separated
segment naming the entry key. Two things make this syntactically safe,
both already established: keys.md §3 already reserves `@` (not `#`) as the
composite separator specifically because `#` mid-scalar in block-style YAML
silently truncates the line as a comment — so an entry pin's `#` segment
has to sit *after* the already-resolved `@key`, never adjacent to
whitespace, and the write-back that appends it must never introduce a
space before it. This is a real, sharp edge worth prototyping (§9 item 1),
not a hand-wave: `THR-PWR-002@kb4h8m1z2t #k2p9w3x1r7` (stray space) would
silently drop the entry pin exactly the way keys.md §3 documented `#`
dropping the key entirely.

When would anyone write the entry-pinned form? Genuinely rare — mainly
external citation and audit trail cases: "the schematic note from
2026-08-12 cites the reasoning as it stood in entry `k2p9w3x1r7`, before it
was superseded" is a claim about a moment in time, not about the thread's
current conclusion, and only the pinned form is honest about that. Ordinary
project-internal traceability (`satisfies`, `constrained_by`, `verifies`)
should almost always use the thread form; **the schema does not
distinguish the two syntactically** — both are legal wherever a link to a
`thread`-typed item is legal — so this is an authoring convention worth
documenting, not an enforced rule. Enforcing it (say, forbidding entry-pins
on `satisfies:`) was considered and rejected: it's exactly the kind of
judgment call (§10 of keys.md makes the same call about prefixes) that
should stay a human decision, not a schema restriction with edge cases no
one anticipated.

### Resolving an entry-pinned link

An entry-pinned composite resolves to **the thread**, for every purpose
that already reads `resolved_links` (coverage, `{{cascade}}`, the blocked
chain walk) — an entry isn't independently a link target for graph-walking
purposes, only for hover-preview and rendering purposes, where it matters
*which* entry was cited. Concretely: `item.resolved_links` stays exactly
the shape it is today (thread display ids), and a new,
narrower field — `item.resolved_entry_pins: dict[str, dict[str, str]]`,
link name → target thread id → pinned entry key, populated only for the
subset of targets that used the entry-pinned form — carries the extra
precision for rendering alone. Every consumer that walks the graph
structurally (coverage, blocked_by, cascade) can ignore this field entirely
and be correct; only the item-page renderer and the hover-preview generator
need to consult it, to show "as of entry k2p9w3x1r7" instead of the
thread's live current state in that one preview card.

### Authored on a thread, and pointing at one — both directions unchanged

**Outgoing** — a thread's entries declare links exactly as today's
`decision`/`log` items do (`satisfies:`, `constrained_by:`,
`blocked_by:`, `addresses:`), just per-entry and folded (§2). No new
authoring convention.

**Incoming** — every backlink computation (`inverse_of`, `item.backlinks`)
operates on the fold, i.e. `Project.folded_items[thread.key].links`, not on
any single entry — a requirement's `satisfied_by` backlink comes from
threads whose *current fold* says `satisfies: [that requirement]`,
regardless of which entry set it. This is the "virtual item" framing used
throughout this document (see §5): once a fold is computed, it exposes
`.fields`/`.links`/`.type` in the identical shape `Item` does, and the
inverse-link computation, which already operates generically over any
object with that shape, needs no thread-specific branch at all.

### `supersedes` — one case dissolves, one case doesn't

Finding 17 says supersession "becomes thread continuation, arguably
cleaner than an explicit `supersedes:` edge." That is correct for exactly
one of two cases decision's `supersedes:` covers today, and conflating
them would be a real regression, so it is worth separating precisely:

- **Revisiting the same decision** — new information changes the verdict
  on the *same* question ("we said LDO was fine at 12V, worst-case is
  36V, revise to buck"). This is thread continuation: append an entry with
  a new `status`, no `supersedes:` link needed, exactly finding 17's claim.
- **A new, distinct decision replacing an old, closed one** — a different
  thread entirely (different root question, different entries, possibly a
  different author, opened long after the first thread concluded) that
  happens to make an earlier thread's conclusion moot. This is **not**
  thread continuation — it is two separate threads, and `supersedes:`
  **stays a real, authored, cross-thread link**, folded exactly like any
  other link (§2), targeting the other thread's key.

Both cases exist in real projects; only the first is the one finding 17's
"arguably cleaner" claim actually applies to.

### What dissolves entirely

`amends:`/`amended_by:` and `records:`/`recorded_by:` are both retired as
link verbs, for the same underlying reason — appending to the same thread
now does what a cross-item link used to do:

- **`amends`** — a same-thread correction is just the next entry; no link
  needed. A correction to an *unrelated* thread's entry (rare — genuinely
  a different topic) has no replacement mechanism specced here; it becomes
  a prose cross-reference (`[[THR-...]]`) or, if it recurs often enough in
  practice, a small new link verb — out of scope for this document, since
  nothing in the record of real usage shows it as more than a rare case.
- **`records`** — finding 16 exists entirely to fix a symptom of the
  log/decision split (a sealed log entry can't add `records:` pointing at
  a decision created after it was sealed, without breaking the seal).
  Under threads there is no split to bridge: the entry that documents "this
  is why we decided" and the entry that says "here is the decision" are
  positions in the *same* append-only list, not two items connected by a
  link at all. Finding 16's proposed fix (`recorded_by: [log]` on
  `decision`, using the existing either-end declaration mechanism) becomes
  unnecessary — not because it was wrong, but because the problem it
  solves no longer exists once there's no seal boundary between the
  deliberation and its conclusion.

---

## 5. Coverage

### The virtual-item pattern

Nearly every question in this section reduces to the same move, so it is
worth stating once rather than per-subsection: define a fold projection
that exposes `.fields`, `.resolved_links`, and `.type` in the identical
shape `Item` already does, computed once per build into
`Project.folded_items: dict[str, FoldedItem]` (keyed by thread key,
alongside `project.items` keyed by display id — a thread needs both
lookups for exactly the reasons an item does today). Every consumer listed
below is then a **one-line dispatch** — "if this item's type declares
`entries: true`, read `project.folded_items[item.key]` instead of `item`
itself" — rather than a rewrite of the consumer's own logic. This is the
concrete mechanism behind every "the shape doesn't change, only what
'current' resolves to does" claim below, including the stale-arithmetic
signal's own forward-compat note (§6) and finding 17's concession that
status folding is "a straightforward fold."

### `satisfying_statuses` / `verifying_statuses` under a fold

Today (`build.py:453-462`): `satisfier.fields.get("status")` checked
against `satisfier_spec.satisfying_statuses`. Under threads:
`fold(T, "status")` checked against the identical list — **the exact same
comparison, sourced from the fold instead of `item.fields` directly.** The
five coverage stages (open/addressed/claimed/satisfied/verified,
`coverage.md`) are unchanged in meaning; what changes is only that a
"decision" contributing to `claimed`/`satisfied` is now a thread's fold
rather than a standalone item, and a thread can move backward through
those categories in a way a `decision` item never could (append an entry
that reopens `status: on_hold` after `accepted` — the fold genuinely
un-settles). That reversibility is new and worth naming as a real, if
narrow, behavior change: today, once a decision is `accepted`, an item's
coverage contribution only ever strengthens over the item's life (nothing
un-accepts a decision short of hand-editing it, which would itself trip
the content hash as an ordinary "changed" item). Under threads,
un-settling is a first-class, auditable, append-only operation — this is
one of the real *wins* the fold buys (§"Background"'s "total immutability"
point), not a defect, but it means `coverage.html`'s "satisfied" stage can
legitimately regress between two builds with nothing wrong, and that is
worth a line in the coverage docs when this ships.

### `addressed_by`, and why the per-field fold gets this right without a special case

Walked through concretely in §2's worked example: `addresses` and
`satisfies` coexist in one thread's fold because neither entry retracts
the other. `compute_coverage`'s existing union
(`cov.addressed_by = backlinks ∪ resolved_links["addresses"]`,
`build.py:442-445`) needs no new logic here — it already unions across
*every local item* that backlinks or resolves an `addresses:` edge; under
threads that union is simply over folded items instead of raw items. The
one thing worth flagging (already covered in §2, restated here because
it's a coverage-specific consequence): if this design is ever extended
with the optional explicit-`null` retraction (§2), a thread author who
*does* clear a prior `addresses:` edge would cause a requirement to move
backward from `addressed` toward `open` — again, correctly reflecting
"this thread no longer claims to have worked on that," but a genuine new
way for coverage to regress that today's items structurally cannot
produce.

### `records`/`recorded_by` dissolves; nothing replaces it in coverage

`records`/`recorded_by` never fed `compute_coverage` at all (it isn't in
the satisfied/verified/addressed union — cross-checked against
`build.py:427-479`, which reads `addressed_by`, `satisfied_by`,
`verified_by` only). Its dissolution (§4) has **zero coverage impact** —
worth stating plainly since finding 16 was framed as a traceability
problem, not a coverage one, and this confirms that framing: nothing here
needs replacing on the coverage side.

### Checks stay live, against the *current* fold

The brief's settled point, restated precisely in fold terms: `checks:` is
a foldable field (§2) — `fold(T, "checks")` is the most recent entry's
`checks:` list. **The comparison inside each check stays exactly as live
as it is today** (`build.py:628-644`, `calc.parse_limit(target.fields["limit"])`
re-parsed fresh every build): revising the target bound still flips the
check's pass/fail with no edit to the thread, because the live-evaluation
code path is completely unaware that its `item` argument is now a fold
projection rather than a real item — this is the payoff of the
virtual-item pattern applying cleanly here too. What *does* change from
today: the `env` a check's `value:` resolves against (`item._env`,
`build.py:573`, populated by evaluating `calc` blocks) has to be the env of
**the same entry that declared the `checks:` entry being evaluated** — not
the thread's terminal entry's calc blocks in general, because two
different entries in the same thread could each carry their own,
independent calc blocks (an early feasibility estimate, a later verified
figure) and a `checks:` entry must resolve against the calc block that
sits in the *same* entry, never a different one's. This is a real,
concrete new piece of bookkeeping (`env` becomes per-entry, not per-item),
directly answering the brief's "the fold takes the most recent entry
carrying a calc block" instruction — the fold applies to *which entry's
calc/checks pair is current*, and within that pair, resolution is
unchanged.

### What's left of the "checks vs. decisions" (`check_severity`) split

Unaffected — `check_severity` is still a type-level setting
(`ItemType.check_severity`, `model.py:210`), and a `thread`-typed item
inherits it exactly like any other type. Nothing about folding touches
which diagnostic level a failing check reports at.

---

## 6. The stale-arithmetic signal — confirming the reframe, precisely

`docs/design/stale-arithmetic-signal.md` already sketched this ("Forward-
compat with threads") without designing it, on the theory that keeping the
verdict probe and the calc probe independent would make the reframe small.
Working through the actual fold mechanics above confirms that claim, and
this section states exactly what changes and what doesn't, rather than
leaving it as a promise.

**Today's condition** (baseline `B` vs. current build, for item `X`):
1. `X`'s type declares a `status` field.
2. `X`'s body has a `calc` block.
3. `X.fields["status"]` differs from what `B` recorded.
4. The normalized text of `X`'s calc block hashes the same as what `B`
   recorded.

**Under threads**, for thread `T`, both stored probes move from "the
item's one value" to "the fold's current value," and the comparison logic
is untouched:

1. `T`'s type declares a `status` field (unchanged — a type-level check).
2. `fold(T, "checks")`'s owning entry has a `calc` block (the entry that
   currently backs the folded `checks:` — see §5's per-entry-env note).
3. `fold(T, "status")` differs from what `B` recorded.
4. The normalized calc-block text of **the entry that currently backs
   `fold(T, "checks")`** hashes the same as what `B` recorded.

The baseline gains the identical two fields the original design specified
(`verdict`, `calc_hash`), just sourced from the fold instead of
`item.fields["status"]`/the item's own calc block — no new baseline
machinery beyond what §3 already needs for the fold hash itself, since
`verdict`/`calc_hash` are the same kind of "small extra probe alongside the
hash" the original design already argued for as a narrow, disclosed
exception to `lifecycle.py`'s "assembly, not new machinery" posture. **The
one piece worth calling out as slightly larger than "no change":** probe 4
is no longer simply "this item's calc block," because a thread can carry
several entries each with their own calc block over its life — the probe
has to be pinned to *whichever entry currently backs the folded checks*,
which means the baseline's `calc_hash` field needs to key off the same
per-entry resolution §5 introduces for live check evaluation, not
recompute independently. That's a real dependency between this feature and
§5's per-entry-env bookkeeping, not a new mechanism of its own — the
reframe is as small as the original document claimed, provided it's built
*after* §5's fold-and-per-entry-env plumbing exists, not before.

---

## 7. Migration

### Both a standard version bump and an engine change — same split keys.md already drew

`docs/design/keys.md` §7 argued keys are "orthogonal to the standard
library... an engine and storage concern, exactly like the content hash,
the id ledger, or the board manifest." Threads split the identical way,
and for the identical reason:

- **Engine layer** (new, standard-independent): the `entries:` reserved
  key and its parser support (§1), per-entry key minting (§1), the fold
  computation and `Project.folded_items` (§5), the two-hash model and
  per-entry seals (§3), entry-pinned link composites (§4). None of this
  mentions `log`, `decision`, or any bundled type name. A schema declares
  a type as thread-shaped with a new `ItemType` flag:

  ```yaml
  types:
    thread:
      entries: true          # new engine-level flag, orthogonal to the standard
      prefix: THR
      ...
  ```

  A `standard: none` project, or one pinned at `hardware@1`–`@3`, gets
  none of this until it opts in — exactly keys' posture. A bespoke project
  could declare its own `entries: true` type today, once the engine ships
  it, with no standard-library involvement at all.

- **Standard layer**: `hardware@4`'s `base.yaml` replaces the `log` and
  `decision` type declarations (`standards/hardware/v3/base.yaml:123-193`)
  with one `thread` declaration, `entries: true`, merging their field sets
  (`satisfies`, `constrained_by`, `selects`, `blocked_by` from `decision`;
  `addresses` from `log`; both keep `status`/`rationale`/`options`/`checks`
  as foldable), and a real `migration.yaml` doing the project-content
  transform, below.

### The project-content migration is not a mechanical rename

Every existing `hardware@N → @N+1` migration
(`standards/hardware/v3/migration.yaml` is the current example: renaming
`text:` → `body:` on two types) is a 1:1, per-field, mechanically reversible
rewrite — `revise.py`'s existing `apply()` engine (compute every rewrite in
memory, verify, write once, roll back on any failure) is built entirely
around that shape. **Collapsing N `log` items and M `decision` items into
fewer `thread` items with reordered, re-keyed entries is a different kind
of transform** — it has to *group* items, not just rewrite fields on each
one independently, and grouping is where it stops being mechanical:

1. **Confident grouping** — a `log` item that already declares
   `records: [DEC-X]` (or `DEC-X` already declares the finding-16-shaped
   `recorded_by: [log]`) has an explicit, unambiguous edge to fold into.
   These become one thread, log entries first (by `date:`), the decision
   last.
2. **Heuristic grouping** — a `log` item with no `records:` edge, but
   whose `addresses:` target set overlaps a `decision`'s `satisfies:`
   target set, is a plausible same-thread candidate, not a certain one.
   This is structurally the same confidence-scoring problem
   `former_ids.propose` already solves for a different question (matching
   same-type items across a renumbering by similarity) — reuse its
   propose-then-confirm shape (`former_ids.py`'s `propose`, 43 lines),
   not `revise.apply()`'s atomic-transaction shape. `refdes standard
   upgrade --to 4` should print a proposed grouping and require
   confirmation (or a hand-edited grouping file) before writing anything,
   the same posture `refdes standard remove-preset`'s dry-run already
   takes for a different kind of consequential change.
3. **No group at all** — a `log` item that addresses nothing any decision
   satisfies, or a `decision` with no log entries pointing at it at all
   (a terse, standalone decision — common) — becomes a **single-entry
   thread**, its one existing item folding into one entry unchanged. This
   is the common, easy case and should be the default outcome whenever
   grouping confidence is low, rather than guessing.
4. **Genuinely ambiguous** — a `log` entry `records:`-linked to *two*
   decisions (legal today, `records: [decision]` is a list), or a `log`
   entry amending another `log` entry that itself belongs to a different
   proposed group. These need a human call; the migration tool's job is to
   surface the conflict, not silently pick one, mirroring the ambiguity
   reporting `revise.check_ambiguous` already does for the ordinary
   rename case.

This is real, new migration machinery — closer in size and shape to a
second `former_ids.py` than to an extension of `revise.py`'s existing
engine. It is the single largest unknown in this document's cost estimate
(§9 item 3).

### What happens to old ids

Entries have keys, not display ids (§1) — a former standalone `LOG-A-003`
becomes an entry with no citable id of its own once folded into a thread.
Two consequences, both worth stating rather than discovering later:

- **`former_ids:` moves to the thread**, coarsened: `THR-PWR-002` records
  `former_ids: [LOG-A-003, LOG-A-004, DEC-PWR-001]` (every id that folded
  into it), so an old external citation to any of them still resolves —
  but resolves to the *whole thread*, losing the entry-level precision the
  citation originally had. A schematic sheet from 2025 citing `LOG-A-003`
  will, after migration, land on a page showing the whole deliberation
  arc rather than the one entry it meant. This is a real, disclosed loss
  of precision for old citations, not a silent one — `former_ids`'s
  existing "(formerly LOG-A-003)" marker still fires, it just now marks a
  thread instead of an entry.
- **A finer alternative — anchor links** (`THR-PWR-002.html#k7f3m2q9x4b`,
  or a rendered per-entry "formerly LOG-A-003" marker positioned next to
  the specific entry it used to be) is possible and would close this gap,
  but it needs the migration to record a former-id-to-*entry-key* mapping,
  not just a former-id-to-thread-key one — a real extension to
  `former_ids:`'s current thread-only shape. Flagged as a nice-to-have,
  not required for a first cut (§9).

### Existing baselines and seals

`docs/design/keys.md` §5(c)'s conditional-carry-forward rule (recompute
the old-format hash from current content; carry forward only if it
matches) is the right shape here too, but it cannot be reused verbatim,
because there is no longer a 1:1 mapping from an old baseline entry (one
`log` or `decision` id) to one new entry (one thread key) — a baseline
recorded five old ids that are about to become five entries of *one*
thread. The migration has to rewrite baseline/seal entries *through* the
same grouping decision §"project-content migration" makes, not
independently of it: an old baseline's `LOG-A-003: {hash: ...}` becomes a
seal entry for one specific *entry* key inside a specific thread (§3), and
an old baseline's `DEC-PWR-001: {hash: ...}` becomes the *fold hash* of
whatever thread it landed in — which is **not** simply "carry the old hash
forward," because the fold hash is a different computation over
potentially-different inputs (folded across the whole thread, not one
item's own fields) even when the content genuinely hasn't changed. This
needs its own conditional check, parallel in spirit to §5(c) but not
literally reusable: recompute what the *fold* hash would be from the
grouped, migrated content, and only claim "unchanged since baseline" when
that matches a *reconstruction* of the old per-item hash from the same
grouped content — meaningfully more computation than a straight carry-
forward, and another concrete argument for prototyping the migration path
against a real project with stamped baselines before committing (§9 item
3, shared with the grouping question above since they're the same
underlying data).

---

## 8. What breaks — every consumer that reads stored state

Named concretely, per file, rather than gestured at:

| Consumer | File | What changes |
|---|---|---|
| Content hashing | `build.py:655-767` (`compute_hashes`, `_hash_payload`, `_link_hash_token`) | Splits into entry hash (§3, new) and fold hash (§3, `_hash_payload` reused verbatim against a fold instead of `item.fields`/`item.links`) |
| Coverage | `build.py:380-540` (`compute_coverage`) | Reads folded items for any `entries: true` type (§5); `satisfying_statuses`/`verifying_statuses` checks unchanged in logic, changed in source |
| Checks | `build.py:576-652` (`run_checks`) | `checks:`/`env` resolution becomes per-entry-scoped (§5); live comparison against a bound's `limit:` is unaffected |
| Append-only sealing | `seal.py`, whole file (294 lines) | Rewritten for per-entry seals instead of per-item; `--reseal` semantics need an entry-level scope option alongside the existing board-level one; the `content_hash`-reuse gap noted in §3 is closed as a side effect |
| Baselines | `lifecycle.py:165-260` (`_items_map`, `migrate_hash_format`), `:551-590` (`diff_against`) | Keys on thread key + fold hash (§3); `diff_against`'s logic is unchanged, its inputs are fold-based; new "entries added, fold unchanged" reporting (§3) |
| The stale-arithmetic signal | not yet implemented; `docs/design/stale-arithmetic-signal.md` | Both stored probes move from item-scoped to fold-scoped (§6); depends on §5's per-entry-env plumbing existing first |
| Link resolution | `links.py` (266 lines), `build.resolve_link_target` | Two-tier resolution: thread-key composites (unchanged from keys.md §3) plus the new entry-pinned composite form (§4); `item.resolved_links` stays thread-scoped, a new `resolved_entry_pins` field carries the extra precision |
| Rendering | `render.py` (917 lines) | Thread pages need an entry timeline (reusing `design-log.md`'s existing timeline rendering) *plus* a folded-summary panel (reusing `decision`'s existing verdict/rationale/checks rendering) on one page; hover previews for entry-pinned links show the pinned entry, not the live fold |
| `{{index}}`/`{{cascade}}` generated blocks | `blocks.py` (448 lines) | `{{index by="status" type="thread"}}` groups by `fold(T, "status")`, not a literal field — needs the virtual-item read (§5); `{{cascade}}`'s walk already operates on `resolved_links`, so it is largely unaffected once that's fold-backed |
| `blocked_by`/the cascade report | `blocked.py` (141 lines) | Root-cause walk and the stale-blocker diagnostic (`standard-library.md` §9) both read a blocker's settled status via `satisfying_statuses`/`verifying_statuses` against the fold — same one-line dispatch as coverage |
| `revise`/migration engine | `revise.py` (1,127 lines) | The existing atomic rewrite engine is reused for ordinary field renames within threads (unaffected fields); the log+decision collapse itself needs new, `former_ids`-shaped propose/confirm machinery (§7), not an extension of `apply()` |
| Cross-workspace lint | `workspaces.py` (136 lines) | Reads `resolved_links`; unaffected once that's fold-backed, same as `{{cascade}}` |
| `stub-tests` dedup | `stub_tests.py` (167 lines) | Dedupes by declared `verifies:` edge via `resolved_links`; unaffected for the same reason |
| The release gate | `lifecycle.py` — `_rule_draft_items`, `_draft_field_name` (`:317-339`) | `draft_items` reads `fold(T, "status")` instead of `item.fields.get("status")`; `uncovered_requirements`/`unverified_requirements` unaffected (they read `project.coverage`, already fold-aware via §5) |
| Schema | `schema.py` (531 lines), `schema-reference.md` | New `entries: bool` flag on `ItemType` (§1/§7); schema validation needs to distinguish thread-level fields from entry-level foldable ones — genuinely new schema surface, not a reused mechanism |
| JSON Schema emission | `schema_json.py` (286 lines) | A thread's emitted schema needs an `entries:` array branch with its own per-field shape, distinct from the top-level item branch — a third document shape alongside the two `standard-library.md` §12 already specifies |
| CLI | `cli.py` (1,211 lines) | No new command is strictly required — appending an entry is "edit the file," matching today's log-entry authoring model exactly (`design-log.md`: "Log entries suit a list file — you add to it most days") — but `refdes standard upgrade --to 4`'s propose/confirm flow (§7) is new, non-trivial CLI surface |

**What does *not* need to change:** `calc.py` (777 lines, evaluation logic
is calc-block-scoped already, unaware of items at all), `citations.py` (438
lines, citation resolution is per-field regardless of which item declares
the field), `boards.py`/`nav.py`/`pages.py` (board/workspace/page
machinery is orthogonal to item vs. thread), `parts.py`-shaped indexing
(§10 of `standard-library.md`, keyed on field name not item shape), the
Damm check character and key-minting mechanism itself (reused as-is, §1).

---

## 9. What to prototype before committing

In order of how likely each is to change the design:

1. **The entry-pinned link composite, round-tripped through the real
   write-back path.** `THR-PWR-002@kb4h8m1z2t#k2p9w3x1r7` needs to survive
   flow-style entries, block sequences, and the same write-back hazards
   keys.md §9 item 1 already flagged for the single-`@` case — doubled
   here, since there are now two separator characters in one string
   instead of one.
2. **A real `.md` multi-entry format, or the decision to live without one**
   (§1). This is the one open question in this document with no
   recommendation attached beyond "start without it" — prototype a
   plausible delimiter shape and read it as an author would before
   deciding whether the ergonomics loss of list-file-only threads is
   acceptable in practice.
3. **The log+decision grouping migration, against this repository's own
   project** (20 items, per `docs/design/keys.md` §7's own adoption
   test). Confirm the confident/heuristic/none split (§7) actually
   produces sensible threads on real data, and that the baseline/seal
   reconstruction (§7, closing paragraph) behaves correctly against a
   project with items genuinely changed since their last stamp, not just
   the easy unchanged case.
4. **The per-entry `env`/calc-block resolution for checks** (§5). This is
   the piece of machinery this document introduces with the least direct
   precedent in the current codebase (today, `item._env` is one dict per
   item; under threads it needs to become "one dict per entry that
   declares calc blocks," looked up by whichever entry backs the current
   `checks:` fold) — worth confirming against a thread with two
   independent calc blocks in two different entries before assuming the
   design in §5 is sufficient.
5. **Coverage regression from status un-settling** (§5's "a thread can
   move backward through coverage stages"). Build a small test project
   where a thread's status flips `accepted` → `on_hold` → `accepted` again
   across three builds, and confirm every downstream surface
   (`coverage.html`, the release gate, `refdes audit`'s baseline diff)
   describes that history sensibly rather than just the current snapshot.

---

## Scale

**Rough estimate, not measured** (unlike `docs/design/keys.md` §4's line
tables, which were counted against working code — nothing here has been
built yet to count against): this touches a meaningfully larger fraction
of the ~12,100-line engine than keys did. Keys added one new concept
(identity) threaded through existing single-item machinery; threads add a
new *document shape* (one item, many entries) underneath machinery that
has assumed "one item, one set of fields, one hash" since the first line
of `parse.py` was written. The consumers in §8's table span build.py,
seal.py, lifecycle.py, links.py, render.py, blocks.py, blocked.py,
schema.py, schema_json.py, and revise.py — nine of the ten largest modules
in the codebase — though the *virtual-item* pattern (§5) is specifically
designed to keep most of that contact to a one-line dispatch per call
site rather than a rewrite, so line count is a poor proxy for risk here:
the real cost concentrates in a small number of genuinely new pieces
(the fold engine itself, per-entry sealing, the entry-pinned link
resolver, and the migration's grouping logic) rather than being spread
evenly across the touched files. Those four are exactly §9's prototype
list, in the order that matters most.

---

## Where you might disagree

- **Entry-pinned links resolve to the thread for graph-walking purposes,
  never to the entry itself** (§4). If a project wants coverage or
  `blocked_by` to treat "satisfied as of this specific entry" as
  meaningfully different from "satisfied, currently," this document's
  model doesn't support that — it was a deliberate simplification to keep
  the virtual-item pattern from needing two parallel graphs.
- **List-file-only threads, with the `.md` multi-entry shape deferred**
  (§1). This trades real authoring ergonomics for a smaller first cut. If
  the ergonomics loss turns out to matter more than expected, the honest
  fix is prototyping item 2 sooner, not shipping the smaller version
  permanently.
- **The migration's grouping step needs a human-confirmed propose step,
  not an atomic mechanical transaction** (§7). This is slower and more
  disruptive to run than every prior `standard upgrade` step, and is the
  single biggest departure from this project's existing migration
  discipline. An alternative — ship threads only for *new* content, and
  leave existing `log`/`decision` items exactly as they are, unmigrated,
  forever — avoids this cost entirely at the price of every real project
  living with both shapes side by side indefinitely. Not recommended here,
  but a legitimate fallback if §9 item 3's prototype turns out badly.
- **Sealing hashes an entry's full content, not just its `invalidate`
  fields** (§3), a behavior change from how `log` items are sealed today.
  This closes a real gap, but it is still a change in what "tampering"
  means for anyone relying on today's (arguably accidental) looser
  behavior.
