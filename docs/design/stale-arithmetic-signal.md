# Stale-arithmetic signal — design spec

**Implemented**, as of v0.5.0 (unreleased) — `lifecycle._stale_arithmetic` and
the `stale_arithmetic` field on `lifecycle.Baseline`/diff output. This header
is stale from an earlier draft; see `git log -- docs/design/stale-arithmetic-signal.md`
and `lifecycle.py` for the landed shape, which this document's prose still
describes accurately.

## The problem

A decision's verdict and its `calc` block are two independent pieces of
content that happen to sit in the same item. Someone edits `status:` (or
writes "we switched to the 2 A part" in prose) without touching the `calc`
block underneath. `refdes check`/`build` evaluate that block live, against
whatever it currently says, and report a pass — nothing is wrong by the
tool's own rules. The verdict now describes a different design than the
numbers do, and nothing surfaces that.

## Not a `check` warning

`check` warnings are permanent: they re-fire on every run for as long as
the condition holds. That shape is wrong here twice over. First, most
decisions legitimately never touch `calc` again after their verdict lands —
flagging "verdict newer than calc" as an ongoing check condition would fire
on the overwhelming majority of accepted decisions in a mature project,
forever, for no reason. Second, this project has already paid for that
mistake once: finding 8 (`3fee369`, `86e8087`) had to aggregate per-item
coverage warnings and add an `info` severity specifically because
individually-permanent, always-on warnings drowned the warnings that were
actually actionable on a given run. This signal is not "is the calc block
stale" as a standing property of an item — it's "did the calc block *fail
to follow* the verdict across one specific transition." That's a diff
question, not a check question.

## The condition

**Verdict-bearing** = the item's `status` field, and only that field. This
project already treats a field literally named `status` (of `type: enum`)
as a distinguished convention — `lifecycle._draft_field_name` reads it the
same way to find the draft state. Reusing that convention here means no new
"what counts as reaching a conclusion" vocabulary has to be invented, and it
deliberately excludes verdict-adjacent fields like `rationale` (explains the
verdict, doesn't carry it) or `options` (candidates, not the choice).

The signal fires for item `X`, comparing against baseline `B`, when all of:

1. `X`'s type declares a `status` field (`type: enum`).
2. `X`'s body contains at least one ` ```calc ` block
   (`calc.extract_blocks(item.body)` non-empty).
3. `X.fields["status"]` differs from what `B` recorded for `X`.
4. The normalized text of `X`'s calc block(s) hashes the same as what `B`
   recorded for `X`.

Any item failing (1) or (2) produces nothing — that's most items in a
typical project (most types have no `calc`, and untyped/non-enum status
fields don't exist). Any item failing (3) already shows up as an ordinary
`changed` entry with nothing extra to say. Item (4) is the actual finding:
the verdict moved, the arithmetic didn't.

This only checks that *this item's own* calc block text didn't change — not
that the values it references didn't change upstream. An upstream value
moving is a different, already-partially-covered problem (content-hash
propagation, suspect links); scoping this signal to the item's own source
text keeps it a precise, single-purpose check rather than a second
change-tracking mechanism.

## What this costs `lifecycle.py`

§3 of `docs/design/lifecycle.md` is explicit that the baseline diff is
"item-scoped... deliberately does not attempt to show *what* changed within
an item," specifically to avoid storing old field values as new machinery.
This signal needs two more per-item probes than that principle currently
allows, so it's worth being honest that this is a narrow, deliberate
exception rather than pretending it fits the existing shape for free:

- `verdict`: the raw `status` value, stored the same way `title` already is
  (plain, not hashed — `title` is precedent for storing one small piece of
  display-relevant plaintext on a baseline entry).
- `calc_hash`: a hash of the item's calc-block source text, normalized the
  same way the body hash already normalizes whitespace, joined
  deterministically if the item has more than one block.

Both are omitted from an entry entirely when they don't apply (no `status`
field, or no `calc` block) — same absent-means-not-applicable posture
`hash_format` already uses. Neither reconstructs old field values in
general; they're two purpose-built probes for this one signal, not a step
toward general field-level diffing. `lifecycle.py`'s own docstring claims
"assembly, not new machinery" for everything else in a baseline — `verdict`
is still assembly (`item.fields["status"]` already exists by the time
`build()` returns), but `calc_hash` genuinely is new: a second hash
definition alongside `content_hash`, computed over a subset of the same
body text. That's the one piece of this design that isn't free, and if that
tradeoff isn't worth it, the alternative is not attempting this signal
without new storage — there's no way to know a calc block used to say
something different without recording what it used to say.

No `hash_format`-style migration is needed for either field: unlike
`content_hash`, nothing else depends on `verdict`/`calc_hash` being
present. A baseline stamped before this feature (or any item that hasn't
been re-stamped since) simply lacks them, and the signal is silent for that
item on that diff — always a false negative, never a false positive. It
starts working for an item the first time it's stamped by a version of
refdes that records these fields.

## No baseline yet

A project with nothing stamped has no baseline to diff against at all —
`audit` already prints `(no revision stamped yet)` / `(no release stamped
yet)` and skips `diff_against` entirely in that case. This signal inherits
that silence for free, and it's the right answer on its own terms: "stale"
is a claim about a transition between two points in time, and a project
with no prior stamp has only one point. There's nothing to have drifted
from yet.

## Output

No new diagnostic class. `DiffResult` gets one more field,
`stale_arithmetic: list[str]`, computed inside `diff_against` alongside
`changed`/`added`/`removed` (it's a refinement of `changed`, not a new
scan — every id in it is already in `changed`). `_print_baseline_diff`
annotates those ids the same way the removed-items list already gets
per-item detail lines below the summary count:

```
Since last revision (rev-c, 2026-08-10T09:12:00Z):
  changed   3   DEC-PWR-002, CMP-PWR-001, REQ-PWR-003
    DEC-PWR-002 -- stale arithmetic: status changed, calc block did not
  added     1   TST-PWR-004
  removed   0
  (38 unchanged)
```

This is exactly the `-- stale: ...` inline-annotation shape the
blocked-chains section of `docs/design/standard-library.md` uses for the
same "flag it inline in the existing report" instinct -- that section has
since shipped (`blocked.py`), unlike this document at the time this was
written.

Firing "once" falls out of the existing mechanics for free, without any
extra bookkeeping: the signal only ever compares against the *latest*
baseline of the relevant kind, and stamping a new baseline refreshes
`verdict`/`calc_hash` to the item's current values. The next diff starts
from that new stamp, where the (now current) status and (still unchanged)
calc hash no longer differ from what's recorded — so there's nothing left
to flag until the next real transition. It reappears on every `audit` run
between the transition and the next successful stamp, same as any other
`changed` entry does; that's not repetition of a stale warning, it's the
same not-yet-recorded fact being reported until it's recorded.

A renamed item (tracked via `former_ids`) can't spuriously trigger this:
`diff_against` matches strictly by `item_id`, so a rename shows as
`removed` + `added`, never `changed` — this signal only ever looks at ids
already in `changed`, which by construction kept the same id in both the
baseline and now.

## Forward-compat with threads

`docs/design/` has no doc yet for collapsing `log` and `decision` into
append-only threads (issue #7 finding 17) — this section is scoped only to
not foreclosing on that, not to designing it.

The two probes this signal needs — "what's the current verdict, did it
change" and "what's the current calc content, did it change" — are kept
independent on purpose, each with its own stored value and its own
comparison, rather than collapsed into one "did the item's shape change"
bit. That's what should make the reframing small if threads land: today,
"current verdict" and "current calc content" both mean "the one value this
item has," because an item has exactly one `status` and one set of `calc`
blocks. Under a thread model, "current" instead means "the most recent
entry of that kind in the thread's append order" — the same fold
(`diff_against` already folds a project down to one hash per item; this
would fold a thread down to one verdict-probe and one calc-probe) attaches
to the thread instead of the item, and the condition becomes "the thread's
most recent verdict entry is newer than its most recent calc entry" instead
of "the item's status field differs from its calc block." The comparison
logic (§ above) doesn't change shape — only what "current" resolves to
does.
