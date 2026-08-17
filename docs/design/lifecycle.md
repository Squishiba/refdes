# Project lifecycle: `revision` and `release` — design spec

## Decision (recap)

Three states, two commands, no flags on either command.

- **draft** — the state a project is in when nothing has been stamped. Not a
  command; nothing to run. `refdes check`/`refdes build` already behave
  permissively here, unchanged.
- **`refdes revision <name>`** — cuts an internal checkpoint. Stamps a
  baseline unconditionally (modulo the always-on error floor, §1). No
  readiness demanded.
- **`refdes release <name>`** — runs the full readiness gate and stamps only
  if it passes. On failure it writes nothing and prints exactly what
  blocked it. Running `release` when you're not ready *is* the check; there
  is no separate `--dry-run`.

Both take a name (`rev-b`, `rev-c`, `sent-to-fab-2026-08`), making
repeatability the point rather than an afterthought.

"draft" means the same thing at item level (`status: draft`) and project
level (nothing stamped, or a `release` that hasn't passed) on purpose: a
release cannot contain draft items *because* both meanings are "not yet
agreed." The build mode itself is never called "draft" anywhere in the
interface — only described that way in prose — to keep that word meaning one
thing.

Design only. Nothing in this document has been implemented.

---

## 1. The readiness gate

### The floor: build errors, always, non-configurable

Today, any `project.error(...)` already fails `check`/`build` (nonzero
exit). That floor is unconditional and stays out of the configurable gate
entirely — **both `revision` and `release` refuse to stamp anything while
`project.errors` is non-empty**, the same posture `check` already has.

This floor already covers two of the candidates in the brief without a new
config key:

- **Seal violations** — `seal.verify()` (`src/refdes/seal.py:87`) already
  calls `project.error(...)` for an edited sealed entry. Already blocks.
- **Vendored-copy hash mismatch** — `citations.verify()`
  (`src/refdes/citations.py:227-233`) already calls `project.error(...)`
  unconditionally for a tampered/corrupt cache. Already blocks. (This is
  distinct from a *missing* vendored copy — see below.)

Both are already non-negotiable today; a baseline stamped over either would
record a hash nobody should trust. No reason to make either configurable.

### The configurable layer

Everything below the floor is normally a warning or an info-level note that
`check`/`build` tolerate (a mid-project board legitimately has open
coverage). `release` needs to treat some of that as blocking; `revision`
usually shouldn't. Each rule below is a boolean pair, `release` /
`revision`, both independently configurable, because a rule useful for
gating a release is not automatically useful for gating a lightweight
checkpoint.

| Rule | Detects | Source | `release` default | `revision` default |
|---|---|---|---|---|
| `draft_items` | any local item whose configured status field currently reads its configured draft value | `item.fields.get(status_field)` | **true** | false |
| `unpinned_citations` | a `citations:` entry with no lockfile record (`state == "unpinned"`) | `citations.verify` / `item.citations` | **true** | false |
| `missing_vendored_copies` | `vendor: true` citation whose blob is absent (`state == "cache_missing"`) | `citations.verify` / `item.citations` | **true** | false |
| `uncovered_requirements` | a non-draft, non-retired coverable item at coverage stage `open` | `project.coverage` | **true** | false |
| `unverified_requirements` | a non-draft, non-retired coverable item at any stage below `verified` | `project.coverage` | false | false |
| `info_check_failures` | a failing `checks:` entry on a type whose `check_severity` is `info` (e.g. an `option` candidate) | `item.checks` | false | false |
| `unaccepted_board_moves` | an item whose resolved board differs from `.refdes/boards.yaml` | `project.board_moves` | **true** | false |

Reasoning for the defaults, briefly:

- **`draft_items` / `uncovered_requirements` / `unpinned_citations` /
  `missing_vendored_copies` / `unaccepted_board_moves` default on for
  `release`.** These are exactly the "did you actually finish" questions a
  release is supposed to force. A release with an unresolved board move or
  an unfetched datasheet citation is shipping an unresolved question, not a
  reference point.
- **`unverified_requirements` defaults off for `release`.** This is a
  hardware tool: boards frequently go to fab specifically so they *can* be
  tested. Requiring full verification before every release would make
  `release` unusable for the rev sent out for bring-up. A project nearing
  tape-out that wants a stricter bar turns this on — that's the "tightened
  over time" the brief asks for, not a fixed property of `release` itself.
- **`info_check_failures` defaults off everywhere.** A failing check on a
  `check_severity: info` type is working as designed — that's what makes a
  rejected `option` a rejected option, and it's valuable history (see
  `docs/design-log.md`'s argument for keeping dead ends visible). Nothing
  here is unambiguously "not ready."
- **Nothing defaults on for `revision`.** A revision is "here's where we
  were," not "here's where we should be." The only thing that ever blocks a
  revision is the floor above — a `revision` config override that flips one
  of these to `true` is legitimate (a team that wants even its checkpoints
  to carry no draft items can ask for that) but it isn't the shipped
  default.

I did not add a gate rule for **items deleted since the last baseline** —
see §6. Detecting a deletion is easy; distinguishing an intentional
retirement from an accidental one is not, and every other rule above has an
unambiguous, already-computed signal behind it. A gate rule with a high
false-positive rate is worse than no rule — it's the thing that gets a
release process disabled by tired engineers, the same failure mode
`docs/change-tracking.md` already warns about for suspect links ("people
stop reading the badges within a week").

### Config shape

Lives in the project-level config file introduced separately for calc
significant figures, item layout, and the `required_when` toggle (see
`docs/design/standard-library.md` §1, "The toggle") — not in `refdes.yaml`.
This document does not name that file; it only adds one top-level key to it,
`release_gate:`, structurally a sibling of whatever holds `sigfigs:` and
`items:`. **Do not put this in `refdes.yaml`** — `refdes.yaml` is schema
(types, links, boards); this is process policy, same category as the
`required_when` toggle it sits beside.

```yaml
release_gate:
  draft_items:              { release: true,  revision: false }
  unpinned_citations:       { release: true,  revision: false }
  missing_vendored_copies:  { release: true,  revision: false }
  uncovered_requirements:   { release: true,  revision: false }
  unverified_requirements:  { release: false, revision: false }
  info_check_failures:      { release: false, revision: false }
  unaccepted_board_moves:   { release: true,  revision: false }
```

A project only needs to write the keys it wants to change — this is an
overlay on the defaults table above, the same override idiom
`schema.py`/the standard-library design already use elsewhere (base +
project overlay), not a second merge convention.

**Load-time validation**, at the same point `required_when` is validated
(after base defaults and the project overlay are merged): an unknown key
under `release_gate:` is a `SchemaError`, difflib-suggested against the
seven known rule names — the same suggestion machinery
`docs/design/standard-library.md` §1 already specifies for
`required_when`. This is what makes "tightened over time" safe: a typo'd
rule name fails loudly at load time instead of silently never gating
anything.

`draft_items` additionally needs to know *which* field and value count as
"draft," since `status` choices vary by project (today's shipped
`refdes.yaml` uses `[draft, open, accepted, retired]`; the pending standard
proposes `[draft, active, retired]` — see
`docs/design/standard-library.md` line 720). Rather than hardcoding the
string `"draft"`, the rule reads whichever field a type marks as its status
field the same way `satisfying_statuses:` already requires a `status`
field to exist (`docs/coverage.md`, "Declaring `satisfying_statuses:`
requires the type to have a `status` field"); `draft_items` is checked only
against types that declare `required_when`-eligible enum fields whose
`choices:` include a value literally spelled `draft` — reusing the same
type constraint `required_when` already imposes (§1's condition fields must
be `type: enum`) rather than inventing a second convention for "what is a
status field."

### Where this runs in the pipeline

`revision` and `release` both call the existing `build.build()`
(`src/refdes/build.py:612`) in the same read-only mode `check` already uses:
`seal_write=False, reseal=False, accept_board_move=False`. Neither command
ever mutates `.refdes/log-seal.yaml`, `.refdes/boards.yaml`, or
`.refdes/citations.yaml` — those are `build`'s and `fetch`'s job. This
resolves the "no flags" tension cleanly: there is nowhere on `revision`/
`release` to pass `--accept-board-move` or `--reseal` because there's
nothing for them to do — if a project has real drift to reconcile, that
happens via an ordinary `refdes build --accept-board-move` first, and
`release` simply reads the resulting clean state afterward. `revision`/
`release` are consumers of state `build` and `fetch` already produce, never
producers of it (except the baseline file itself).

Sequence: run `build.build()` → if `project.errors`, report and stop (exit
1, nothing written) → evaluate the configured gate rules against
`project.coverage`, `project.board_moves`, `item.citations`, `item.checks`,
and item statuses → for `revision`, stamp unconditionally; for `release`,
stamp only if every rule configured `true` for `release` passed, otherwise
report and stop, nothing written.

---

## 2. The baseline artifact

### Location and format: `.refdes/baselines/<name>.yaml`

This is the brief's own suggestion and I don't think there's a better one.
It matches the two existing precedents exactly:

- `.refdes/log-seal.yaml` (`src/refdes/seal.py`) — one committed YAML file,
  `id -> hash`, header comment, `yaml.safe_dump(sort_keys=True)`.
- `.refdes/boards.yaml` (`src/refdes/boards.py`) — same shape, `id -> board`.

A baseline is one more manifest in the same family, except there are many
of them (one per name) rather than one growing file, so each gets its own
file under a `baselines/` subdirectory instead of a single file keyed by
name internally. That keeps `git diff` on any one release/revision scoped
to exactly that stamp, and keeps the "delete to undo" story in §6 a plain
`rm` instead of a hand-edit of a shared file.

**Committed, not gitignored** — same reasoning `.gitignore`'s existing
comment gives for `ids.yaml` and `citations.yaml`: these record which names
have been burned, and two branches stamping `rev-b` independently without
seeing each other's file is exactly the kind of silent collision that
comment already warns about. Only `.refdes/vendor/` (the actual copyrighted
bytes) is gitignored; every other `.refdes/*.yaml` manifest is committed.
`.refdes/baselines/` follows that rule.

### Shape

```yaml
# Refdes baseline. Written once by `refdes revision <name>` or
# `refdes release <name>` and never modified afterward — a second stamp of
# this name with different content is a build error (see docs/design/lifecycle.md).
kind: release                  # "revision" | "release"
name: rev-b
stamped_at: 2026-08-17T14:03:00Z
stamped_by: "J. Bin <jared.bin12@gmail.com>"   # best-effort, see below; omitted if unknown
refdes_version: "0.3.0"

# Present only for kind: release. Records which rules were active and
# passed, so re-reading an old release stays meaningful after the gate
# config itself is later tightened.
gate:
  draft_items: pass
  unpinned_citations: pass
  missing_vendored_copies: pass
  uncovered_requirements: pass
  unverified_requirements: skipped   # not enabled in release_gate: at the time
  info_check_failures: skipped
  unaccepted_board_moves: pass

items:
  CMP-PWR-001: { hash: 673e6ba11269f350, type: component, title: "Buck converter" }
  DEC-PWR-001: { hash: a1b2c3d4e5f60718, type: decision, title: "LDO vs. buck for 3V3 rail" }
  REQ-PWR-004: { hash: 9f8e7d6c5b4a3210, type: requirement, title: "3V3 regulation during input step" }
  # ... one entry per local item
```

**This is assembly, not new machinery.** Every value above already exists
by the time `build.build()` returns: `item.content_hash` is computed by
`compute_hashes()` (`src/refdes/build.py:322`, already run in the pipeline
above), `item.type` and `item.title` are existing `Item` fields
(`src/refdes/model.py:180,202`), and the gate results fall out of §1's
rules. Nothing here requires a new computation, only a new place to write
down results that already exist in memory at the end of a build.

**Scope: `project.local_items` only**, matching `seal.py`/`boards.py`/
coverage's existing convention of excluding imports ("Imported items are
excluded from your coverage and validation" — `README.md:299`). Extending
baselines to also record imported items' upstream hashes (enabling a
cross-project diff — "did the interface spec I import from actually
change") is a real future extension and is exactly the kind of thing
`docs/change-tracking.md` already gestures at ("Imported items already
carry their upstream hash, so cross-project suspect links drop in with
it" — README.md:331-332) — but it's genuinely new scope (which imported
project, at which pinned version, do you diff against?) rather than
assembly, so it's deliberately left out of v1.

**Why store `type` and `title`, not just `hash`, per item** — this is the
one deliberate departure from the terser `seal.yaml`/`boards.yaml`
precedent (bare `id: hash`/`id: board`). Those two manifests are always
compared against a *live* item that can still supply its own title if
something needs printing. A baseline's whole point (§6) is to remain
legible after the live item is gone — a diff reporting `REQ-OLD-002 removed`
with no other information is nearly useless six months later. `type` and
`title` cost nothing extra to capture (both are already-computed `Item`
properties) and turn a removed-item diff line into `REQ-OLD-002 (requirement)
"Legacy input protection" — removed`.

### `stamped_by`: two options

**Option A (recommended): best-effort from `git config user.name`/
`user.email`, subprocess, swallowed on any failure; falls back to
`getpass.getuser()`; omit the field entirely if both fail.** This is
identity metadata, not history reading — it does not open the `.git`
object database, walk commits, or do anything the "not the git layer" line
in §5 is protecting. It degrades to "field absent" on a machine with no git
installed or no identity configured (a bare CI runner), which the baseline
schema already treats as optional.

**Option B: OS username only** (`getpass.getuser()` / `%USERNAME%`), no
subprocess call to git at all. Simpler, zero dependency on git being
installed, but on most machines gives a login name (`jbin`) instead of the
name that actually appears on commits and in the design log elsewhere in
the project (`docs/design-log.md`'s example entries are attributed
`J. Bin`), which is a worse match for the rest of the tool's own
conventions.

I lean toward A but flag it explicitly in my reply — it's the more likely
of the two decisions in this document to be wrong, because "shell out to
`git config`" is a small crack in the "this deliberately doesn't read git"
boundary even though it only reads local config, not history.

### Name validation

A baseline name becomes a filename (`.refdes/baselines/<name>.yaml`).
Validate it the same way an item id or board name would be — safe
characters only (letters, digits, `-`, `_`, `.`), reject anything containing
a path separator or resolving outside `.refdes/baselines/`, `SchemaError`-
style message on rejection. This is ordinary input hygiene, not a new
concept; it doesn't need its own subsection of design debate.

---

## 3. The diff

Two independently useful questions, both answered by comparing the current
build's `item.content_hash` per local item against one stored baseline's
`items:` map:

- **Since last revision** — compared against the most recently *stamped*
  baseline of **either kind** (`revision` or `release`), whichever has the
  later `stamped_at`. A release is itself a perfectly good checkpoint; if
  the most recent stamp of any kind was a release, "since last revision"
  reaching further back to some older `revision`-kind file and ignoring the
  release in between would be a stranger answer, not a more correct one.
  This is the tight, noisy, day-to-day question: "what's moved since I last
  marked a spot at all."
- **Since last release** — compared against the most recent
  `kind: release` baseline specifically, skipping over any revisions
  stamped since. This is the wider question that actually matters for
  release notes or a diff against "what we sent to the fab last time."

Both scans are computed by listing `.refdes/baselines/*.yaml`, reading each
file's `kind` and `stamped_at`, and taking the max — **not** a separate
"latest" pointer file. This is a deliberate choice: with no pointer to
maintain, deleting a baseline (§6) self-heals automatically on the next
run, the next-most-recent file left on disk simply becomes "latest." A
pointer file would need its own consistency story (what happens when the
pointer names a file that was deleted?) for no benefit — there are at most
a handful of baseline files in a project's lifetime, a directory scan is
free.

### Output

Surfaced via **`refdes audit`** — not a new third command. `audit`'s
existing job is exactly this: "everything the build tracks but does not
fail on" (`src/refdes/cli.py:300-308`). A baseline diff is read-only,
never blocks a build, and is exactly the kind of tracked-but-not-gating
state `audit` already reports (resealed entries, board moves, suppressed
fields). Adding a fourth top-level command for this would duplicate
`audit`'s stated purpose rather than extend it, and keeps the "two
commands" constraint from the brief unambiguously about the *stamping*
commands only.

```
Since last revision (rev-c, 2026-08-10T09:12:00Z):
  changed   3   DEC-PWR-002, CMP-PWR-001, REQ-PWR-003
  added     1   TST-PWR-004
  removed   0
  (38 unchanged)

Since last release (rev-b, 2026-07-02T16:40:00Z):
  changed   9   CMP-PWR-001, DEC-PWR-001, DEC-PWR-002, REQ-PWR-002, REQ-PWR-003, ...
  added     4   TST-PWR-003, TST-PWR-004, DEC-PWR-003, CMP-PWR-005
  removed   1   REQ-OLD-002 (requirement) "Legacy input protection" — no longer in the project
  (31 unchanged)
```

No baselines of a given kind yet → that section prints `(no revision
stamped yet)` / `(no release stamped yet)` rather than erroring; `audit`
already runs with zero preconditions today and this shouldn't change that.

### Relationship to suspect links

`docs/change-tracking.md` describes suspect links as edge-scoped: "a link
records the hash of its target at review time, and a mismatch later means
the target moved and the link needs re-reviewing." That is genuinely
different granularity from what a baseline diff gives you. The baseline
diff is **item-scoped** — it tells you *which items* moved since a point in
time, project-wide, with no notion of who linked to them or when they last
looked. Suspect links (not yet implemented — see §5) would be **edge-
scoped** — for one specific link from one specific item, whether *that*
link's target has changed since *that* link was last reviewed.

They're complementary, and the baseline diff's `items:` map is exactly the
"target hash at a point in time" data a future suspect-link mechanism would
need on the target side — assembling this now doesn't build suspect links,
but it does mean suspect links, whenever built, have a ready-made source of
"hash at $baseline" to compare a link's recorded review-time hash against,
rather than needing to invent that storage too.

Until suspect links exist, the *changed* set in a baseline diff is the
closest thing available to "what's worth re-reviewing" — coarser (item, not
edge) but immediately usable: anything in the changed list is safe to treat
as "look at this again if you're relying on it," same spirit, project-wide
grain instead of per-link.

### Relationship to `git diff`

The baseline diff deliberately does not attempt to show *what* changed
within an item — only *that* it did. Field-level diffing would mean storing
old field values somewhere, which is new machinery this document
explicitly avoids (§5). But baseline files are ordinary committed YAML, so
the field-level answer is one `git diff` away *for free*, once you know
which two commits to diff — which is precisely what the baseline diff
supplies. In that sense this is a curated index into `git diff`, not a
competitor to it: `git diff <commit-at-old-baseline> <commit-at-new-
baseline> -- items/REQ-PWR-003.yaml` gives the exact field-level change,
scoped by a list refdes already computed instead of a human guessing which
of forty items are worth looking at. (Resolving "commit at old baseline"
itself — e.g. from the baseline file's own git blame — is squarely the
parked git-reader layer's job; see §5.)

---

## 4. The log entry

**Recommendation: document as convention, plus a printed reminder on
success. Do not auto-write a log item, and do not prompt.**

Why not auto-write:

- A `log` entry is user-authored prose with an id that has to go through
  the same allocator every other item does — a prefix, a board (per-project,
  scoped by folder or `board:` override), and content. `revision`/`release`
  would have to guess at least the prefix and board on the project's behalf,
  neither of which it reliably knows (the same uncertainty `stamped_by` in
  §2 already has to hedge with "best-effort").
- `docs/design-log.md` is explicit about what a log entry is *for*: "the
  reasoning... between a requirement being handed to you and a decision
  being made." A machine-generated "released rev C on 2026-08-17" entry
  with no rationale is exactly the low-value noise the `log`/`ignore`
  on_change split elsewhere in this design was built to keep out of the
  timeline ("Without it, suspect links are unusable... roughly half your
  fields should be `log`" — `docs/change-tracking.md:30-32`). An empty
  auto-entry is worse than no entry.
- It would also couple two very different kinds of writes into one command:
  the baseline manifest (`.refdes/baselines/<name>.yaml`, computed,
  machine-owned) and an `items/` source file (hand-authored, append-only,
  id-ledger-consuming). Keeping `release`/`revision` scoped to writing only
  the manifest keeps the blast radius of "what does this command touch"
  small and matches every other manifest-writer in the codebase (`seal.py`,
  `boards.py`, `citations.py`) — none of them write into `items/`.

Why not prompt: this is a CLI meant to run unattended in CI (`refdes check`
already documents that use — `docs/change-tracking.md:106`, `cli-
reference.md`), and the brief is explicit that `release`/`revision` take no
flags because "running it when you're not ready is the check." An
interactive prompt is the flag problem in a different costume — it still
means the command can't run unattended, just via stdin instead of argv.

**The convention, concretely**: on a successful `release` (and only
`release` — a `revision` is explicitly allowed to be a mid-thought
checkpoint, nothing to announce yet), print a one-line nudge to stdout:

```
release 'rev-b' stamped: 41 items, all gates passed.
  .refdes/baselines/rev-b.yaml

Consider recording this in the design log, e.g.:
  - id: LOG-A-0NN
    date: 2026-08-17
    summary: Released rev-b — sent to fab.
    records: [DEC-...]
```

This is documentation-as-UX, not a new mechanism: it's a print statement
after a successful stamp, no different in kind from `cmd_fetch`'s existing
per-url status lines. `docs/design-log.md` gets a short new section
("After a release") stating the convention in prose, the same way it
already documents the `amends:` convention for corrections.

---

## 5. Relationship to the parked git-history layer

Both `README.md` ("Not built yet... Git history layer — field-level diffs,
item timelines, suspect links, baselines") and `docs/change-tracking.md`
("What is not built yet... baselines, and change reports between two
baselines") currently file baselines under the git-reader layer. This
document's conclusion is narrower than that framing suggests: **baselines
and the two-question diff in §3 do not need a git reader at all.**

What this design **does** give you, with zero git object reads:

- A durable, named, content-addressed checkpoint (§2), workable in a repo
  using any VCS or none — it's a YAML file compared by hash, the same way
  `seal.py` and `boards.py` already work without touching `.git`.
- "Did this item's meaningful content change since $baseline" (§3), for
  every local item, in one pass, project-wide.
- The two independently useful comparison points the brief asks for
  (since-last-revision, since-last-release).
- A ready-made scope list to hand to `git diff` for the field-level answer,
  when git is available (§3).

What still needs the git reader, unchanged from today's framing:

- **Field-level diffs** — *what* changed within an item, not just that it
  did. The baseline stores a hash, not the old values; recovering the old
  values means reading git history (or, as above, borrowing `git diff`
  directly rather than reimplementing it).
- **Item timelines** — a continuous view across many small steps, not just
  two-point comparisons between named baselines.
- **True edge-scoped suspect links** (§3) — "this specific link, reviewed
  at this specific time, against this specific version of its target."
  Baselines give you the target-hash side of that for free (§3); the
  "recorded at review time" side, per link, is still unbuilt and doesn't
  obviously need git either, but it's out of scope here.
- **Authorship/blame of a change** — `stamped_by` (§2) says who stamped the
  *baseline*, not who changed any particular item since the last one.

Nothing in this design forecloses the git layer; if anything it gives that
future work a cheaper starting point — a `refdes.yaml`-independent, always-
available list of "which items actually moved between these two points,"
which is exactly the filter a git-backed timeline would want before walking
history for the items that matter. `README.md`'s and `change-tracking.md`'s
"not built yet" lists are worth updating to move "baselines" out of the
git-layer bucket once this ships — not done here, since the brief scopes
this document to `docs/design/lifecycle.md` only.

One explicit non-goal, stated for clarity: neither command checks git
working-tree cleanliness (no "refuses to stamp with uncommitted changes").
`.refdes/log-seal.yaml`, `.refdes/boards.yaml`, and `.refdes/citations.yaml`
are already "committed by convention, not enforced" — `.refdes/baselines/`
takes the same posture, consistent rather than inventing a stricter rule
for this one manifest.

---

## 6. Edge cases

### Re-running the same name

`.refdes/baselines/<name>.yaml` already exists.

- **New content is byte-identical** (same `items:` map) → no-op, exit 0,
  file untouched (not even `stamped_at` rewritten — rewriting a timestamp
  for no content change would make `git diff` show churn on every rerun,
  the opposite of what a byte-identical run should look like). Mirrors
  `refdes fetch` skipping an already-pinned, unchanged url.
- **New content differs** → error, nothing written. `rev-b` is meant to be
  a durable label — "the version sent to the fab" only works if `rev-b`
  keeps meaning the same thing later. This is the same append-only
  philosophy `seal.py` already applies to log entries, applied to baseline
  names instead of item ids.
- No `--reseal`-equivalent flag exists for this, on purpose (no flags at
  all on these commands). The sanctioned override is explicit deletion —
  next bullet.

### Releasing when a revision is newer

No special handling. `release` and `revision` are peers writing into the
same name/hash space, not a strict lineage where one must follow the
other — a release doesn't need to "catch up to" or "supersede" the most
recent revision. If a release happens to have identical content to the
latest revision, `refdes audit`'s "since last revision" section will simply
report zero changes, which is informative on its own; nothing needs to
gate on it.

### Deleting a baseline

No dedicated subcommand. `.refdes/baselines/<name>.yaml` is a plain
committed file — `rm`/`git rm` it like any other tracked file, no more a
candidate for its own CLI verb than removing a line from `citations.yaml`
is today. Because §3's "latest" lookup is a directory scan rather than a
maintained pointer (deliberately, see §3), deleting a baseline needs no
cleanup elsewhere: the next run of `refdes audit` simply finds a different
file as "latest," or reports "(no release stamped yet)" if none remain.

### An item that existed at baseline time and has since been deleted

Reported by the diff (§3) as `removed`, using the `type`/`title` captured
in the baseline (§2) since the live item can no longer supply them. **Not**
a gate condition by default (see §1's reasoning for leaving this out of
`release_gate:` entirely) — deletion is routinely intentional (retirement,
merge into another item, a superseded decision removed outright) and there
is no reliable machine signal to distinguish that from an accidental loss.
Making every deletion block a release would either get worked around
immediately or get the whole gate turned off — the exact failure mode
`docs/change-tracking.md` already warns about for over-eager suspect links.
Surfacing it prominently in the diff, with enough context (type, title) to
be actually legible, is the right amount of friction.

---

## CLI surface (recap)

Two new `argparse` subcommands in `src/refdes/cli.py`, alongside `build`/
`check`/`index`/`id`/`fetch`/`audit`. Each takes exactly one positional
argument, `name`, and nothing else — no flags, consistent with every
constraint above.

```
refdes revision <name>
refdes release <name>
```

Exit codes, matching the existing convention (`0` success, `1` diagnostic
failure, `2` `SchemaError` — `src/refdes/cli.py:311-316`):

- `0` — stamped (or a byte-identical no-op re-run).
- `1` — blocked: either the error floor (§1) or, for `release` only, a
  failed gate rule. Report format mirrors `_report()`'s existing style,
  then the gate table (pass/FAIL/skipped per rule) for `release`.
- `2` — `SchemaError`: bad `release_gate:` config, or an invalid name (§2).

---

## Summary of new/changed surface

| What | Where |
|---|---|
| `release_gate:` config block | the new project-level config file (not named here) |
| `.refdes/baselines/<name>.yaml` | new, one per stamp, committed |
| `refdes revision <name>` | new CLI subcommand |
| `refdes release <name>` | new CLI subcommand |
| Two new sections in `refdes audit` output | since-last-revision / since-last-release diff |
| "After a release" convention note | `docs/design-log.md` |
| Reclassify "baselines" out of the git-layer "not built yet" bucket | `README.md`, `docs/change-tracking.md` (not done in this change) |
