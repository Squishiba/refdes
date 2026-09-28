# User-simulation release gate — run 1 (first run ever)

Jared's instruction, recorded 2026-09-27: stand up a standing pre-release gate
that exercises refdes the way a real first-time author would, not the way its
own test suite does. This is the first run, so it went deliberately **broad**
rather than scoped to a delta. Future runs should be scoped against §1 (what
was covered) so they don't re-walk the same ground.

Everything below was produced by installing this checkout editable
(`pip install -e .` into a clean venv, dist version reported as `0.5.0`) and
then using only documented surfaces: the docs, `--help`, and real HTTP.

**Nothing in the repo was modified.** All authoring happened in
`.scratch/user-sim-run1/`, which is gitignored. No source file is touched by
this report.

---

## 0. Three things that look like actual bugs

Read these first. They are not taste complaints; two of them produce wrong
output through the tool's flagship interactive surface, and the third makes an
audit trail lie.

### BUG 1 — the browser editor's create path ignores the target file's `defaults.prefix` and mints ids from the wrong series

**Severity: high.** The browser editor is the surface a newcomer is steered
toward, and it produces a defect the CLI allocator does not.

Three-line deterministic repro:

```bash
refdes init && mkdir -p items
cat > items/reqs.yaml <<'EOF'
defaults:
  type: requirement
  prefix: REQ-SYS
  owner: J. Bin

items:
  - body: First system requirement.
  - body: Second system requirement.
EOF
refdes id          # -> REQ-SYS-001, REQ-SYS-002   (correct)
refdes serve       # then in the browser: New -> requirement, any title
```

`items/reqs.yaml` ends up holding three ids:

```
  - id: REQ-SYS-001
  - id: REQ-SYS-002
  - id: REQ-001        <-- appended by the editor, wrong series
```

Two code paths disagree. `refdes id` honours `defaults.prefix` from the
destination list file. The editor's `POST /api/items/create` does not — it
allocates from the bare type prefix (`REQ`). Observed in isolation at
`.scratch/user-sim-run1/repro3/`, and again by accident in the main project,
where the editor put `REQ-001` inside `items/environment/requirements.yaml`
whose `defaults.prefix` is `REQ-ENV`.

What makes this worse than a cosmetic slip:

- `refdes check` **does** notice — `WARNING ... id 'REQ-001' does not match
  this item's prefix 'REQ-ENV' (from defaults:)` — but it is a *warning*, so
  the build stays green and exits 0. The wrong id is committed to a green tree.
- The id is then **burned** in `.refdes/ids.yaml`. Repairing it means a
  hand-edit or a `revise` mapping; the burned entry does not go away.
- The editor also wrote `status: draft` explicitly onto the new item, fighting
  the file's `defaults.status: active`.

I did not fix anything. Flagging for a decision on where the prefix should come
from — the destination file's `defaults`, the request, or a `prefix` field the
create form can set.

### BUG 2 — a re-minted surrogate key silently orphans every composite link, and the resulting diagnostic names two causes that are both false

**Severity: high.** Surrogate keys are presented as durable identity. Nothing
prevents a key from being silently re-minted, and when that happens the tool
misdiagnoses it and offers no recovery.

Deterministic repro (`.scratch/user-sim-run1/repro1/`):

```bash
# grp.md gains a key on first load; c.yaml's link expands in place
part_of: [GRP-001@136h8w1aatd]

# author (or a formatter, or a bad merge, or hand-retyped front matter)
# rewrites grp.md and loses the `key:` line

$ refdes id
no items are missing an id
$ grep '^key:' items/grp.md
key: pvsvykwrynm        <-- brand new key, same item, same id, same project
$ grep part_of items/c.yaml
    part_of: [GRP-001@136h8w1aatd]   <-- still points at the old key

$ refdes check
ERROR items/c.yaml:6 [CMP-001] — part_of points at key '136h8w1aatd' (labelled
GRP-001), which no item declares. The label may be stale; the key is what
resolves. Either the target was deleted, or this reference predates it.
```

Three separate problems:

1. **The message is wrong about the cause.** `GRP-001` exists, right there,
   under exactly that id — the link text *names that id*. The two hypotheses
   offered ("the target was deleted" / "this reference predates it") are both
   false. The real and much more common cause is "the target's key was
   regenerated", and the tool has both halves in hand to say so.
2. **The documented remedy does not work.**
   `docs/troubleshooting.md:154` says: *"give it a `key:` line (run a writable
   command to mint missing keys) and check that the key matches."* There is no
   missing key. Running a writable command is the thing that *caused* the
   problem. Following the docs accomplishes nothing.
3. **`refdes keys adopt` refuses because of the very error it exists to fix:**

   ```
   $ refdes keys adopt
   refused:
     project has existing build errors -- fix those first
     ERROR items/c.yaml:6 [CMP-001] — part_of points at key '136h8w1aatd' ...
   ```

   The only recovery I found is hand-editing the link text to the item's
   current key. That works, and the label half then refreshes itself correctly
   on a later rename (verified — the rename-safe part of the design is sound).

For the record, the re-mint itself is *documented*: `docs/ids.md:146` says keys
are minted as a side effect of loading the project, every time. What's
undocumented is that a re-mint orphans inbound composite links, that the
diagnostic misattributes it, and that no command recovers it.

### BUG 3 — `--reseal` permanently rewrites append-only history and records nothing, while two places in the tool promise a record

**Severity: high.** This one is about the audit trail being trustworthy.

`refdes build --help` says `--reseal` is *"recorded in `audit`"*. The runtime
message says it too. Neither is true.

```
$ refdes build --reseal
WARNING items/log.yaml:3 [LOG-001] — resealed after an edit to a sealed entry
  (was 64fd9f67989d596d, now ac0e8e41bedd0e65). This is recorded in the audit
  output.

$ refdes audit | grep -A2 "Append-only entries edited"
Append-only entries edited after sealing:
  (none)

$ grep -rn 64fd9f67989d596d .        # the old hash, anywhere in the project
  (not found anywhere on disk)
```

The only record of the rewrite is a transient terminal warning — lost to a
scrolled buffer or a CI log. The seal file is overwritten with the new hash and
the old one is unrecoverable.

Reading the source, `seal.resealed_ids()` (`src/refdes/seal.py:430`) returns
entries whose current content **no longer matches** the seal — i.e. *outstanding*
drift. It is not a log of accepted reseals, so the audit section titled
"Append-only entries edited after sealing" cannot show one. The message at
`seal.py:323` and the flag help are describing a record that does not exist.

This matters because the append-only guarantee is the tool's answer to "is my
design history trustworthy?", and right now a deliberate rewrite is
indistinguishable from no rewrite at all once the terminal is gone.

---

## 1. What this run covered

So a future scoped-delta run knows what it doesn't need to redo.

**Docs read and followed:** `getting-started.md` end to end, plus
`checks.md`, `parts.md`, `multi-board.md`, `troubleshooting.md`,
`lifecycle.md`, `standard-library.md` excerpts, `cli-reference.md` excerpts,
`schema-reference.md` excerpts.

**Project lifecycle:** `init` → author → `id` → `check` → `build` → `serve` →
edit → rebuild → check again, across five "sessions", on a 19-item synthetic
project (`.scratch/user-sim-run1/my-board/`) covering all seven bundled
`hardware@3` types (`requirement`, `bound`, `decision`, `test`, `log`,
`component`, `group`), plus 5 isolated repro projects.

**Commands exercised:** `init`, `id`, `new` (single + `--list`), `schema`,
`check` (incl. `-v`, `--board`, `--dry-run`-adjacent), `build` (`--reseal`,
`--dry-run`), `ls` (`--type`/`--tag`/`--board`/`--file`/free text), `audit`,
`index` (+`--compact` not run), `revision`, `release --help`,
`former-ids propose`, `stub-tests --dry-run`, `calc-rewrite --help`,
`standard --help`, `keys adopt --dry-run`, `serve`.

**HTTP surface, driven with curl against a live `refdes serve`:** root launch
URL and token redirect, `/preview/`, `/edit/`, `/edit/static/*`, and the whole
API — `/api/revision`, `/api/items` (with `type`/`status`/`q`/`tag` filters and
a bogus param), `/api/item/<ref>`, `/api/item/<ref>/sources`,
`/api/item/<ref>/sources/entries`, `/api/create/schema`, `/api/images`,
`/api/assets` (POST), `/api/items/create` (POST), `/api/item/<ref>/edit`
(POST). Also the negative paths: missing token (403 on every surface), wrong
`Host`/`Origin` (403), wrong method (405), unknown path (404), bad filter
(400), unknown item (404).

**Authoring done through the real editor API:** create a requirement →
`set_body` → `add_link`; `set_field`; stale-revision conflict; upload a PNG
asset and reference it from a decision body.

**Negative tests run deliberately:** link to a nonexistent id; wrong link type
for the verb; misspelled field; duplicate id across two files; string where a
list belongs; value outside an enum; missing required field; malformed YAML
(bad indent); unparseable YAML (unclosed flow seq); non-id link target;
unparseable `limit`; editing a sealed log entry; calc parse error and its
cascade; dangling image reference.

**Deliberately NOT covered** (candidates for a later run): `workspaces:`
(it needs a correct shape — see §2 F8 — and I ran out of budget), multi-project
`imports:`, `refdes fetch` (network), `standard upgrade` / `add-preset` /
`remove-preset`, `refdes release` succeeding end to end (my project never got
a clean `release_gate` pass), `--no-write` systematically, `serve` under
`--no-write`, PDF source picks (`serve` "Slice P-C"), `history capture` /
`redact` / `migrate-seals`, the VS Code adapter, the doc-site build, and any
Windows-specific behaviour.

---

## 2. Friction, ranked by how much it would derail a real newcomer

### F1 — the browser editor's create form cannot set `body` or a single link field, on *any* of the seven types

This is the finding most likely to strand someone, because the flagship doc
teaches a shape the flagship UI cannot produce.

`docs/getting-started.md` §2 says to author a requirement like this:

```yaml
items:
  - body: The unit shall operate from an input supply of 9 V to 36 V.
    source: Customer spec rev D, §3.1
```

Do that, then reach for the browser editor to add a third requirement, and the
create form refuses:

```
$ curl -X POST .../api/items/create -d '{"type":"requirement","fields":{"body":"..."}}'
422 {"kind":"refused","message":"refused: requirement does not declare a field
     'body'; it declares last_reviewed, note, owner, rationale, source, status,
     tags, title"}
```

Measuring `/api/create/schema` against `refdes schema` for every bundled type:

| type | fields in form | fields in schema | missing from the form |
|---|---|---|---|
| bound | 9 | 14 | `body`, `derives_from`, `part_of`, `refines` |
| component | 12 | 19 | `alternate`, `body`, `constrained_by`, `drop_in`, `part_of`, `satisfies` |
| decision | 12 | 21 | `blocked_by`, `body`, `constrained_by`, `part_of`, `recorded_by`, `satisfies`, `selects`, `supersedes` |
| group | 6 | 8 | `body` |
| log | 6 | 11 | `addresses`, `amends`, `body`, `records` |
| requirement | 8 | 13 | `body`, `governed_by`, `part_of`, `refines` |
| test | 7 | 11 | `body`, `part_of`, `verifies` |

(`history` excluded above as a non-authoring field.)

`body` is missing from **all seven**. So is **every link verb**. The practical
consequence: the editor can create an item's scalar shell, and then you need a
second round trip for the body and a third for each link. Every decision, test
and component in the getting-started walkthrough has at least one link, so the
common case is three-plus round trips to author what the docs present as one
act.

The good news: the *edit* route handles both — `POST /api/item/<ref>/edit` with
`op: "set_body"` and `op: "add_link"` both work cleanly, and the
optimistic-concurrency guard returns the current revision on a stale write
(`kind: "conflict"`). So this is a gap in the create form specifically, not a
limitation of the editor. Widening the create form to accept `body` and links
would close it.

### F2 — a scalar where a list belongs is silently coerced, with no diagnostic and a green build

```yaml
- id: CMP-010
  title: Part with SCALAR tags
  tags: "power, analog"     # meant to be two tags
```

`refdes check` → `0 errors, 0 warnings`, exit 0. Nothing anywhere. The stored
value is the **single** tag `"power, analog"` — not split on the comma
(confirmed via `GET /api/item/CMP-010`, which returns `["power, analog"]`
whereas the list form returns `["power", "analog"]`).

Worse, this is invisible at the query you'd actually run, because
`refdes ls --tag` matches by substring:

```
$ refdes ls --tag analog     -> CMP-010, CMP-012      # both "found"
```

So the wrong value looks right everywhere a newcomer would look for it.

The tool is also *inconsistent with itself* here: the editor's create path
refuses the same field with a good message — *"field 'tags' is a list field:
collections are not created here -- create the item and edit the collection
after"*. The loader accepts it silently; the editor rejects it. One of those
two is wrong, and I'd argue it's the loader.

(`satisfies: REQ-001` as a bare scalar, by contrast, works correctly and the
link is created — that leniency looks intentional. It's specifically
list-valued *data* fields like `tags` where coercion loses information.)

### F3 — a misspelled field is only a warning, so the build goes green without the field

```yaml
- id: CMP-003
  title: A part
  partnum: TPS123          # meant part_number
```

```
WARNING items/bad3.yaml:3 [CMP-003] — unknown field 'partnum' on component.
        Did you mean 'part_number'?
3 items, 0 errors, 1 warnings      [exit=0]
```

The did-you-mean is genuinely excellent and should be kept. But it's a
*warning*: exit 0, site written, and for `part_number` specifically the part
silently drops off the parts index, which is precisely the report the field
exists to feed. An unknown field is a typo with no other interpretation — this
one reads like it should be an error.

### F4 — the getting-started narrative never reaches a green build, and the route to green isn't signposted

`getting-started.md` is a good story with a hole in the end. Steps 5–7: the
build fails on the thermal check, then you add a test and a log entry, and the
build *still* fails. A reader who works the whole page has a permanently red
build and no next step.

The deeper problem: **a decision whose check failed can never stop being a
build error.** I superseded `DEC-PWR-001` with a passing `DEC-PWR-002`
(`supersedes: [DEC-PWR-001]`, `status: superseded`) and the failing check kept
erroring. That may well be deliberate — it's history — but nothing in the
walkthrough says so, and the doc gives the reader no way forward.

The escape hatch exists, and it isn't mentioned anywhere in the path a
newcomer walks. `component` ships a status-mapped `check_severity`; `decision`
does not. To get green you have to hand-write an overlay:

```yaml
# refdes-schema.yaml
types:
  decision:
    check_severity:
      default: error
      superseded: info
      rejected: info
```

and the `default:` key is mandatory — omitting it gives:

```
configuration error: types.decision.check_severity does not cover status
'proposed'. Add it, or add default: <level>.
```

That error is good. The problem is that no document a newcomer reads on this
path mentions the overlay. Either the walkthrough should end green, or it
should say plainly that a failed decision stays red and point at the overlay.

### F5 — `refdes id` reports "nothing to do" while silently minting keys and rewriting your link targets

Right after the getting-started walkthrough, running `refdes id` again on a
project whose ids are all allocated:

```
$ refdes id
no items are missing an id
```

But in the same run it minted `key:` lines on two items and rewrote a link in
place, `part_of: [GRP-001]` → `part_of: [GRP-001@136h8w1aatd]`. Three lines of
the project changed and the tool said there was nothing to do.

Compounding it: **`getting-started.md` never mentions `key:` at all.** Its §2
says only "The IDs are now written into your file. They will never change."
So a newcomer's files acquire a second, undocumented identifier that the tool
will later hold against them — and the one doc that would explain it is
`docs/design/keys.md`, which is a design document, not onboarding.

### F6 — append-only protection only exists if you ran `build` at least once

`refdes check` verifies seals but never creates them (documented in
`check --help`; easy to miss). Verified:

```
edit a brand-new, never-built LOG-002  ->  refdes check: 0 errors, exit 0
refdes build                            ->  seal file gains LOG-002
edit it again                          ->  ERROR ... append-only ... exit 1
```

Correct as designed, but a `check`-first workflow gets **no immutability at
all** and no warning that it's in that state. A one-line note in the append-only
error, or in `check --help`'s summary line, would close it.

### F7 — the append-only error tells you to run a flag that the printing command doesn't have

`refdes check` prints:

> ... or run with `--reseal` if the edit is deliberate.

`--reseal` is a `refdes build` flag. Following the advice on the command that
printed it:

```
$ refdes check --reseal
usage: refdes [-h] [-c CONFIG] [--no-write] {serve,build,check,...}
refdes: error: unrecognized arguments: --reseal
[exit=2]
```

A full usage dump in place of the sentence the tool just wrote. The message
should read `refdes build --reseal`. (`refdes build --reseal` does work — see
BUG 3 for the more serious problem with it.)

### F8 — one bad key in `refdes-project.yaml` bricks every command, including read-only ones

I invented two config keys while setting up a two-board project. Both were
rejected accurately — the validator names the valid set every time:

```
configuration error: refdes-project.yaml: boards.main.root is not valid --
  a boards: entry takes conforms_to, includes, label, path, token
configuration error: refdes-project.yaml: workspaces.hw.members is not valid --
  a workspaces: entry takes label, path, shared
```

That's decent behaviour for a machine-checkable mistake. The friction is that
there is no way to inspect *anything* until it's fixed — `check`, `ls`, `build`
and `audit` all die identically, so you can't even list your items to work out
what you broke. The error also doesn't say what the keys *mean*, or point at
`docs/multi-board.md`, which does.

(I did not get `workspaces:` working — I ran out of budget before reading
`workspaces.md` for the real shape. Not a finding against the tool; a gap in my
coverage.)

### Lower severity, but each one costs a newcomer a beat

- **L1 — `refdes init`'s only pointer to the docs is dangling on first contact.**
  It prints `candidate parts live in items/<board>/candidates.yaml --
  docs/parts.md#candidate-parts-the-recommended-layout`. `init` creates no
  `docs/`. A wheel built from this checkout
  (`pip wheel --no-deps -w .scratch/wheelout .` → 98 entries) contains **zero**
  `.md` files and no `docs/` directory, so the docs aren't installed either.
  And there's no published docs URL anywhere in the repo — `README.md` points
  at `docs/index.md` as a repo-relative path. So the very first thing the tool
  says to a newcomer points at a file that does not exist for them, in a
  project they just created, via a package that doesn't carry it. The guidance
  itself is right; the reference is unresolvable.
- **L2 — no `--version`.** `refdes --version` errors with the top-level usage
  dump. The installed dist is `0.5.0` and the CLI cannot tell you. Given the
  docs' own advice that *"a later `refdes` may write a higher number here; that
  is expected"*, being able to ask the tool which version you have is more than
  a nicety.
- **L3 — a malformed sentence in the missing-image error.**
  `image src 'x.png' does not exist (searched no site.assets directories are
  declared to search)` — two clauses run together. With `site.assets` declared
  the same code path reads correctly: `(searched the site.assets directories:
  items/assets)`. The no-assets branch needs a comma or a full stop.
- **L4 — unknown query params on `/api/items` are silently ignored.**
  `?typey=decision` returns all 18 items, HTTP 200, with `"filters": {}` echoed
  back. The client already has a `Bad filter: ...` path for 400s, so unknown
  *keys* could plausibly warn too. Right now a mistyped deep link shows
  everything and says nothing.
- **L5 — `refdes ls <ID>` returns "no items match".** Free text matches title
  and tags only. It's in `--help` ("matched against title and tags"), but the
  natural query immediately after allocating or creating an id is the id.
- **L6 — Python `repr` leaks into user-facing prose**, in three shapes I hit:
  `status: 'picked' is not one of ['candidate', 'selected', 'rejected',
  'obsolete']`; `constrained_by may point at ['bound'], but ...`; and
  composite keys appearing mid-sentence (`... but REQ-001@3tfdhrfwxvz is a
  requirement`). The bracket-list form reads like a debug print. The composite
  key in particular is an implementation detail surfacing in the one message a
  newcomer most needs to read cleanly.
- **L7 — the install snippet is Windows-first.**
  `docs/getting-started.md` §Install gives `./.venv/Scripts/python.exe -m pip
  install -e .` in the code block, with the POSIX correction
  (`.venv/bin/python`) in the sentence *after* it — and the fallback line two
  sentences later also gives the Windows path. A macOS/Linux reader following
  the block literally gets "No such file or directory". Small, and it
  self-corrects immediately, but it's the first thing anyone runs.

---

## 3. What worked cleanly — worth recording as the baseline

This is a good tool with a small number of sharp edges, and the sharp edges are
concentrated in the browser editor and in surrogate-key recovery, not in the
core loop.

- **The getting-started walkthrough worked first try, verbatim.** I followed
  `docs/getting-started.md` as written, and its documented build output matched
  character for character — including the failing check's exact text
  (`P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15 W/in^2`),
  the `4 items, 1 errors, 1 warnings` tally, and the `--keep-going` hint. The
  generated `refdes-project.yaml` matched the documented file exactly. That is
  rare and worth protecting.
- **The headline promise holds.** Tightening the shared bound from
  `<= 0.15 W/in^2` to `<= 0.13 W/in^2` re-evaluated the downstream decision's
  arithmetic and failed it, showing both bounds:
  `worst case 0.1458 W/in² vs <= 0.13 W/in^2 (nominal 0.1129 W/in²)`. Nobody
  typed either number. This is the reason to use the tool and it works.
- **Fully idempotent.** Three consecutive `build`s, then `check`, `id`, `ls` and
  `audit`, left `items/` and `.refdes/` byte-identical (excluding
  `schema.json`). No key churn, no seal churn, no repeated warnings, no
  reformatting. For a tool that rewrites its own source files on nearly every
  command, this is the property I'd most expect to break, and it didn't.
- **The write path is safe.** `POST /api/item/<ref>/edit` enforces an
  optimistic-concurrency token and returns `kind: "conflict"` with the current
  revision on a stale write, rather than clobbering.
- **Destructive operations are transactional and dry-runnable.**
  `build --dry-run` writes real browsable HTML, watermarks it as a draft, and
  skips sealing. `keys adopt --dry-run` prints a full plan. `former-ids propose`
  never writes without `--confirm`.
- **Diagnostics are unusually good, with the exceptions noted above.**
  Duplicate id names *both* locations. The unparseable-`limit` error matches
  `docs/checks.md` exactly. YAML errors pass PyYAML's message through with
  `file:line` and point at the exact column. The calc cascade names the bad
  line, then each dependent, then the resulting `check refers to 'P_dens',
  which no calc block defines` — four errors that tell the whole story. Unknown
  fields get a did-you-mean. `supersedes` pointing at a non-superseded item
  says exactly what to do. A `selected` component with no `selects:` says
  exactly what to add and where.
- **Serve's security posture is right.** 403 on every surface without the
  token; the API takes `X-Refdes-Token` rather than the cookie; POST requires a
  matching `Origin` (so curl without one gets 403 — correct CSRF behaviour, and
  a browser never hits it). `serve` also loads side-effect-free: no keys
  minted, no links expanded, nothing sealed, and `_site/` untouched (the preview
  is built into a temp dir).
- **Image upload is the best-behaved write path in the tool.** It is idempotent
  on identical bytes ("nothing was written"), sniffs the type from the bytes
  rather than the extension or the `Content-Type`, refuses a `.txt` with a
  message explaining that PNG/JPEG/GIF/WebP are accepted, returns the correct
  400/415/422 for the three malformed cases, and the rendered asset gets a
  content-hashed name (`board-outline.c414cd0e204de974.png`).
- **The label half of composite links refreshes on rename**, as designed —
  renaming an id rewrote the composite's display half and kept resolving. (The
  *key* half is where BUG 2 lives; the rename path itself is sound.)
- **Boards work as advertised.** A main-board decision checked cleanly against
  a sensor-board's bound, board-scoped pages were generated
  (`coverage-main.html`, `summary-sensor.html`, `tree-main.html`, …), and
  `--board` filtered `check` and `ls` correctly.
- **`refdes audit` is a genuinely good newcomer summary** — schema-field policy
  by type, item-level overrides, orphaned ledger entries, baselines, what's
  changed since the last revision and release, blocked chains, older baseline
  keys. Every section says `(none)` rather than hiding itself when empty.
- **Two small touches that show care:** the warning when
  `.refdes/schema.json` is older than `refdes-schema.yaml` ("If your editor's
  completion looked stale, it should catch up now"), and the info-level
  citation diagnostics that hand you the exact `refdes fetch --path ...`
  command to run.

---

## 4. Suggested shape for a scoped-delta run 2

Pick up the **untouched** list in §1 first (workspaces, imports, fetch,
standard upgrade, a real `release` pass, `--no-write` systematically, history
commands, PDF source picks, the VS Code adapter), then diff-check only the
areas §2 flagged:

- the editor's create form (F1, BUG 1) — re-measure
  `/api/create/schema` against `refdes schema` and re-run the `defaults.prefix`
  repro
- surrogate-key recovery (BUG 2) — re-run the lost-`key:`-line repro and check
  whether `keys adopt` can now reach it
- `--reseal` auditability (BUG 3) — check whether an accepted reseal leaves a
  durable record and whether `refdes audit` shows it
- `getting-started.md` reaching a green build (F4)

Everything in §3 should be re-confirmed only as a smoke test; it is the
baseline, not the target.
