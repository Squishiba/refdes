# Project lifecycle: revision and release

Three states, two commands, no flags on either.

- **draft** — the state a project is in when nothing has been stamped. Not a
  command; there's nothing to run to be in draft. `refdes check` and `refdes
  build` behave exactly as permissively as they always have.
- **`refdes revision <name>`** — cuts an internal checkpoint. Stamps a
  baseline unconditionally (past the always-on error floor). No readiness
  demanded — "here's where we were," not "here's where we should be."
- **`refdes release <name>`** — runs the full readiness gate and stamps only
  if it passes. On failure it writes nothing and prints exactly what
  blocked it. Running `release` when you're not ready *is* the check —
  there is no `--dry-run`.

Both take a name (`rev-b`, `rev-c`, `sent-to-fab-2026-08`), so repeating a
stamp under the same label is the point, not an afterthought.

## The readiness gate

Two layers.

**The floor, always on, not configurable.** Any build error (a seal
violation, a tampered vendored citation, a broken link, anything `refdes
check` already fails on) blocks both commands outright — nothing is
written. This is the same posture `check` already has; `revision`/`release`
add nothing new here.

**The configurable layer**, in `refdes-project.yaml`:

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

Only list the keys you want to change — this is an overlay on the defaults
above. An unknown key is a load-time `SchemaError`, difflib-suggested
against the seven names.

| Rule | Blocks a release when... |
|---|---|
| `draft_items` | any local item's own status field currently reads `draft` |
| `unpinned_citations` | a `citations:` entry has never been fetched |
| `missing_vendored_copies` | a `vendor: true` citation's local blob is missing |
| `uncovered_requirements` | a non-draft coverable item's coverage stage is `open` |
| `unverified_requirements` | a non-draft coverable item isn't yet `verified` |
| `info_check_failures` | a failing check on a `check_severity: info` type |
| `unaccepted_board_moves` | an item's board/workspace differs from `.refdes/boards.yaml` |

**Why `unverified_requirements` defaults off.** This is a hardware tool:
boards frequently go to fab specifically so they *can* be tested. Requiring
full verification before every release would make `release` unusable for
the revision sent out for bring-up. Turn it on for a project nearing
tape-out that wants a stricter bar — that's a project-level choice, not a
fixed property of `release`.

**Why nothing defaults on for `revision`.** A revision is a checkpoint, not
a readiness claim. The only thing that blocks one by default is the floor.

**Draft detection** reads whichever field a type calls `status`, the same
field-existence convention `satisfying_statuses:`/`coverable_statuses:`
already use — a type only participates if that field is `type: enum` and
`draft` is one of its declared `choices:`. A type with no such field never
trips `draft_items`.

Neither `uncovered_requirements` nor `unverified_requirements` count a draft
item's open coverage against it — a draft item isn't expected to be covered
yet; that's a different problem (`draft_items`), not the same one twice.

## Running it

```console
$ refdes release rev-b
2 items with no coverage — see coverage.html
41 items, 0 errors, 1 warnings

release 'rev-b' blocked -- not stamped:
  FAIL     draft_items            REQ-PWR-004, REQ-PWR-005
  FAIL     uncovered_requirements CON-THM-002
  pass     unpinned_citations
  pass     missing_vendored_copies
  skipped  unverified_requirements
  skipped  info_check_failures
  pass     unaccepted_board_moves
```

Fix what's listed and run it again — there's no flag to override or skip a
rule for one run; adjust `release_gate:` in `refdes-project.yaml` if a rule
genuinely shouldn't apply to this project.

```console
$ refdes release rev-b
41 items, 0 errors, 0 warnings

release 'rev-b' stamped: 41 items, all gates passed.
  .refdes/baselines/rev-b.yaml

Consider recording this in the design log, e.g.:
  - id: LOG-...
    date: 2026-08-17
    summary: Released rev-b — sent to fab.
    records: [DEC-...]
```

Nothing writes that log entry for you — see [After a
release](design-log.md#after-a-release) for why, and what to write instead.

`refdes revision <name>` is the same shape, minus the gate (by default) and
minus the log-entry nudge — a revision is explicitly allowed to be a
mid-thought checkpoint, nothing to announce yet.

## The baseline file

`.refdes/baselines/<name>.yaml` — one file per stamp, committed like
`.refdes/ids.yaml` and `.refdes/citations.yaml` (two branches stamping
`rev-b` independently without seeing each other's file is exactly the
silent-collision problem those files already guard against).

```yaml
kind: release                  # "revision" | "release"
name: rev-b
stamped_at: 2026-08-17T14:03:00Z
stamped_by: "jbin"              # OS username by default -- see below
refdes_version: "0.3.0"

# Present only for kind: release -- which rules were active and passed, so
# re-reading an old release stays meaningful after release_gate: is later
# tightened.
gate:
  draft_items: pass
  unpinned_citations: pass
  missing_vendored_copies: pass
  uncovered_requirements: pass
  unverified_requirements: skipped
  info_check_failures: skipped
  unaccepted_board_moves: pass

items:
  CMP-PWR-001: {hash: 673e6ba11269f350, type: component, title: "Buck converter"}
  DEC-PWR-001: {hash: a1b2c3d4e5f60718, type: decision, title: "LDO vs. buck for 3V3 rail"}
  # ... one entry per local item
```

This is assembly, not new machinery — every value already exists by the
time `build()` returns (`item.content_hash`, `item.type`, `item.title`,
the gate results). Scoped to local items only, matching every other
manifest in the project (imports are read-only, and not this project's
readiness question).

**`type`/`title` per item, not just a hash**, is the one departure from the
terser `id: hash` shape `.refdes/log-seal.yaml`/`.refdes/boards.yaml` use.
Those compare against a *live* item that can still supply its own title.
A baseline's whole point is to stay legible after the live item is gone —
`REQ-OLD-002 removed` means nothing six months later; `REQ-OLD-002
(requirement) "Legacy input protection" — removed` does.

### `stamped_by`

```yaml
# refdes-project.yaml
baseline_identity: os_user   # os_user | git_identity — default: os_user
```

- **`os_user`** (default) — the OS username (`getpass.getuser()`). No
  subprocess, no git state read at all.
- **`git_identity`** — `git config user.name`. Opt-in, for a name that
  matches what already appears on commits and in the design log. If it
  can't be resolved (git missing, not a repo, or `user.name` unset), the
  build **warns and falls back to `os_user`** — it never errors, since
  `stamped_by` is metadata no gate rule reads, and a missing name string
  should never be able to block a release.

With the shipped default, `revision`/`release` never invoke git in any
form — this is deliberately not the git-history layer (below).

## The diff: what changed, and since when

Two independently useful questions, both answered by comparing the current
build's item hashes against a stored baseline's — surfaced through **`refdes
audit`**, not a third command (that's already `audit`'s job: "everything the
build tracks but does not fail on").

- **Since last revision** — against the most recently stamped baseline of
  *either* kind. The tight, day-to-day question: what's moved since I last
  marked a spot at all.
- **Since last release** — against the most recent `kind: release`
  specifically, skipping any revisions since. The wider question that
  matters for release notes, or a diff against what was actually sent to
  the fab last time.

```console
$ refdes audit
...
Baselines:
  most recent stamp:   rev-c (revision, 2026-08-10T09:12:00Z)
  most recent release: rev-b (2026-07-02T16:40:00Z)

Since last revision (rev-c, 2026-08-10T09:12:00Z):
  changed   3   DEC-PWR-002, CMP-PWR-001, REQ-PWR-003
  added     1   TST-PWR-004
  removed   0
  (38 unchanged)

Since last release (rev-b, 2026-07-02T16:40:00Z):
  changed   9   CMP-PWR-001, DEC-PWR-001, DEC-PWR-002, REQ-PWR-002, ...
  added     4   TST-PWR-003, TST-PWR-004, DEC-PWR-003, CMP-PWR-005
  removed   1
    REQ-OLD-002 (requirement) "Legacy input protection" — no longer in the project
  (31 unchanged)
```

No baselines of a given kind yet → `(no revision stamped yet)` / `(no
release stamped yet)`, not an error — `audit` already runs with zero
preconditions and this doesn't change that. A project that has stamped
nothing at all is in **draft**; this "Baselines:" section is where that
state is actually visible, since `check`/`build` stay exactly as
permissive as they always were.

Item-scoped, not field-scoped: the diff tells you *which* items moved, not
*what* moved within them. Field-level detail is one `git diff` away once you
know which two commits to compare — which is exactly the scoped list this
diff supplies. See [suspect links](change-tracking.md) for the closest thing
to a "what's worth re-reviewing" answer that exists today; a baseline's
`items:` map is exactly the "hash at this point in time" data a future
edge-scoped suspect-link mechanism would need on the target side.

## Not the git-history layer

Baselines and this diff work with **zero git object reads**, in any repo
using any VCS or none — a YAML file compared by hash, the same way
`seal.py`/`boards.py` already work without touching `.git`. With the
shipped `baseline_identity: os_user` default, git is never invoked at all.

What still needs an actual git-backed layer, not built here: field-level
diffs (*what* changed within an item), continuous item timelines, true
edge-scoped suspect links, and authorship of a change (as opposed to who
stamped the baseline). Nothing here forecloses that work — the baseline
diff's item list is exactly the filter a future git-backed timeline would
want before walking history for the items that actually moved.

Neither command checks git working-tree cleanliness. `.refdes/baselines/`
is committed by convention, the same as every other `.refdes/*.yaml`
manifest, not enforced.

## Edge cases

**Re-running the same name.** `.refdes/baselines/<name>.yaml` already
exists:

- New content is byte-identical (same items, same kind) → no-op, exit 0,
  file untouched — not even `stamped_at` rewritten. Mirrors `refdes fetch`
  skipping an already-pinned url.
- New content differs → error, nothing written. `rev-b` is a durable
  label; it only means "the version sent to the fab" if it keeps meaning
  the same thing later.
- No override flag exists for this, on purpose (no flags at all). The
  sanctioned override is explicit deletion — next.

**Deleting a baseline.** No dedicated subcommand — `rm`/`git rm`
`.refdes/baselines/<name>.yaml` like any other tracked file. Because
"latest" (both questions above) is a directory scan, not a maintained
pointer, deleting a baseline needs no cleanup elsewhere: the next `refdes
audit` simply finds a different file as latest, or reports nothing stamped
if none remain.

**Releasing when a revision is newer.** No special handling. `release` and
`revision` are peers writing into the same name/hash space, not a strict
lineage — a release never needs to "catch up to" the latest revision. If a
release happens to be identical to the latest revision, the diff simply
reports zero changes.

**An item deleted since a baseline was stamped.** Reported by the diff as
`removed`, using the `type`/`title` captured at stamp time. Not a gate
condition — deletion is routinely intentional (retirement, a merge, a
superseded decision removed outright) and there's no reliable machine
signal to tell that apart from an accident. A gate rule with a high
false-positive rate is worse than no rule at all.
