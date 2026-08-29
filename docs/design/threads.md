# Threads: collapsing `log` and `decision` into a chain of ordinary items — design spec

## Decision (recap)

`decision` retires. `log` absorbs its fields. Every entry — narrative note
or concluding verdict — is an **ordinary item** of one type. An entry
declares its predecessor with a link, `follows:`, written by the tool, not
typed by the author. A **thread** is not a container and not an item: it is
the connected chain of entries reachable by walking `follows:`
backward and its computed inverse, `followed_by:`, forward. What a thread
"currently concludes" is answered by walking forward from any entry in the
chain to its tip(s) and folding per field, the same rule as before, over a
different population.

The decision is taken. This document specs it; it does not relitigate it.

**Status: design only.** Nothing here is implemented.

**Scope note on concurrent work:** this document does not touch, and makes
no claim about, `standards/hardware/v3/base.yaml`, any file under `docs/`
other than this one, `CHANGELOG.md`, or `calc.py`/anything about calc-block
evaluation semantics — those are other sessions' work in progress.
Anywhere this spec would eventually touch one of those files (§5's type
merge, §7's migration file), it says so and stops there.

---

## What changed, and why the previous draft is wrong

The prior version of this document specced a thread as one item containing
a nested `entries:` list — a new sub-structure, with its own key-minting
scope, its own document format problem (no existing shape holds several
independently-timestamped prose bodies in one item), and a two-hash model
to keep "was this entry tampered with" separate from "did the thread's
fold change."

That is not the model. **Each entry is a full, ordinary item** — the same
kind of thing a `log` entry already is today, parsed by the same code,
hashed by the same code, sealed by the same code, capable of living in a
`.md` file or a `.yaml` list file exactly as it can today. The thread is
not a container; it is a property of the link graph. This resolves the
worst compromise in the previous draft (§1's "no multi-entry document
format exists" problem) for free — there is nothing new to hold multiple
entries, because there is no longer a container to hold them in.

What survives from the previous draft, reused rather than re-derived: the
two-tier identity argument from `docs/design/keys.md` (still the thing that
makes this safe), most of the coverage/checks analysis (still correct once
"which item declares this field" is answered by a graph walk instead of a
list scan), and the observation that `records`/`recorded_by` (finding 16)
dissolves. What does not survive: the nested-entry document format, the
two-hash model (§4 — this model needs *zero* new hashing machinery), and
the entry-pinned link composite (§2 replaces it with something the old
draft explicitly said it would need if entries got real independent
identity — they now do, so the composite trick is unnecessary). See the
closing section for the full diff.

---

## 1. The chain

### The link

One new link type, `follows:` — inverse `followed_by:` — declared on the
merged `log` type (§5), restricted to `log` targets:

```yaml
link_types:
  follows: { inverse: followed_by, label: "Follows" }

types:
  log:
    links:
      follows: [log]
      # ...satisfies, constrained_by, addresses, etc. -- §5
```

An entry declares at most its immediate predecessor(s) — plural, because a
merge entry closing a fork (§6) declares more than one. This mirrors every
other link in this vocabulary (`blocked_by` names only the direct blocker;
the chain, like the blocker chain, is walked by a dedicated pass, not
declared transitively by the author).

### The head is inferred, never marked

**An entry with no `follows:` is a head.** No new field, no
`is_thread_start: true` marker, nothing to remember to set. This follows
the same convention the rest of the schema already uses for "the absence
of a declaration is itself meaningful" — `coverable_statuses:` unset means
one specific default (`coverage.md`); `blocked_by: []` unset means
unrestricted (`standard-library.md` §9). Here, unset means "nothing
precedes this," which is simply true the first time anyone writes about a
topic, and needs no author action to be correctly recorded.

**Rejected: an explicit head marker.** It would have to stay
consistent with `follows:`'s absence by construction (a head that also
declares `follows:` is nonsensical), which makes it redundant data with a
consistency rule to enforce, for no benefit inference doesn't already
give for free.

### The chain link is written by the tool

The author never types a key. They write what they'd write today —
a reference to *something* in the thread they mean to continue, most
naturally the head's own display id, since that's the only stable,
memorable name a chain has:

```yaml
# authored
- date: 2026-04-02
  author: J. Bin
  follows: [LOG-A-001]
  summary: Buck converter, not LDO, for the 3V3 rail
  status: accepted
  ...
```

On the next writable build, this resolves — and freezes — exactly the way
an ordinary composite reference already does (`docs/design/keys.md` §3):
the write-back pass walks forward from whatever `LOG-A-001` currently
resolves to, along `followed_by:` backlinks, to the chain's **current
tip**, and rewrites the line to that tip's bare key:

```yaml
# after the next build
- date: 2026-04-02
  author: J. Bin
  follows: [k2p9w3x1r7]
  summary: Buck converter, not LDO, for the 3V3 rail
  status: accepted
  ...
```

Two things are worth being precise about, because they are easy to get
subtly wrong:

- **This reuses the write-back *mechanism*
  (`ids.insert_into_markdown`/`insert_into_list`, keys.md §3) but not its
  *resolution logic*.** Ordinary composite expansion is a static lookup:
  "what key does this display id currently name." Chain resolution is a
  graph walk: "starting from whatever this reference names, follow
  `followed_by:` to the end." A reference to *any* entry in the chain —
  not just the head — resolves the same way, which is the forgiving
  behavior a human actually wants ("continue after DEC-PWR-001" should
  work even if DEC-PWR-001 is three entries back by the time the build
  runs).
- **Resolution happens exactly once, at the moment `follows:` is still a
  bare display-id reference.** Once frozen to a bare key, no later build
  ever re-resolves it — for the identical reason a composite's key half is
  never re-resolved once written (keys.md §3, case 3: "an unknown key is
  an error, and the display half is deliberately not used as a fallback").
  Re-resolving on every build would mean an entry's declared predecessor
  could silently change out from under it as the chain grows — exactly
  the kind of silent identity drift keys exist to prevent. An entry's
  place in the chain, once recorded, is as permanent as the entry itself.

### A concrete, realistic fork — the reason resolving to "the tip" isn't a guarantee against branching

Two engineers, working from the same starting point, each add an entry
referencing `LOG-A-001` before either has seen the other's work:

```yaml
# author A, local build, resolves LOG-A-001's *current* tip -> itself is now the tip
- follows: [k_A_prev_tip]     # frozen against what A's checkout knew

# author B, local build, on an older checkout, same starting reference
- follows: [k_A_prev_tip]     # frozen against the *same* prior tip -- B never saw A's entry
```

Both builds are individually correct — each resolved against the tip its
own checkout could see. Once both land in the same tree, two entries now
share one predecessor: a fork, produced by nothing more than ordinary
concurrent editing, not a bug in either build. §6 covers what happens next.

---

## 2. Identity: entries with a key and no display id

### The place that assumes every item has one

`parse.load_items` (`parse.py:701-731`) is where this gets decided today.
An item with no `id:` is added to `project.pending`, and — unless the
caller passed `require_ids=False` (only `refdes id` itself, `revise.py`,
and `scaffold.py` do) — a hard build error is raised: `"item has no id —
run 'refdes id' to allocate one."` Critically, **a pending item never
enters `project.items` at all.** It sits in a separate list, invisible to
every downstream pass — `compute_coverage`, `compute_hashes`, `run_checks`,
`render_site`, the backlink computation — all of which iterate
`project.items.values()`/`project.local_items`, never `project.pending`.

This is the actual, concrete assumption to fix, and it is stronger than
"a few call sites assume a string is an id." Today, "no id" doesn't mean
"a valid, minimal identity state" — it means "not yet a real project
member, waiting to become one." A chain entry that is *never* going to get
an id needs to be a real project member on arrival: hashed, sealed,
coverage-eligible, renderable, exactly like anything else. `project.pending`
cannot become that state without contradicting what it's for.

### The fix: `project.items` keyed by surrogate key, not display id

`parse.py:740` (`project.items[item.id] = item`) and every place that
constructs, looks up, or iterates that dict needs to stop treating "the
dict key" and "the display id" as the same thing. Concretely:

- `Project.items: dict[str, Item]` — **re-keyed on `item.key`.** Every item
  gets a key on the same schedule it already does (`keys.mint_missing`,
  keys.md §2), so this dict is populated the moment an item is parsed and
  minted, id or no id.
- `Project.items_by_id: dict[str, str]` — a new, small secondary index
  (display id → key), built alongside. Every place that currently does
  `project.items[some_id_string]` — `build.py:239,911`, `blocked.py:112`,
  `cli.py:842`, `former_ids.py:89,127,138,139,160`, `imports.py:100`,
  `ids.py:413`, `render.py:101,103` — is a lookup by a **known display id**
  in a context that only ever deals with id-having items already (the id
  ledger, `former_ids`, an explicit rename target): those sites are
  unaffected in behavior, just rewritten as
  `project.items[project.items_by_id[some_id_string]]` or a small
  `project.item_by_id(id) -> Item | None` helper wrapping that.
- **General link-target resolution** — `build.resolve_link_target`, and
  the `_key_index` it already builds (`build.py:248`) for composite
  `DISPLAY@key` targets — gains a third case: a bare token that is neither
  a known display id nor a `DISPLAY@key` composite, but *is* a
  well-formed key on its own (11 characters, valid Damm check), resolves
  directly against `_key_index`. This is the only place `follows:`'s bare-
  key targets are actually resolved as links, and it is a small, additive
  case next to the two `resolve_link_target` already handles.

This is a real, if mechanical, restructuring — not a two-line patch — and
it is worth naming plainly as the load-bearing engine change this document
requires that the previous draft didn't: **every item, not just chain
entries, moves from "identified by what it's called" to "identified by
what it is," with the display id demoted to an optional, secondary label.**
That is exactly the trajectory keys.md was already on (§8: "the display id
... stops being load-bearing"); this is where that trajectory reaches its
logical end, because a chain entry is the first case where "load-bearing"
would otherwise mean "this item cannot exist without a name nobody needs
to give it."

### The rule that decides "pending" vs. "permanently id-less"

One precise addition to `parse._resolve_id_value`/`load_items`
(`parse.py:238-287`, `701-731`): an item with no `id:` **and** a non-empty
`follows:` is not pending. It skips `project.pending` and the
`require_ids` error entirely, and is added straight to the (now key-keyed)
`project.items`. An item with no `id:` and no `follows:` behaves exactly
as it does today — pending, needs `refdes id`, same diagnostic. The
signal is deliberately the same field that already decides head-vs-
continuation (§1): a continuation entry is, by definition, one that
declares where it continues from, and that is the only fact needed to
tell "doesn't have an id yet" apart from "was never going to have one."

```
follows: absent, id: absent   -> pending (unchanged) -- a head-to-be
follows: absent, id: present  -> ordinary item (unchanged) -- a named head
follows: present, id: absent  -> NEW: permanently id-less, enters project.items directly
follows: present, id: present -> ordinary item (unchanged) -- a citable continuation, if wanted
```

Nothing stops an author from giving a continuation entry an id anyway —
some entries are worth citing individually (a schematic note referencing
one specific bench measurement). Nothing requires it. This is the concrete
form of "only the start of a thread needs a human-facing id": it's a
default, not a restriction.

### `refdes id`, the ledger, and `former_ids`

**Unaffected, because they only ever act on items that already have —
or are actively requesting — a display id.** An id-less continuation entry
never enters `project.pending`, so `refdes id` never sees it, never burns
a ledger number for it, never has anything to allocate. This matches
keys.md §8's own reframing of the ledger as "external-citation hygiene,
not an identity mechanism" precisely: an entry nobody will ever cite by
number simply never needs to reserve one, which is the ledger working
exactly as designed rather than a gap in it.

`former_ids:` needs no new interaction either, for a related reason: it
answers "does this old string still resolve," which only matters for
items that *used to have* a display id. Migration (§7) does not strip ids
from any existing item — every currently-id'd `log`/`decision` item keeps
its id exactly as it is. The id-less state only ever arises for a *new*
entry an author chooses not to name, so there is no "an item lost its id,
now what resolves the old citation" case for this design to solve.

### Rendering: the slug

`Item.slug` (`model.py:427-429`) is `self.id.lower()` — the page filename.
For an id-less entry, this needs a fallback: `self.id.lower() if self.id
else self.key`. Page URLs for id-less entries become
`k2p9w3x1r7.html` — not meant for a human to type, exactly the same
posture keys already have generally (nobody is expected to type a key by
hand; they follow a link to it). `{{index}}` blocks and listing pages
(`refdes ls`) that enumerate a type now also enumerate id-less entries;
their "ID" column shows blank or the key, which is a minor, disclosed
rendering wrinkle, not a defect — the item is real and belongs in the
listing regardless of whether it has a citable name.

---

## 3. What a thread "currently concludes"

### Folding survives, but what it folds over changes

The per-field fold rule from the previous draft is *correct* and is kept
verbatim:

> For field `F`, the current value is whatever the most recent entry *that
> declared `F`* said, walking backward from the tip. An entry that omits
> `F` does not clear it.

What changes is what's being folded. Previously: a list nested inside one
item. Now: a set of separate items discovered by a graph walk along
`follows:`/`followed_by:`.

### Is folding even still needed, or does ordinary link resolution already do the job?

Worth asking honestly rather than assuming, because there's a real case
where it *isn't* needed: `compute_coverage` (`build.py:453-462`) already
unions across every item that declares `satisfies:`/backlinks
`satisfied_by`, and checks `satisfier.fields.get("status")` — the status
of *whichever entry actually declared the link*. If a thread's terminal
entry restates both `status: accepted` and `satisfies: [REQ-PWR-002]` on
itself (the common case — a verdict entry naturally carries both), **no
fold is needed at all**: `satisfier` already *is* the entry with the
current status, and today's coverage code works completely unmodified.

The fold is needed for the case that isn't guaranteed: an entry that
declares `satisfies:` without also restating `status:` on itself — because
an earlier entry set `status: accepted` and nothing since has touched it.
Nothing enforces that authors always co-locate every relevant field on the
one entry declaring the link, and assuming they do would be exactly the
kind of silent, unenforced convention this project's own design docs
routinely flag as a real risk (see `coverage.md`'s own "claimed but not
settled... bit a real migration" story for what happens when a status
check silently reads the wrong thing). So: **fold, but scoped narrowly** —
whenever a consumer needs "the current value of field `F` for the thread
this entry belongs to," resolve it by walking forward from that entry to
the chain's tip(s) and applying the fold rule, rather than trusting that
the entry in hand already carries the answer.

### A lazy walk, not a persistent registry

The previous draft proposed a global `Project.folded_items` table keyed
by one canonical identity per thread. That doesn't survive contact with
merges (§6): a merge entry can join two previously-independent chains,
each with its own head, into one connected component with two heads and
one tip — there is no longer a single key that uniquely names "the
thread" the way there was when a thread was one container item. Trying to
maintain one is solving a problem that doesn't need solving.

Instead: a small utility (new module, playing the same role `blocked.py`
plays for the blocker chain — walk, detect cycles, report) —

```python
def resolve_current(project: Project, start_key: str, field: str) -> Any | None:
    """Walk forward from `start_key` along `followed_by:` to every reachable
    tip, and return the value of `field` from the highest-indexed entry
    (by chain distance from `start_key`) that declares it. `None` if no
    entry in the reachable chain ever declares `field`.
    """
```

— called on demand, from exactly the places that need "the current value,"
not precomputed for every item on every build. This is cheaper when only a
few threads are actually queried (coverage only calls it for items that
already have a `satisfies:`/`verifies:` backlink) and it sidesteps the
multi-head problem entirely: the walk starts from a specific entry (the one
that declared the link being evaluated), not from "the thread," so there is
never a question of which of several heads is canonical.

### `satisfying_statuses` under this model

Today (`build.py:453-462`): `allowed = satisfier_spec.satisfying_statuses;
satisfier.fields.get("status") in allowed`. Under this model:

```python
status = satisfier.fields.get("status")
if status is None:
    status = chains.resolve_current(project, satisfier.key, "status")
allowed = satisfier_spec.satisfying_statuses
```

One extra fallback step, only taken when the declaring entry itself is
silent on `status` — the common case (entry restates its own status)
never pays for the walk at all. This is a small, precise change to
`compute_coverage`, not a rewrite of it.

### Checks stay live — and this needs no fold at all

`checks:` and its owning `calc` blocks are declared and evaluated on **one
entry** (`build.py:576-652`) exactly as `decision.checks:` is today — a
`checks:` entry, its referenced `value:`, and the `calc` block that
defines it all have to live on the *same* item already (checks.md: "`value`
must be a variable defined by a `calc` block in the **same item**"). Under
this model that constraint is unchanged and needs no chain-awareness at
all: whichever entry declares `checks:` also declares the calc block it
checks, on itself, and the live comparison against the target's *current*
`limit:` (`build.py:628-644`) is completely unaffected, because it was
never item-identity-dependent in the first place — it re-parses the
target's `limit:` fresh every build regardless of which item is asking.
This is a genuine simplification over the previous draft, which invented a
per-entry-`env` resolution problem that doesn't exist once entries are
separate items: there's no ambiguity to resolve, because there's no
container in which two different entries' calc blocks could be confused
with each other.

### Branching's effect on "current"

If `resolve_current`'s walk reaches more than one tip (an unmerged fork,
§6), the fold for a field with different values at different tips is
genuinely ambiguous. **Recommendation: treat it as undefined**, the same
outcome as "no entry ever set this field" — a forked, unmerged thread
cannot be read as `satisfied` even if one of its tips independently says
`accepted`, because a fork is, by construction, not yet a single
conclusion. It can still be `claimed` (the union-based `claimed`/`satisfied`
split in `coverage.md` already distinguishes "linked, not yet settled"
from "settled"), which is the right coverage stage for "someone has
concluded something here, but the thread hasn't reconciled" — reusing an
existing distinction instead of inventing a sixth coverage stage for forks.

---

## 4. Hashing and seals

### Confirmed: unchanged, per entry

**Each entry is an ordinary item, so its own hash and its own seal work
exactly as they do today, with zero new machinery.** `compute_hashes`
(`build.py:731-766`) computes `item.content_hash` over the entry's own
`invalidate` fields, links, and body — unmodified. `seal.py`, in its
entirety, is unaffected: an append-only-typed entry is sealed the first
time it's built, and any edit to it — including an edit to its
`follows:` link, once frozen — is caught the same way an edited `log`
entry is caught today. **Appending to a chain means creating a brand-new
item; it never touches an existing entry's hash or seal, because nothing
about appending edits an existing file.** This is the direct, complete
answer to why the previous draft's two-hash model doesn't exist under this
one: that model existed to solve a problem — one item, multiple mutable-
yet-sealed sub-records — that this model doesn't have. An entry is never
simultaneously "still growing" and "already sealed"; it's sealed, full
stop, the moment it's first built, exactly like `log` today.

One thing worth confirming rather than assuming: sealing today hashes via
`item.content_hash`, which is `invalidate`-fields-only
(`seal._matches_sealed_hash`, `seal.py:65-104`, compares directly against
it) — so a field marked `on_change: log`/`ignore` can already be edited on
a sealed entry today without tripping the seal. That's a pre-existing
gap, orthogonal to this design, not something threads introduce or need to
fix; noted so it isn't mistaken for a new problem.

### What, if anything, still needs a thread-level hash

**Nothing load-bearing.** Coverage, checks, and the release gate all read
the fold's *values* directly (§3), not a hash of them — there's no
tamper-detection or change-detection question that a chain-level hash
would answer that per-entry hashing doesn't already answer on its own. If
`REQ-PWR-002`'s `satisfied_by` moves from one entry to a newer one (the
chain grew, and the new tip took over the `satisfies:` declaration), that
already shows up as an ordinary backlink change — no new hash needed to
notice it.

One place a **derived, optional, reporting-only** digest is genuinely
useful: `refdes audit`'s "since last baseline" summary. A chain that
gained five narrative entries but no field-level change reads as
completely silent under hash-based diffing (§3 of the previous draft
flagged exactly this case) — worth a coarse "has anything happened here"
signal for a human skimming the report, computed at report time by
hashing the sorted list of the chain's own entry hashes (a hash-of-hashes,
purely for display), never stored, never compared against anything but
itself between two `audit` runs. This is optional polish, not required for
correctness, and it needs no new baseline field to exist — see next.

### Baselines need no new fields at all

This is a real, positive simplification over the previous draft, worth
stating plainly: `lifecycle._items_map` (`lifecycle.py:165-183`) already
records one row per local item — `{hash, type, title, hash_format}` — and
under this model an entry *is* a local item, so it already gets a row,
with no change to the baseline schema whatsoever. `diff_against`
(`lifecycle.py:551-590`) is item-scoped and hash-only already; it reports
a new entry as `added`, exactly correct — a chain growing by one entry
*is* one item added, which is the truest possible description of what
happened. Nothing about "which thread this belongs to" needs recording in
the baseline for `diff_against`'s own job.

The one place this matters for a *different* consumer:
`docs/design/stale-arithmetic-signal.md`'s forward-compat note
anticipated needing a fold sourced from "the thread" rather than one
item — under this model, that reframes as: reconstruct "the chain's
status/calc state as of the baseline" by walking the *same*
`resolve_current` logic (§3), restricted to only the entries the baseline
itself recorded (filter the walk to keys present in `baseline.items`),
and compare that against `resolve_current` over the *current* project.
Two walks, same function, different scopes — no new baseline fields, no
new stored probes, because the baseline's existing per-item rows already
carry everything the reconstruction needs.

---

## 5. Does `decision` still exist?

**No — recommend retiring it, with `log` absorbing its fields.** Argued,
not assumed:

`decision`'s distinguishing properties today are: mutable (`status`,
`rationale`, `checks` can all be edited in place) and not append-only.
Under this model, **every entry is append-only** — revising a verdict
means appending a new entry, never editing an old one, which is the
entire premise of the chain. That erases the one structural property that
justified `decision` being a separate, differently-behaved type from
`log` in the first place. What's left distinguishing them is purely which
*optional* fields an entry happens to use — a terse note sets `date`,
`author`, `body`, maybe `addresses`; a verdict entry additionally sets
`status`, `rationale`, `checks`, `satisfies`. Nothing in the schema engine
needs two types to express "this item uses a larger subset of its type's
optional fields than that one does" — that's what optional fields already
mean, and forcing a rigid type boundary between "narrative" and "verdict"
would make the natural, common case (one entry that both reports a bench
result *and* moves the status forward) awkward to write.

`log` is the type that survives and absorbs, not the reverse, because it
was already closer to this model's shape — already `append_only: true`,
already the type whose whole authoring convention is "add to it most days"
(`docs/design-log.md`). The unified type:

```yaml
types:
  log:
    prefix: LOG
    label: Log entry
    plural: Log entries
    append_only: true
    preview: [date, author, status, summary]
    satisfying_statuses: [accepted]     # from decision
    check_severity: error               # from decision
    fields:
      date:      { type: date, required: true, on_change: invalidate }
      summary:   { type: text, required: true, on_change: invalidate }
      author:    { type: person, on_change: invalidate }
      status:    { type: enum, on_change: invalidate,
                   choices: [proposed, in_progress, accepted, on_hold, rejected, superseded] }
      rationale: { type: text, on_change: invalidate, required_when: {status: rejected} }
      options:   { type: options, on_change: invalidate }
      checks:    { type: checks, on_change: invalidate }
    include: [provenance]
    links:
      follows:        [log]         # new -- §1
      addresses:      [requirement, bound]
      satisfies:      [requirement]  # from decision
      constrained_by: [bound]        # from decision
      selects:        [component]    # from decision
      supersedes:     [log]          # from decision, retargeted -- §6
      blocked_by:     []             # from decision
    body: { on_change: invalidate }
```

Real, disclosed field-level decisions this makes, each worth naming:

- **`title` (decision) is dropped in favor of `summary` (log)**, already
  required, already serving the same "one-line label" role. This is the
  same kind of field unification `hardware@3` already did once
  (`text:`/`method:` → `body:`, `model.py:191-198`'s comment on
  `body_required`) — precedent exists in this codebase for exactly this
  move, not a novel risk.
- **`status` becomes optional** (it's required on `decision` today, not
  declared at all on `log`). A narrative entry legitimately never sets it;
  `satisfying_statuses`/`required_when: {status: rejected}` both already
  tolerate an absent field correctly (§2 of `standard-library.md`).
- **`stewardship` (`owner`, `last_reviewed`) is dropped**, matching `log`'s
  existing exclusion of it (`standard-library.md` §1: "an append-only
  entry has no reviewer rotation") — a verdict entry doesn't get a
  reviewer-rotation field back just because it absorbed `decision`'s job.
- **`option` (the design-debate preset) is untouched.** This merge is
  scoped to `log`/`decision` only, matching the scoping discipline
  `standard-library.md` already uses when it explicitly declines to widen
  a change beyond its stated target.

### What this costs the standard

This is standard-content, not engine content (mirroring the split keys.md
§7 already drew) — it lands in `standards/hardware/v4/base.yaml` and a
real `migration.yaml`, neither written here (another session owns
`v3/base.yaml`; a `v4` is this design's business once it's implemented,
not this document's). §7 covers what that migration has to do.

---

## 6. Branching and merging

### Two entries claiming the same predecessor

**Legal, not an error.** §1's worked example shows this arising from
ordinary concurrent editing, with nobody doing anything wrong — forbidding
it outright would forbid a normal, recoverable outcome of two people
working at once, and this is a file-based tool with no locking mechanism
that could prevent it in the first place. Detected the same way the
`blocked_by` cycle walk already is (`standard-library.md` §9: "checked
once, as a dedicated build step... after ordinary link resolution"),
reusing that pattern for a chain-fork check instead of a cycle check:

```
INFO items/main-io/log.yaml:40 [LOG-A-009] — this thread has forked: both
  LOG-A-009 and LOG-A-011 declare follows: [k2p9w3x1r7]. Coverage and
  checks treat an unmerged fork as unsettled -- append an entry declaring
  follows: [both tips] to reconcile it, or leave the fork if the two
  continuations are genuinely independent.
```

`info`, not `error` or even `warning` by default — matching the
`blocked_by` stale-check's own reasoning (`standard-library.md` §9): a
project with active parallel investigation trips this normally, and it
would be noise at a higher severity. `refdes audit` always shows it
regardless of visibility settings, the same posture every other `info`
finding in this area already takes.

### Merging

An entry closes a fork by declaring `follows:` on more than one tip —
already legal syntax (`follows:` is a list, like every other link), no new
schema shape:

```yaml
- date: 2026-04-05
  author: J. Bin
  follows: [k_tip_a, k_tip_b]
  summary: Reconciled -- going with the buck topology from the parallel
    thermal analysis; the EMI concern from the other branch is addressed
    by the added ferrite bead (see BND-EMI-004).
  status: accepted
```

After this entry, `resolve_current`'s walk from either original tip
reaches this single new tip — the fork is closed, `satisfying_statuses`
can settle again (§3).

### Cycles

A hard build error, reusing `blocked_by`'s exact cycle-detection shape
(`standard-library.md` §9) against the new edge type — `follows:` asserts
a DAG the identical way `blocked_by:` does, and nothing about the check
itself needs to differ beyond which link name it walks.

### A chain superseding one that isn't its own

**`supersedes:` stays a real, ordinary, cross-chain link**, distinct from
`follows:`, and the distinction matters: `follows:` says "I continue *this*
deliberation"; `supersedes:` says "I am a different, later deliberation
that makes an old, separate one moot." These answer different questions
and collapsing them would be wrong — a thread revising its own conclusion
(new information, same question) is thread continuation via `follows:`,
no `supersedes:` needed; a wholly separate decision replacing an old,
already-concluded one (different question, different chain, opened
independently) is `supersedes:`, targeting the old chain's — most
naturally its head's — display id, resolved and folded exactly like
`satisfies:` or any other ordinary link. Nothing about `supersedes:`
needs chain-awareness at all; it's an inter-chain edge, not an intra-chain
one.

### `amends:` — decoupled from chain topology, not retired

The previous draft retired `amends:` on the theory that a same-thread
correction is just the next entry. That's still true for the common case,
but it isn't the whole of what `amends:` does today: `docs/design-log.md`
lets an entry amend *any* earlier entry, not only the current tip — a
correction discovered later can point at exactly the entry it corrects,
even if other entries happened in between. Under strict `follows:`-only
chaining, pointing at anything other than the current tip *is* branching
(§6, above) — which may be exactly right (a correction really is a
divergence from what was believed) but conflates two different facts:
"where does this sit in the chain" and "what, specifically, does this
correct." **Recommendation: keep `amends:` as a plain, non-chain-forming
annotation** — an ordinary link that names what an entry corrects without
affecting `follows:`/`followed_by:` topology or the fold at all. An entry
can (and typically will) declare both: `follows:` for its place in the
chain, `amends:` for what it's correcting, which may or may not be its own
immediate predecessor.

`records:`/`recorded_by:` — finding 16's whole problem — still dissolves,
for the reason the previous draft gave: the deliberation and its
conclusion are positions in the same chain now, no cross-item link needed
to associate them. A genuinely cross-chain "this entry's reasoning also
fed a different, unrelated decision" case is rare enough in the record of
real usage that this document doesn't propose a replacement mechanism for
it — same disclosed gap `amends:` has for a cross-chain correction, use
prose (`[[...]]`) until it proves common enough to need more.

---

## 7. Migration

### Simpler than the previous draft's, and worth saying so plainly

The previous draft needed a `former_ids`-shaped propose/confirm tool to
*group* existing items into new containers — real, substantial, new
machinery. **This model needs no grouping step for correctness at all.**
Every existing `log` item stays exactly what it is (already the surviving
type). Every existing `decision` item becomes a `log` item with its fields
carried over — a mechanical, per-item rename, structurally identical in
shape to the `text:`/`method:` → `body:` migration `hardware@3` already
shipped (`standards/hardware/v3/migration.yaml`), reusing `revise.py`'s
existing atomic-rewrite engine (`apply()`) with no new transaction model
needed:

```yaml
# sketch of standards/hardware/v4/migration.yaml -- fields: section only,
# for illustration; the real file is another session's/a later change's to write
fields:
  decision:            # keyed by the OLD type name
    title: null         # dropped -- summary already exists and serves the role (§5)
types:
  decision: log         # type rename; decision's own fields merge into log's
```

No item loses its id. No item's content hash needs reconstructing beyond
what a type rename already requires (the type name is itself part of the
hash payload, `build.py:676` — a `decision` → `log` rename already
legitimately changes the hash the same way any type rename does today,
and `revise.py`'s existing baseline/seal carry-forward machinery
(`_carry_forward_baselines`, `_carry_forward_seals`) already handles
exactly this case, unmodified). **This is the standard `refdes standard
upgrade --to N` path this project already has, not new machinery.**

### What migration does *not* do

**It does not retroactively construct `follows:` chains.** An existing
project's `log`/`decision` items become standalone, id-having, `follows:`-
less heads — single-entry threads, one per existing item, with zero data
loss and zero risk. This is correct and sufficient: nothing about
coverage, checks, hashing, or rendering requires an item to be part of a
multi-entry chain; a chain of length one is exactly as valid as one of
length five (§1: absence of `follows:` just means "nothing precedes
this," which is true).

**Reconstructing historical chains — inferring `follows:` edges from
existing `records:`/`addresses:` overlap between old `log` and `decision`
items — is optional, best-effort, separate tooling**, decoupled entirely
from the type-merge migration above. It would reuse the same
confidence-scored propose/confirm shape `former_ids.propose` already has
(43 lines, `former_ids.py`), for the identical reason: matching "which log
entries led to this decision" from indirect evidence (shared `addresses:`
targets, proximity in `date:`) is a similarity-scoring problem, not a
mechanical one, and should stay opt-in and human-confirmed rather than
folded into the required upgrade path. Whether this is ever built is a
separate decision from whether `hardware@4` ships at all.

### Standard version, or engine change, or both

Both, and the split is the identical one keys.md §7 already drew for a
different feature: the engine layer (`follows:`/`followed_by:` as a link
type any project can declare; the id-optional item state, §2; the
`resolve_current` walk, §3) is standard-independent — a bespoke
`standard: none` project can declare its own chainable type today, once
the engine ships this, with no involvement from the bundled standard at
all. The standard layer (`hardware@4` merging `log`/`decision`) is a
version bump on top of that engine capability, exactly as `hardware@3`'s
`body:` unification was a version bump on top of engine capabilities that
already existed independently.

---

## 8. What breaks — per file, concretely

| Consumer | File | What changes |
|---|---|---|
| Item storage | `parse.py:701-740` (`load_items`, `_resolve_id_value`) | `project.items` re-keyed on `item.key`; new rule distinguishing "pending" from "permanently id-less" via `follows:` presence (§2) |
| Project model | `model.py` (`Project.items`, new `Project.items_by_id`) | Re-keying (§2); `Item.slug` falls back to `self.key` when `self.id` is empty |
| Link-target resolution | `build.py:248` (`_key_index`), `build.resolve_link_target` | New third case: a bare, well-formed key with no display half resolves directly (§2) — this is the only place `follows:`'s targets actually get resolved |
| Chain write-back | new, alongside `links.expand_missing` (`links.py`) | Reuses `ids.insert_into_markdown`/`insert_into_list` (mechanism), new resolution logic: walk forward to the current tip, freeze once (§1) |
| Coverage | `build.py:380-540` (`compute_coverage`) | Small, precise addition: fall back to `resolve_current(..., "status")` only when the declaring entry itself doesn't set `status` (§3) |
| Checks | `build.py:576-652` (`run_checks`) | **Unaffected** — confirmed, not merely assumed (§3) |
| Hashing | `build.py:655-767` (`compute_hashes`) | **Unaffected** — confirmed (§4) |
| Seals | `seal.py`, whole file | **Unaffected** — confirmed (§4) |
| Baselines | `lifecycle.py:165-260`, `:551-590` | **Unaffected** — no new fields (§4); the stale-arithmetic signal's forward-compat note reframes as two scoped walks, no new baseline schema |
| Fork/cycle detection | new module, shaped like `blocked.py` (141 lines) | Chain-fork `info` diagnostic and `follows:` cycle `error`, both reusing `blocked_by`'s existing walk-and-detect pattern (§6) |
| The chain-fold utility | new module | `resolve_current` (§3) — the one genuinely new piece of query machinery this design adds |
| `former_ids` / the id ledger | `former_ids.py`, `ids.py` | **Unaffected** — confirmed (§2) |
| Rendering | `render.py` | Page slugs for id-less items fall back to key (§2); a chain view (reusing `design-log.md`'s existing timeline rendering, plus a "currently concludes" panel sourced from `resolve_current`) — no new document type, an extension of existing item-page rendering |
| `{{index}}`/`{{cascade}}` | `blocks.py` (448 lines) | `{{index by="status" type="log"}}` needs the same `resolve_current` fallback coverage uses, for the identical reason (§3); `{{cascade}}`'s existing walk is otherwise unaffected |
| `blocked_by` cascade | `blocked.py` | Unaffected in its own logic; its cycle-detection *pattern* is reused (not shared code) for `follows:` (§6) |
| `revise`/migration engine | `revise.py` (1,127 lines) | **Reused as-is** for the type-merge migration (§7) — no new transaction model, unlike the previous draft's conclusion |
| Schema | `schema.py`, `schema-reference.md` | New link type `follows`/`followed_by`; no new schema *surface* beyond an ordinary link declaration — no `entries:` shape, no per-entry sub-schema, both eliminated relative to the previous draft |
| CLI | `cli.py` | No new command strictly required — appending a continuation entry is "write the file, run a writable command," identical to writing a `log` entry today |

**What does *not* need to change, beyond what §4/§8 above already
confirms:** `citations.py`, `calc.py` (explicitly out of scope for this
document — another session's work), `boards.py`/`nav.py`/`pages.py`,
`workspaces.py`, `stub_tests.py` — all of these read `resolved_links`,
which is unaffected in shape; the only new thing they'd need is the same
`resolve_current` fallback coverage uses, and only if they turn out to
query a field that isn't reliably co-located with the link declaration,
which — unlike coverage's `satisfying_statuses` — none of them currently
do.

---

## Scale

Meaningfully smaller than the previous draft's estimate, and it's worth
being explicit about why: the previous draft's cost concentrated in a
projection engine, a two-hash model, a new document format, and a
bespoke migration tool — four separate pieces of substantial new
machinery. This model needs one new piece of real machinery
(`resolve_current` and the fork/cycle check that goes with it, together
well under `blocked.py`'s 141 lines), one structural but mechanical
refactor (`project.items` re-keyed on surrogate key, §2 — touching perhaps
a dozen call sites, each a small, well-understood change), and confirms —
rather than invents — that hashing, seals, baselines, and checks need
**no changes at all**. The standard-layer migration reuses existing,
proven machinery outright (§7). If the previous draft was "a third to a
half of the engine has some contact with this," this one is closer to
"three or four files gain real new logic, a dozen more gain a small,
mechanical fix, and the rest are confirmed unaffected."

---

## Where the new model is worse, honestly

- **Branching is a real new failure mode a nested-entry model structurally
  couldn't have.** A list inside one item can't fork; a graph of separate
  items can, and does, from nothing more than ordinary concurrent editing
  (§1's worked example). This needs its own diagnostic and its own
  coverage-stage rule (§3, §6) — real, new complexity the previous draft's
  wrong model didn't have to solve, precisely because it was wrong in a
  way that happened to avoid this problem.
- **The fold is a graph walk across files, not a list scan within one.**
  Cheaper to author into (no new document format), more expensive to
  compute and reason about — `resolve_current` has to cross file
  boundaries and handle a DAG with possibly multiple heads and multiple
  tips, where the previous (wrong) model's fold was a single, bounded,
  in-memory list.
- **An entry's place in a narrative is no longer visually contiguous.**
  Today's `log.yaml` list file shows a whole conversation in one place,
  read top to bottom. Under this model, a chain's entries can legitimately
  scatter across different files (different boards, different authors'
  working files) with only the `follows:` graph — not physical proximity —
  showing they belong together. The rendered chain view (§8) exists
  specifically to compensate for this; it is a compensating mechanism,
  not evidence the underlying authoring experience is as good as reading
  one file top to bottom.

## Where it's better

- **No new document format.** The previous draft's single largest,
  least-resolved cost (§1 in that draft) is eliminated outright — entries
  are ordinary items in the two shapes that already exist.
- **Hashing and seals need zero new machinery**, confirmed in §4, against
  the previous draft's two-hash model — a real, load-bearing piece of
  complexity that turns out not to be needed once entries have independent
  identity.
- **Migration reuses `revise.py`'s existing engine outright** (§7),
  against the previous draft's bespoke propose/confirm tool — because
  there is no grouping step required for correctness, only an optional,
  decoupled, best-effort one.
- **Checks need no per-entry-env resolution problem** (§3) — that
  complexity in the previous draft was an artifact of entries sharing a
  container; it doesn't exist once each entry is independently the thing
  that owns its own calc blocks, exactly as `decision` already is today.

---

## Diff from the previous draft, summarized

| | Previous draft | This draft |
|---|---|---|
| An entry is | a sub-record inside one `thread` item | an ordinary item |
| Document format | new, unbuilt (`.md` multi-entry shape needed) | none needed — existing `.md`/`.yaml` shapes work unchanged |
| Chain/thread identity | the container item's own key | emergent from the `follows:`/`followed_by:` graph; no single canonical key once merges exist |
| Link target for "continue this" | a new `#`-separated entry-pin composite | a bare key, written by a tool-mediated write-back reusing the existing composite mechanism |
| Hashing/seals | two-hash model (entry hash + fold hash), new machinery | unchanged, per-entry, zero new machinery |
| Baselines | new fold-hash fields per thread | no new fields |
| Coverage/checks | virtual-item projection table, computed per build | small, targeted fallback (`resolve_current`), called on demand |
| `decision` as a type | not fully resolved — flagged as an open question leaning toward keeping it | retired; merges into `log` |
| Migration | bespoke propose/confirm grouping tool, required | mechanical type-merge via existing `revise.py`; grouping is optional and decoupled |
| Branching | not addressed (the container model couldn't fork) | first-class: forks are legal, detected, foldable-to-undefined until merged |
| Biggest new risk | the multi-entry document format | `project.items` re-keying (§2) and branching (§6) |
