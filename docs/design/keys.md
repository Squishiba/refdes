# Surrogate keys: identity separate from the display id — design spec

## Decision (recap)

Every item gains an **opaque, immutable surrogate key**, assigned by the
tool, never typed and never read by a human. Links resolve on the key. The
human-facing id (`REQ-IO-AI-001`) becomes a **display label** that can change
freely, because nothing points at it.

Storage stays plain text. This is explicitly **not** a move to a database —
the point of keys is to make the text format durable enough that a database
is never needed. Every file a human edits stays a file a human can read,
diff, and merge.

The decision is taken. This document specs it; it does not relitigate it.

**Implementation status:** §1 (key format) and the minting half of §2 are
implemented (`refdes/keys.py`, wired into `cli._load()`). Everything else —
link resolution on the key (§3), hashing on the key (§5), the corruption
lint (§6), `refdes keys adopt` (§7), and any change to `revise.py` or
`former_ids.py` — is still design only, deliberately sequenced as later
work rather than landed alongside the format and minting in one pass.

---

### Why this is the root fix

Nearly every id problem this project has hit traces to one cause: the id is
simultaneously the permanent identity *and* the string a person writes and
reads. Those two jobs want opposite properties.

| Identity wants | Authoring wants |
|---|---|
| opaque — no information to become wrong | memorable — `REQ-PWR-002`, not `k7f3` |
| stable — never changes, ever | revisable — reorganise, renumber, re-prefix |
| meaningless — no prefix to mismatch | meaningful — the prefix *is* the point |
| unique by construction | unique by convention and bookkeeping |

Every mechanism in the columns below exists to force one string to satisfy
both. Separate the jobs and the mechanisms stop being load-bearing:

- the **ledger** and burned numbers (`ids.py`) — a number must never be
  reused because an old reference might still resolve to it
- **expand-and-freeze** for bare-numeric ids, and **prefix validation** as a
  hard error — because "the id is the one string every link, backlink, and
  ledger entry is keyed on" (`ids.py:104-140`)
- the **`revise` engine's** prefix half — 363 of its 1091 lines (§4)
- **`former_ids`** and its title-similarity inference — reconstructing an
  identity that was destroyed by a renumbering
- **hash carry-forward** across baselines and seals, so a cosmetic rename
  doesn't read as a content change
- the standard library's **`prefixes:` migration** discipline, and the
  refusal-and-rollback machinery guarding it

None of that is bad code. All of it is the cost of one design choice.

**The first concrete bug that *requires* this, rather than merely benefiting
from it** (issue #6, finding 10 part 2): allocate `REQ-001`, delete that
item, hand-type a *different* item with `id: REQ-001`, run `check`. It
passes silently — the ledger's own "never reused, even after an item is
deleted" guarantee, broken. Investigated at length (see the finding's own
thread): every check considered — comparing against the ledger's `burned`
ceiling, against the `allocated` list, against a hypothetical proper
per-number burned set — either false-positives on ordinary projects (a
hand-typed id sitting below some other, unrelated id's number is completely
normal, not reuse) or fails to catch the repro. The reason is structural,
not a gap in the checks tried: "the same item, never touched" and "the
original item deleted, a different item hand-typed with its exact former
id" produce **byte-identical on-disk state** — the same ledger entry, the
same single item named `REQ-001` in the parsed project. No function
computed from that state can return different answers for two inputs it
cannot tell apart. This is exactly the identity/display split this document
argues for: once a key is what a link resolves on and what a baseline
records, the two histories stop being indistinguishable — the deleted
item's key is simply gone (an ordinary `removed` diff line), and the new
item mints its own, different key, however it happens to be labelled. See
§6's Layer 4 for the mechanism that catches it once keys exist.

---

## 1. Key format

### Recommendation

**Eleven characters: ten random data characters plus one check character,
Crockford base32, lowercase.**

```
k7f3m2q9x4b
└────┬────┘└┬┘
  10 data   check
```

- **Alphabet** — Crockford base32, `0123456789abcdefghjkmnpqrstvwxyz`
  (32 symbols; `i`, `l`, `o`, `u` excluded).
- **Entropy** — 10 × 5 = **50 bits**, from `secrets.token_bytes`.
- **Check character** — Damm, over a fixed 32×32 totally anti-symmetric
  quasigroup table (amended from the original recommendation of Luhn mod 32;
  see below).
- **Case** — lowercase, always. Never normalised on read: a key containing
  an uppercase character is malformed, not silently folded.

### Why lowercase (this one is mechanical, not aesthetic)

`BARE_REF_RE` (`build.py:30`) matches a prose reference as
`[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6}` — it *requires* an uppercase start.
A lowercase key can therefore never be mistaken for a bare display-id
reference in prose, with no new exclusion rule anywhere. The same asymmetry
makes keys trivially greppable and makes a key visually unmistakable inside
a composite: `REQ-IO-AI-001@k7f3m2q9x4b` reads as label-then-key at a
glance, without knowing the syntax.

### Why 50 bits

Keys are minted independently with no coordination — that is the entire
reason they cost nothing to mint (§2). So collision resistance has to come
from the size of the space. Birthday-bound probability of *any* collision in
a resolution scope of `n` items:

| data chars | bits | space | n=10,000 | n=100,000 | n=1,000,000 |
|---|---|---|---|---|---|
| 8 | 40 | 1.10e12 | 4.6e-05 | 4.5e-03 | **0.37** |
| **10** | **50** | **1.13e15** | **4.4e-08** | **4.4e-06** | **4.4e-04** |
| 12 | 60 | 1.15e18 | 4.3e-11 | 4.3e-09 | 4.3e-07 |

Eight data characters is tempting for brevity and is what informal examples
tend to reach for, but it fails at scale in a way that matters: a federated
setup importing a dozen projects can plausibly reach 10⁵ items, and 1-in-220
is not a risk worth carrying for two saved characters. Twelve buys three
more orders of magnitude for two more characters of line noise in every
link. **Ten is the knee.**

Note what a collision actually costs: two items claiming one key inside a
resolution scope is a **hard load-time error** (§6), never a silent
mis-resolution. So the table is a probability of *annoyance* — regenerate
one key, fix its inbound references — not of corruption. That is what
licenses accepting 4.4e-06 rather than demanding 4.3e-11.

### The check character: argued for, and honestly bounded

**For.** The user's framing is right, and it is worth being precise about
what it buys. Without a check character these two situations are
indistinguishable:

- a key that was damaged (bad merge, stray keystroke, truncated paste)
- a key that is intact but names an item that no longer exists

They need opposite responses. The first says "your file is corrupt, restore
this line"; the second says "the item this pointed at is gone, relink or
restore it." Conflating them sends someone hunting through git history for
an item that was never deleted. A check character separates them
mechanically, and the diagnostics can then say different things (§6).

**Bounded.** The check character is a *diagnostic quality* mechanism, not a
correctness mechanism. Correctness comes from keys being resolved and
unknown keys being errors. A corrupted key that happens to pass the check
still fails resolution — it degrades to today's behaviour (a dangling
reference), not to silent breakage. This is worth stating plainly so the
check character is never mistaken for a safety guarantee it isn't.

**Decided: Damm, not Luhn mod 32 as originally recommended.** This section
originally recommended Luhn mod 32 and treated Damm as a later upgrade "if
there is appetite for the table now." There was: the user weighed the cost
(a 1,024-entry table to construct and verify) against Luhn's one real gap and
chose Damm outright, before any project had adopted keys and while the
window from §9 point 5 was still open. The reasoning, for the record:

**Verified properties**, measured rather than recalled the same way for both
algorithms (3,000 minted keys, all valid in each case; 170,500 single-character
substitutions and 4,836 adjacent transpositions tested against Luhn mod 32;
1,023,000 single-character substitutions and 29,111 adjacent transpositions
tested against Damm — the count differs only because the two runs iterated
the alphabet/keys slightly differently, not because of any difference in
method):

| property | Luhn mod 32 | Damm |
|---|---|---|
| single-character substitutions rejected | 170,500 / 170,500 — 100% | **1,023,000 / 1,023,000 — 100%** |
| adjacent transpositions rejected | 4,821 / 4,836 — 99.69% | **29,111 / 29,111 — 100%** |
| random 11-char strings accepted by chance | 3,077 / 100,000 ≈ 1/32 | 3,088 / 100,000 ≈ 1/32 |

Both hit 100% on single-character substitution, the stated primary goal.
Where they differ is transposition: Luhn mod 32's 0.31% gap is pairs
differing by exactly half the modulus — a known, structural weakness of the
algorithm, not a measurement artefact — while a totally anti-symmetric
quasigroup catches every adjacent transposition by construction, not by
the luck of which pairs happen to get typed. That is a clean, provable
property rather than "good enough in practice," and it is what tipped the
decision: the marginal cost (one more source file holding a constant table,
verified once by a property test, never touched again) was judged worth
paying for a mechanism with no known gap, rather than one with a
characterised 0.31% hole. Both numbers above stay in this document because
the comparison is the argument — deleting the Luhn side would leave the
decision unjustified.

**What this changes downstream.** The check character is still purely a
*diagnostic quality* mechanism (the "Bounded" paragraph above is unaffected
by which algorithm computes it) — Damm does not change what correctness
depends on, only how good the "your key is corrupt" diagnostic's coverage is.
Layer 1 of §6 (well-formedness) is the only place the algorithm choice is
externally visible; nothing about §2 through §5 depends on which check
character scheme is in use.

**The table itself is now a permanent compatibility contract.** The moment
the first key is minted against a specific 32×32 table, that table cannot
change again without invalidating every key minted under the old one — a
corrupted-vs-valid verdict would silently flip for keys nobody touched. It
must therefore be a **fixed constant compiled into the package**, never
generated per-project, per-run, or written into a project's own files: a
table that could vary between installs would make a key valid in one repo
and corrupt in another, which defeats the entire point of a check character.
This also closes §9 point 5 and the corresponding bullet in §10 — the
decision is made, not a prototype question anymore.

**Rejected: a leading sigil** (`k7f3m2q9x4b` with a mandated `k`). The `@`
separator already marks the key structurally, and lowercase already
distinguishes it. A sigil costs a character in every link to restate what
position and case already say. It also cannot be `@` itself: PyYAML rejects
a plain scalar beginning with `@` outright (`ScannerError`), so any
sigil would have to be an ordinary alphabet character and would silently
reduce the entropy of the first position to zero.

### Generation

```python
ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"

def mint() -> str:
    data = "".join(ALPHABET[b % 32] for b in secrets.token_bytes(10))
    return data + check_char(data)
```

`secrets`, not `random` — not because an adversary matters, but because it
removes any possibility of a seeded generator making two projects mint the
same sequence, and it costs nothing.

---

## 2. When a key is minted

### The argument, restated

`refdes id` is a deliberate, separate command because allocation is
**consequential**: it draws the next number from a shared ledger, burns it
permanently, and produces a string that people will cite in schematics and
email. Running it by accident has consequences; running it twice matters.

A surrogate key has none of those properties. There is no sequence, no
ledger, nothing burned, no coordination, and nobody ever reads it. Minting a
key is as consequential as assigning a variable name in generated code.

**Therefore keys are minted automatically, by any command that already loads
the project and is permitted to write.** There is no new step in anyone's
workflow, no new command to learn, and no way to forget.

### Which commands

Every command routed through `cli._load()` — `check`, `build`, `index`,
`id`, `fetch`, `audit` — plus `revise`, `standard upgrade`, `stub-tests` and
`former-ids`. Concretely: after `parse.load_items()` and before
`build.build()`, a `keys.mint_missing(project)` pass assigns a key to every
local item lacking one and writes it back into the source file, using the
same `insert_into_markdown` / `insert_into_list` write-back `refdes id`
already uses (`ids.py:191-264`).

This is the same posture the project already takes with `.refdes/schema.json`
— "a cheap side effect of loading, not a job of its own" (`cli.py:43-47`).

### `--no-write`

A **global** flag, alongside `-c/--config`, not a per-command one:

```
refdes [-c CONFIG] [--no-write] <command> ...
```

**Definition: never modify anything under `items/` or `.refdes/`.** That
covers key minting, display-half refresh (§3), `.refdes/schema.json`
regeneration, the seal file, the boards manifest, and the id ledger.

It deliberately does *not* cover a command's own declared output:
`refdes build --no-write` still writes `_site/`, because rendering the site
is what the command is *for*, not a side effect of loading. Naming it
`--no-write` and scoping it to the source tree is the least surprising
reading; `--read-only` would imply the site too.

Who needs it:

- **CI**, checking out a tree and asserting it builds without mutating it —
  today a CI run that touches `.refdes/schema.json` can dirty a tree and
  confuse a subsequent "no uncommitted changes" gate
- **Inspecting someone else's project**, or a read-only checkout
- **A `git bisect`** or any automated pass over historical commits, where
  minting keys into old trees would be actively wrong

### An item with no key yet

**Keyless items stay fully usable.** They parse, validate, get a page, count
toward coverage, and appear in `items.json`. A key is not a precondition for
existing; it is a precondition for being *durably referenced*.

Resolution rule, stated once and applied everywhere:

> A link resolves on the key when a key is present in the reference. When no
> key is present — the reference is a bare display id — it resolves on the
> display id, exactly as today.

So a keyless project is a working project, and adoption is incremental
rather than a flag day (§7). The keyless state self-heals on the next
writable command.

Reporting: one project-level `info` line, not one per item —

```
INFO    <project> — 12 item(s) have no key yet; the next writable command will
        mint them. Run without --no-write, or see docs/design/keys.md.
```

`info`, not `warning`, because under `--no-write` it is the expected and
correct state, and a warning that fires on every CI run is a warning people
learn to ignore.

---

## 3. How a link is written and stored

### The shape — confirmed, with evidence

The author types exactly what they type today:

```yaml
satisfies: [REQ-IO-AI-001]
```

The tool expands and freezes it:

```yaml
satisfies: [REQ-IO-AI-001@k7f3m2q9x4b]
```

**Resolution uses only the part after the separator.** The readable half is
tool-maintained: refreshed whenever the target's display id changes, and
never consulted for resolution.

This is the right shape, and it is worth noting the project already has this
exact pattern working: `refdes id` expands a bare-numeric `id: "042"` into a
full id and freezes it. Composite link expansion is the same move applied to
references, which makes it familiar rather than novel.

### The separator must be `@`, and `#` is a genuine trap

The user's instinct here is correct and the evidence is worse than expected.
Measured against PyYAML:

| input | result |
|---|---|
| `satisfies: [REQ-001@k7f3m2q9x4b]` | ✅ `['REQ-001@k7f3m2q9x4b']` |
| `satisfies:`<br>`  - REQ-001@k7f3m2q9x4b` | ✅ `['REQ-001@k7f3m2q9x4b']` |
| `satisfies: [REQ-001#k7f3m2q9x4b]` | ✅ `['REQ-001#k7f3m2q9x4b']` |
| `satisfies: [REQ-001 #k7f3m2q9x4b]` | ❌ **`ParserError`** |
| `satisfies:`<br>`  - REQ-001 #k7f3m2q9x4b` | ⚠️ **`['REQ-001']`** — key silently dropped |

The last row is the one that settles it. A stray space before `#` in
block style is not an error: YAML reads the rest of the line as a comment,
the key vanishes, and the link silently falls back to display-id resolution.
That is precisely the class of silent failure this project keeps finding and
fixing — a reference that looks right, parses clean, and quietly means
something else. **Use `@`.**

`@` is a YAML reserved indicator only in *leading* position; mid-scalar it
is an ordinary character, confirmed above.

### Alternatives considered

**Bare keys, `satisfies: [k7f3m2q9x4b]`.** Rejected — this undercuts the
entire reason for staying in text. A diff showing `- k7f3m2q9x4b` `+
k2p9w3x1r7` is unreviewable, and a merge conflict in one is unresolvable
without tooling. If links are unreadable, the format is a database with
extra steps.

**Sidecar map, `.refdes/keys.yaml` mapping key → display id.** Rejected, but
it is the obvious alternative and deserves a real answer: it keeps item
files marginally cleaner at the cost of a second file that can desync from
the first, cannot be merged independently of it, and must be consulted to
read any link at all. It converts a local, self-describing reference into a
lookup. The composite keeps the file self-describing.

**Key first, `k7f3m2q9x4b@REQ-IO-AI-001`.** Rejected — the readable half
should lead because that is what a human scans, and because sorting a link
list would otherwise sort by opaque key, scrambling an order that currently
reads sensibly.

**Structured, `satisfies: [{id: REQ-IO-AI-001, key: k7f3m2q9x4b}]`.**
Rejected — verbose, changes the shape of every link value, and breaks the
hard requirement that an author writes what they write today.

### On the item itself

```yaml
- id: REQ-IO-AI-001
  key: k7f3m2q9x4b
  text: The AI accelerator rail shall regulate to 0.85 V ±3%.
```

`key:` sits immediately after `id:`, written by the tool. It becomes a
**reserved key** in `parse.RESERVED` alongside `id`, `type`, `history`,
`body`, `former_ids` — *not* an overridable one like `prefix`/`board`/
`workspace`. Identity must not be shadowable by a type that happens to
declare a field called `key`. No bundled type declares one today, so the
practical blast radius is a project with a hand-rolled `key` field; §7 flags
this as the one adoption-time breaking change.

### Refresh, and one case that must not be silent

When a display id changes, inbound composites are rewritten on the next
writable command. Three cases, deliberately not treated alike:

1. **Display half stale, key resolves, old display id matches nothing
   live** — the ordinary rename. Silently refreshed. No diagnostic; this is
   bookkeeping, and the diff shows it.

2. **Display half stale, key resolves, old display half matches a
   *different* live item** — do **not** silently refresh. This is the
   signature of a bad merge crossing two references. Warn, naming both:

   ```
   WARNING items/io/decisions.md:14 [DEC-IO-005] — satisfies references
           'REQ-IO-AI-001@k7f3m2q9x4b', but that key is REQ-IO-AI-004 and
           REQ-IO-AI-001 is a different live item. Refusing to refresh the
           label until you confirm which was meant.
   ```

3. **Key does not resolve** — an error, and the display half is *not* used
   as a fallback (§6). Falling back would resurrect exactly the ambiguity
   keys exist to remove.

### Prose references are unchanged

`[[REQ-PWR-002]]` and bare `REQ-PWR-002` in prose stay display-id-only.
Humans write prose; humans must never type a key. This means prose
references remain breakable by a renumbering — which is what `former_ids`
is for, and is now essentially its whole job (§4).

---

## 4. What this does to the existing machinery

Measured against the current tree, not estimated.

### `revise.py` — 1,091 lines, of which ~363 are identity machinery

| function | lines | fate under keys |
|---|---|---|
| `_rewrite_reference_ids` | 60 | **gone** — references carry keys; nothing to rewrite |
| `_rewrite_block_sequence` | 26 | **gone** — existed only to reach block-style link lists |
| `_rewrite_id_tokens` | 16 | **gone** |
| `_rename_prefix` | 21 | **gone** — compound-prefix matching was an identity concern |
| `_relabel_id` | 11 | **gone** |
| `_relabel_ledger` | 28 | **gone** (see §8 on the ledger) |
| `_restore_ledger` | 4 | **gone** |
| `_stale_prose_references` | 44 | **stays** — prose still breaks; still worth reporting |
| `_carry_forward_baselines` | 65 | **shrinks** — loses the id-remapping half, keeps hash swap |
| `_carry_forward_seals` | 42 | **shrinks** — same |
| `_capture_seal_files` / `_restore_seal_files` | 46 | **stays** — rollback is still rollback |

**Roughly 166 lines delete outright**, and ~107 more lose their most
delicate dimension. `Mapping.prefixes` and its collision checks in
`check_ambiguous` go with them, along with the ledger interaction that made
prefix renames refuse when a target prefix already had burned ids.

The deeper win is not line count. It is that **a prefix rename stops being a
transaction**. Today `refdes standard upgrade --to 2` renaming `CON` → `BND`
must atomically rewrite item ids, every structured reference to them, the
ledger, every baseline, and every seal — with rollback if any step fails,
because a half-applied rename leaves dangling references. Under keys, that
same rename touches only `id:` lines and the *display halves* of inbound
composites. If it were interrupted halfway, nothing would be broken —
resolution never used those strings. The all-or-nothing machinery stays for
type and field renames (which do change hashes, §5), but the prefix case
stops needing it.

### `former_ids.py` — 164 lines, survives with a much smaller job

`propose` (43 lines) exists to answer: *which new item replaced this old
id?* It answers it by diffing a baseline, matching same-type items by
title similarity, scoring confidence, and asking a human to confirm —
because the identity linking them was destroyed by the renumbering.

**With keys, that question is a lookup.** The item kept its key; the tool
knows with certainty that `CAN_00` became `REQ-CAN-001`. The similarity
scoring, the confidence percentages and the `--confirm` gate all become
unnecessary for the internal case: the tool can simply report every display
id that changed since the last baseline, exactly and without inference.

What remains for `former_ids:` is the case it is genuinely good at, and the
user is right that it survives: **an external citation.** A schematic, a
test report, a supplier email, a PDF from 2024 says `CAN_00`. That artefact
knows nothing about keys and never will. `former_ids: [CAN_00]` on the item
makes that string resolve, with the existing visible "(formerly CAN_00)"
marker. That is a display-alias mechanism, and it stays exactly as it is.

The validation in `ids.collect_former_ids` (47 lines) — a former id must not
collide with a live id, must not be claimed twice — stays too, because it
guards display-id resolution, which still exists.

### `ids.py` — 386 lines

`insert_into_markdown` / `insert_into_list` (74 lines) not only stay but
gain a second caller: key write-back uses the identical mechanism. `split_id`
and `prefix_for` stay. The ledger functions (`load_ledger`, `save_ledger`,
`high_water`, ~45 lines) and `allocate`'s two-pass numbering (122 lines)
survive but stop being load-bearing for correctness — see §8, which treats
"should the ledger survive at all" as the real question it is.

`validate_prefixes` (40 lines) stays but **relaxes from error to warning**.
Its docstring today justifies the hard error explicitly: fixing a mismatch
automatically "would change the one string every link, backlink, and ledger
entry is keyed on." Under keys, that sentence is false — the id is keyed on
by nothing. A mismatched prefix becomes what it always felt like: a
cosmetic inconsistency worth flagging, not a build-stopping fault.

### The migration files and standard-version discipline

`hardware@2`'s migration carries `prefixes: {CON: BND}`. Under keys that
entry still does useful work — it keeps display ids consistent with the new
vocabulary — but it stops being *dangerous*. The elaborate guarantees around
it (never merge chained steps lest a freed name collide; refuse if the
target prefix has burned ids; carry hashes forward so the rename doesn't
read as a content change) were all protecting identity.

**Type and field renames are unaffected and still need the full apparatus**,
because they change what is hashed (§5). The standard-version discipline
itself — pin an integer, byte-identical forever, one `migration.yaml` per
version — is untouched and still correct. Keys reduce the *stakes* of one
category of migration; they do not remove the need for versioning.

### Test surface

533 tests, of which 291 mention `prefix`, 66 `former_id`, 25 `ledger`, 16
`burn`. Not all of those are identity tests, but the concentration shows
where the complexity has been. Expect a substantial net *reduction* in test
count alongside a small number of new, sharper tests (§6's lint especially).

---

## 5. Content hashing, seals and baselines

### What is hashed today

`build.compute_hashes` (`build.py:539-567`) builds a payload of:

- `type` — the type name
- every field whose `on_change` is `invalidate`
- `link:<name>` → **the sorted list of link target strings**
- `body`, normalised, if the body is `invalidate`

Note what is *already* absent: `item.id`. The display id is not hashed, and
never has been. Renaming an item therefore already does not churn *its own*
hash.

### The one change required — and it is load-bearing

**`link:<name>` currently hashes display-id strings.** So renaming
`CON-THM-001` → `BND-THM-001` churns the content hash of every item that
links to it, even though nothing about those items' content changed. That is
exactly the churn keys exist to eliminate, and it is *not* eliminated by
keys unless this is changed.

**Spec: link targets are hashed as their resolved keys, never as the
composite text and never as the display id.**

```python
for lname in sorted(item.links):
    payload[f"link:{lname}"] = sorted(t.key for t in resolved(item.links[lname]))
```

With that change, a display rename churns nothing anywhere in the project.
Without it, keys deliver readability and lose the main prize.

### What is *not* hashed

**The item's own key is not hashed.** Two reasons, both decisive:

1. If the key were hashed, *minting* a key would change every item's hash —
   adoption would rewrite every hash in the project for no content reason.
2. The key is identity, not content. An item's hash answers "has this item's
   substance changed"; identity is the thing being asked *about*, not part
   of the answer.

**The display id is not hashed** (unchanged from today) — that is what makes
it free to change.

### The type name stays in the hash — and this is a real limit

I recommend keeping `payload["type"]` as is. An item changing type is a
genuine content change and should invalidate. The consequence is worth
stating plainly rather than discovering later: **a schema-vocabulary rename
(`constraint` → `bound`, `title` → `text`) still churns hashes and still
needs `revise`'s carry-forward.** Keys do not make `revise` unnecessary;
they make its *prefix* half unnecessary.

If churn on type renames later proves painful, the alternative is to hash a
type's own surrogate key rather than its name — extending this design from
items to schema entities. That is a larger change and should not be bundled
in. Flagged as a possible successor, not a recommendation.

### Baselines

`lifecycle._items_map` (`lifecycle.py:164-170`) keys the snapshot by
`item.id`:

```python
{item.id: {"hash": ..., "type": ..., "title": ...} for item in project.local_items}
```

**Spec: baselines key on the surrogate key, and record the display id as a
field.**

```yaml
kind: revision
name: rev-c
stamped_at: '2026-08-22T09:12:00Z'
hash_format: 2
items:
  k7f3m2q9x4b: {id: REQ-IO-AI-001, hash: 673e6ba11269f350, type: requirement, title: ...}
```

This is what makes the diff say the true thing. Today, renaming an item
between two baselines reads as one item removed and one added; the tool
cannot know they are the same thing, which is the whole reason
`former-ids propose` had to guess. Keyed on the surrogate, the same rename
reads as what it is:

```
Since last revision (rev-c, 2026-08-21T09:12:00Z):
  changed   0
  added     0
  removed   0
  relabelled 1   CON-THM-001 -> BND-THM-001   (k7f3m2q9x4b)
  (17 unchanged)
```

`relabelled` is a new, fourth diff category, and it is only expressible
because identity survived the rename.

### Seals

`.refdes/log-seal-<board>.yaml` maps id → hash. Same change: **key on the
surrogate**, carry the display id as a comment or a sibling field for
readability.

```yaml
sealed:
  k7f3m2q9x4b: {id: LOG-A-001, hash: b85d98cb24ab9e56}
```

The payoff is direct: today, renaming a sealed log entry's id requires
`revise` to rewrite the seal file in the same transaction or the next build
fails with a seal violation — an *error*, not a diff. Under keys, a rename
touches the seal file not at all.

### `hash_format: 2` and what happens on adoption

Changing what `link:` hashes changes every hash of every item that has
links. Existing baselines and seals record hashes under the old definition.
Three options:

- **(a) Recompute on adoption** — wrong. The baseline records what content
  *was* at stamp time; recomputing from current content asserts nothing
  changed since, destroying the diff.
- **(b) Stamp `hash_format: 2` and refuse to compare across formats** —
  honest but lossy: every pre-adoption baseline becomes undiffable.
- **(c) Carry forward conditionally** — **recommended.**

(c) reuses a rule already implemented and proven in
`revise._carry_forward_baselines`: swap a stored hash for the new one **only
when the stored hash equals what the item hashes to under the old
definition**. If it matches, the content demonstrably has not changed, so
the new-format hash of current content is the correct new-format hash of
baseline content, and the entry can be re-keyed and rewritten. If it does
not match, the item genuinely changed since the stamp; leave the entry
alone, keyed by display id, marked `hash_format: 1` and reported as
uncomparable rather than guessed at.

Record `hash_format` per entry, not per file, so a partially-carried
baseline is precisely described. Same rule for seals.

---

## 6. Corruption and detection

### The asymmetry that makes this tractable

A display id has legitimate reasons to change. A surrogate key has **none,
ever**. Any change to a key is therefore provably a bug — a bad merge, a
hand-edit, a script gone wrong — and can be detected mechanically without
heuristics. This is the strongest property of the whole design and it should
be exploited aggressively.

### Layer 1 — well-formedness, no context needed

A key is malformed if it is not exactly 11 characters, contains a character
outside the alphabet (including uppercase, including the excluded `i l o u`),
or fails its check character.

```
ERROR   items/io/requirements.yaml:12 [REQ-IO-AI-001] — key 'k7f3m2q9x4c' is
        malformed: check character mismatch. A key is written by refdes and
        never edited by hand, so this line has been corrupted — restore it
        from git rather than guessing. (Expected check character 'b'.)
```

Note what this diagnostic can say *because* of the check character: **this
is corrupt**, not "no such item". Without it, the same edit produces a
manhunt for a deleted item.

### Layer 2 — uniqueness within the resolution scope

Two items claiming one key is a hard error, always, independent of any
baseline:

```
ERROR   items/io/requirements.yaml:18 [REQ-IO-AI-004] — key 'k7f3m2q9x4b' is
        already used by REQ-IO-AI-001 (items/io/requirements.yaml:12). A key
        is unique by construction; two items sharing one means a line was
        duplicated. Delete the key from one of them and rebuild — it will be
        re-minted.
```

This is the mechanism that makes §1's collision probability an annoyance
rather than a hazard. It also catches the most likely real-world duplication
cause: copy-pasting an item block and editing the visible fields.

### Layer 3 — resolution

An unknown key is an error, and the display half is deliberately **not**
used as a fallback:

```
ERROR   items/io/decisions.md:8 [DEC-IO-005] — satisfies points at key
        'k2p9w3x1r7' (labelled REQ-IO-AI-001), which no item declares. The
        label may be stale; the key is what resolves. Either the target was
        deleted, or this reference predates it.
```

### Layer 4 — the baseline lint

This is the one the asymmetry buys, and it should be a standing check, not
an opt-in. **`refdes check` compares every item's key against the most
recent baseline of either kind.**

For each entry in the baseline, keyed `K` with display id `D`:

| situation | verdict |
|---|---|
| an item declares `K` | fine, whatever its display id now is |
| no item declares `K`; an item at the same source position, or with display id `D`, or with the same title and type, declares `K′` | **key changed — error** |
| no item declares `K`; nothing plausibly corresponds | item deleted — the ordinary `removed` diff line, not an error |
| an item that the baseline recorded with key `K` now has no key at all | **key deleted — error** |

```
ERROR   items/io/requirements.yaml:12 [REQ-IO-AI-001] — key changed since
        baseline 'rev-c': was 'k7f3m2q9x4b', now 'k2p9w3x1r7'. A key never
        changes legitimately. Every reference and every baseline entry
        pointing at the old key now dangles. Restore the old key; if the
        item really is a new one, delete the key line and let it be
        re-minted, and give it a new display id too.
```

Two properties worth calling out. First, it is **provable** — no similarity
scoring, no confidence, no confirmation prompt, unlike `former-ids propose`
today. Second, it is **cheap**: the baseline is already loaded for the diff.

The one false positive to guard: legitimately *replacing* an item — deleting
one and creating a different one that happens to occupy the same file
position with a similar title. Handled by requiring the display id to be
unchanged too before calling it a key change, and by the remedy in the
diagnostic naming the deliberate path ("delete the key line... and give it a
new display id too").

### Layer 5 — a key changed while a baseline references it

Covered by layer 4 for the most recent baseline. For *older* baselines,
recommend reporting at `info` in `refdes audit` rather than erroring in
`check`: an old baseline referencing a key that no longer exists may simply
predate a legitimate deletion, and turning that into a build error would
make old baselines a liability. `audit` is where "what has drifted" already
lives.

---

## 7. Migration

### Is this a standard version bump? No — it is orthogonal

Clearly and deliberately **orthogonal to the standard library.** The
standard defines *vocabulary*: types, their fields, link verbs, status
lifecycles. A surrogate key is none of those. It is an engine and storage
concern, exactly like the content hash, the id ledger, or the board manifest
— none of which the standard describes.

Concretely: a `standard: none` project gets keys. A project pinned at
`hardware@1` gets keys without moving its pin. No `migration.yaml` mentions
keys. `hardware@3` is not needed and should not be minted for this.

The one engine-level change with a compatibility surface is `key:` joining
`parse.RESERVED`. No bundled type at any version declares a `key` field, so
this affects only a hand-rolled schema that does. That is a real if narrow
breaking change and belongs in the changelog with that framing.

### `refdes keys adopt`

Adoption should be **one explicit, transactional command**, even though
minting is otherwise automatic — because adoption rewrites every item file
and every baseline at once, and that deserves to be a reviewable commit
rather than a side effect of someone running `refdes check`.

```
$ refdes keys adopt
minted 20 key(s)
expanded 34 link reference(s) to composite form
baselines rebased: rev-b (17/17 entries carried), rev-c (20/20 entries carried)
seals rebased: board-a (6 entries)
  .refdes/log-seal-board-a.yaml
Nothing else changed. Review the diff before committing.
```

It reuses `revise.apply`'s existing safety model wholesale — compute every
rewrite in memory, verify the reloaded project is as clean as the original,
write only then, roll back completely on any failure. That machinery already
exists, is tested, and is exactly the right shape. Adoption should cost
little new code beyond the minting and the composite expansion.

**Ordering inside the transaction**, which matters:

1. mint a key for every local item
2. expand every link reference to composite form (resolving by display id —
   the last moment at which that is the resolution rule)
3. re-key baselines and seals, carrying hashes forward under §5(c)'s
   conditional rule
4. reload, fully validate, and only then write

### What happens to existing links written as bare display ids

They keep working. §2's resolution rule means a bare display id resolves by
display id, so a project mid-adoption — or one that never adopts — is not
broken. The practical consequence: **adoption is not mandatory and not a
flag day.** A project can run `refdes keys adopt` when convenient, or simply
let the automatic minting fill keys in over time as files are touched.

I recommend the explicit command anyway, for one reason: a scattered
adoption produces a scattered diff over weeks, and the one moment when
reviewing this change is easy is when it is a single commit that touches
only keys.

### This repository's own project

20 items, 6 sealed log entries, no baselines currently stamped, and a
`.refdes/ids.yaml` with four burned prefixes. It is a good adoption test
precisely because it exercises the sealed-log path and the compound-prefix
convention. Worth doing on a branch and reading the whole diff.

---

## 8. What remains of the display id, prefixes, the ledger and `refdes id`

### The display id

Everything user-facing. It is still what appears on the page, in the
document, in `coverage.html`, in prose references, in `refdes audit`, and in
what people say to each other. Nothing about the authoring experience
changes. It simply stops being load-bearing.

**Duplicate display ids stay a hard error.** Prose references (`[[REQ-001]]`
and bare `REQ-001`) resolve by display id, so two items sharing one makes
those references ambiguous. Keys do not rescue this and should not be
claimed to.

### Prefixes

Unchanged as a convention and still worth having — `REQ-A-PWR` still tells a
reader more than `REQ`. What changes is the *enforcement posture*:
`validate_prefixes`'s hard error becomes a warning (§4), because its stated
justification no longer holds.

### Should the ledger survive? — the real question

Its guarantee: **a number is never reused, even after the item using it is
deleted.** Worth taking seriously why that guarantee exists, because keys
make part of it automatic and part of it not.

**The part keys make automatic.** Reuse used to risk an old *internal*
reference silently resolving to a different item. Under keys, internal
references carry keys and cannot be captured by a reused display id. That
risk is gone entirely.

**The part keys do not touch.** An *external* citation — a schematic sheet,
a test report, an email saying "per REQ-PWR-005" — resolves by display id or
not at all. If `REQ-PWR-005` is deleted and later reissued to an unrelated
item, that external citation silently becomes a lie. No key can help,
because the schematic does not have one.

That is the same case `former_ids:` now exists to serve (§4), and it is a
real case in this domain — a PCB fabricated in 2025 has a paper trail that
outlives any refactor.

**Recommendation: keep the ledger, and demote it explicitly.**

- **Keep** `refdes id`, the ledger file, and burned-number tracking. The
  cost is one committed YAML file and it protects a case nothing else does.
- **Reframe** it in the docs: the ledger is no longer an identity mechanism.
  It is external-citation hygiene. That reframing matters because it changes
  what people should feel free to do — renumbering becomes cheap and safe,
  and the ledger's job is only to stop a *retired* number from coming back.
- **Relax** what a ledger conflict means. Two branches allocating the same
  number is today a genuine hazard; under keys it is a display collision,
  caught as a duplicate display id and fixable by renaming one, with no
  reference anywhere needing to move.

**The alternative, honestly stated:** drop the ledger, let display ids be
freely reassignable, and rely on `former_ids:` alone for external citations.
This is defensible — it removes a shared mutable file that causes merge
conflicts, and `former_ids:` is a more precise instrument (it says *this*
old id means *this* item, rather than merely preventing reuse). I do not
recommend it, because `former_ids:` requires someone to remember to record
the alias at renumbering time, whereas the ledger protects the case where
nobody remembered. Prevention beats annotation for a failure that surfaces
years later in a fab house.

If the ledger is ever dropped, drop it as a separate decision with its own
argument — not as a side effect of adopting keys.

### `refdes id`

Survives, unchanged in interface. It still allocates display ids for items
that lack one, still writes them back, still burns numbers. What changes is
that running it late, or not at all, stops being risky: an item can live
keyed and unlabelled, be referenced durably, and receive its display id
whenever someone gets round to it. That is a genuine ergonomic improvement
that falls out for free.

### A bonus: imports

The README currently warns that **"IDs must be unique across every project
you import"**, and recommends adopting board-token prefixes early against
the day projects are split. Under keys, cross-project *links* are immune to
display-id collision — two projects can both have `REQ-001` and a link into
either resolves correctly. Display-id uniqueness still matters for prose
references and for human sanity, so the advice does not vanish, but it stops
being a correctness requirement and becomes a readability one. Worth
updating that passage at adoption time.

---

## 9. What I would prototype before committing

In rough order of how likely each is to change the design:

1. **Composite round-tripping through the real write-back path.** `refdes
   id`'s `insert_into_list` already handles flow-style entries (`- {text:
   ...}`) by injecting into the braces, and refused an unclosed flow mapping
   rather than corrupting it. Composite expansion has to survive the same
   shapes, plus `defaults:` blocks, plus block sequences, plus quoted
   scalars. This is where I would expect to find the sharp edges, and it is
   cheap to test exhaustively.

2. **The diff, on a real rename.** Take this repository, adopt keys on a
   branch, rename `BND-THM` → `THM`, and read the resulting diff as a
   reviewer. If it is not obviously *more* readable than today's, the
   composite shape is wrong and should be revisited before it is baked into
   every file.

3. **Adoption on a project with sealed log entries and stamped baselines.**
   §5(c)'s conditional carry-forward is the subtlest part of this design.
   Prototype it against a project where some items *have* changed since the
   baseline, and confirm the uncomparable entries are reported rather than
   quietly rebased.

4. **`--no-write` coverage.** Enumerate every write the tool performs during
   a load and confirm the flag suppresses all of them. This is the kind of
   flag that is 95% implemented and then dirties a CI tree via one forgotten
   path. **Status: partially done.** The flag exists and gates key minting
   (the write this document's first implementation slice added); it does not
   yet gate `.refdes/schema.json` regeneration, seals, the boards manifest, or
   the id ledger, all of which `_load()` still writes unconditionally today.
   This prototype item is therefore still open, narrowed to "everything
   except key minting."

5. ~~**Damm versus Luhn**, but only if the answer might be Damm — the window
   for changing the check algorithm closes the moment the first project
   adopts keys.~~ **Resolved: Damm.** Decided before any project adopted
   keys, so the window was still open. See §1's amended "check character"
   section for the reasoning and the measured numbers.

---

## 10. Where you might disagree

Flagged deliberately, with my reasoning, so these are decisions rather than
assumptions:

- **The type name stays in the content hash** (§5), so schema-vocabulary
  renames still churn hashes and still need `revise`'s carry-forward. You
  may have expected keys to eliminate that too. Eliminating it means giving
  schema entities keys as well, which is a strictly larger design.

- **`validate_prefixes` relaxes from error to warning** (§4, §8). If you
  regard a mismatched prefix as a smell worth blocking on regardless of
  whether it is load-bearing, keep it an error — nothing else in the design
  depends on the change.

- **The ledger survives** (§8). I have given the counter-argument its due;
  this is the closest call in the document and the one I would most expect
  you to overturn.

- **Adoption is opt-in** rather than automatic on upgrade (§7). Automatic
  adoption would guarantee every project gets the benefit, at the cost of
  rewriting every item file in someone's tree without them asking.

- ~~**Luhn mod 32 rather than Damm** (§1). Chosen for simplicity against a
  failure mode that barely occurs; the transposition gap is real and
  measured at 0.31%.~~ **Overturned.** This was the disagreement I most
  expected, and it landed the other way: Damm, not Luhn. See §1.

- **`key:` is hard-reserved, not overridable** (§3), unlike `prefix:` and
  `board:`. Identity should not be shadowable, but this is a genuine
  asymmetry with the existing reserved-key rules and it will surprise
  someone who knows those rules well.

- **Eleven characters.** Long enough to be safe, long enough to be noticed
  in every link line. If line noise turns out to dominate the reading
  experience in prototype (2), the honest response is to reconsider 8+1 with
  eyes open about §1's table, not to quietly hope.
