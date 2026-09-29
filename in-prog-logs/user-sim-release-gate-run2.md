# User-simulation release gate — run 2 (the scoped delta run 1 asked for)

Run 2 of the standing gate. Run 1 went broad; this run went only where run 1's
§1 said it had not gone: **workspaces, imports, `fetch`, `standard upgrade`, a
real `release` pass, `--no-write` systematically, the `history` commands, PDF
source picks over HTTP, and the VS Code adapter.** Run 1's §3 baseline was
touched only as a smoke test, and nothing in it has regressed.

Same method as run 1: install this checkout editable, then use only documented
surfaces — `docs/`, `--help`, real CLI invocations, real HTTP. Reported version
is `refdes 0.5.0`.

**Nothing in the repo was modified.** All authoring happened under
`.scratch/user-sim-run2/` (gitignored). This report adds one file and touches no
other.

One environment note that is itself a data point about first runs: the `refdes`
on `PATH` was a stale editable install pointing at a deleted worktree
(`/tmp/w-pr59-merge/src`), so `refdes --version` died with
`ModuleNotFoundError: No module named 'refdes'`. Re-running `pip install -e .`
fixed it. That is a local-machine artefact, not a product defect, but it is
exactly the failure a newcomer hits first and the error message gives no hint
that the fix is a reinstall rather than a broken checkout.

---

## 0. Three things that look like actual bugs

### BUG 1 — `refdes check` rewrites your item files while its own `--help` says nothing of the project's own is written

**Severity: high.** This is run 1's F5 (keys minted silently during a load)
still live, but the headline has moved: F5 was filed against `refdes id`, and
the fix landed as a *notice*, wired into exactly two of the twenty subcommands
that load a project. `check` — the command the docs explicitly recommend for CI
and pre-commit — is not one of them, and its help text actively denies the
behaviour.

The promise, at `src/refdes/cli.py:1538-1542`:

> Exits non-zero on any error. **Nothing of the project's own is written** -- no
> site, no seal, no board or citation manifest, no baseline. **The one exception
> is `'.refdes/schema.json'`**, the gitignored editor-completion schema every
> project-loading command refreshes.

The reality, on a project whose items carry `id:` but no `key:` yet — which is
every project written by hand, and every project written before keys existed:

```bash
# fresh git repo, clean tree
refdes -c refdes-project.yaml check
# -> 2 items, 0 errors, 0 warnings      exit 0, no mention of writing anything

git status --porcelain
# M items/decisions/dec.md
# M items/requirements/power.yaml
```

The diff is not metadata. It rewrites authored source:

```diff
 --- a/items/decisions/dec.md
 +++ b/items/decisions/dec.md
 @@ -1,2 +1,3 @@
  ---
 +key: r72txq43zam
  id: DEC-PWR-001
 @@ -5,3 +6,3 @@
  status: accepted
 -satisfies: [REQ-PWR-001]
 +satisfies: [REQ-PWR-001@j6qk1w3ad3b]
```

```diff
 --- a/items/requirements/power.yaml
 +++ b/items/requirements/power.yaml
 -  - id: REQ-PWR-001
 +  - key: j6qk1w3ad3b
 +    id: REQ-PWR-001
```

Verified identical for `check`, `ls`, `index`, `audit`, `build` and
`former-ids propose`. Only `id` and `stub-tests` say anything, via
`_load_write_notice()` (`src/refdes/cli.py:95`), which is called from exactly
two places — `cmd_id` (`cli.py:492`) and `cmd_stub_tests` (`cli.py:1193`):

```
(minted 4 key(s) and rewrote 1 reference(s) while loading)
```

This is not undocumented behaviour being missed. `docs/cli-reference.md:60-67`
states the truth plainly — and, in the same paragraph, recommends exactly the
workflow this breaks:

> Loading the project can still write back surrogate `key:` fields and expand
> resolvable link and `check` targets to composite form … Run
> `refdes --no-write check` for a run that writes none of those either.

So the docs and the `--help` contradict each other, and the `--help` is the one
that is wrong. `docs/ids.md:146` agrees with the docs, not with the help text.

Why it matters more than a stale sentence:

- **CI dirties itself.** The docs call `check` "the right command for CI and
  pre-commit hooks". A pipeline that runs it and then `git diff --exit-code` (the
  standard "is the tree clean?" step) now fails on a green build, with a diff
  nobody asked for. Worse, a pipeline that
  auto-commits formatting changes will commit surrogate keys into authored
  history from a machine with no author intent behind them.
- **The writes are cross-project.** With `imports:` configured, a bare link to
  an imported item expands to `IFC-CAN-001@5efq7knmrg8` — an upstream key — in
  the *downstream* author's file, during a command described as read-only. If
  upstream later regenerates that key, the downstream tree is left holding a
  composite that resolves to nothing (see §2, F4, for the diagnostic).
- **The fix already exists and is one line per command.** `_load_write_notice()`
  is right there; it just isn't called.

Minimum fix: correct the `check` description (and any sibling that repeats the
"one exception" claim), and call `_load_write_notice()` from every command that
loads with `write=True` and does not otherwise announce writes. Better fix:
make the default for the *reporting* commands (`check`, `ls`, `index`, `audit`)
`write=False`, and require an explicit command to mint keys — `keys adopt`
already exists for exactly that job.

### BUG 2 — on a read-only checkout, `refdes check` dies with an unhandled `PermissionError` traceback

**Severity: medium.** Read-only working trees are normal: CI with a frozen
checkout, a container with a read-only bind mount, an artifact directory, a
`git worktree` on a mounted volume. `refdes check` is the command you would
reach for there.

Whole tree read-only (`chmod -R a-w`):

```
$ refdes -c refdes-project.yaml check
Traceback (most recent call last):
  ...
  File ".../src/refdes/loader.py", line 92, in load_project
    schema_was_stale = schema_json_mod.write_schema(project, write=write)
  File ".../src/refdes/schema_json.py", line 350, in write_schema
    os.makedirs(os.path.dirname(path), exist_ok=True)
PermissionError: [Errno 13] Permission denied: '/…/.refdes'
```

Only `items/` read-only, project root writable — a different crash, same class:

```
$ refdes -c refdes-project.yaml check
Traceback (most recent call last):
  ...
  File ".../src/refdes/revise.py", line 640, in write_rewrites
    textio.write_text(rewrite.path, rewrite.after)
  File ".../src/refdes/textio.py", line 273, in write_text
    with open(path, "w", encoding="utf-8", newline="") as fh:
PermissionError: [Errno 13] Permission denied: '/…/items/decisions/dec.md'
```

Both exit `1`, which is the "errors found in the project" code — so a CI gate
reads "your project has errors" when the truth is "your filesystem is
read-only". No diagnostic, no suggestion, a raw traceback. `refdes --no-write
check`, `--no-write ls` and `index --compact` all survive the same read-only
tree cleanly and exit 0, which confirms the crash is purely a consequence of
the BUG 1 writes.

Fix: catch `OSError` around both write sites and emit
`WARNING <project> — could not write … (read-only tree?); run with --no-write
to silence`, then continue. The information being written is a cache and an
idempotent normalisation; neither is load-bearing for a `check`.

### BUG 3 — `refdes init` writes a machine-specific absolute path into a committed `.vscode/settings.json`, and the docs show a different file

**Severity: medium.** `docs/standard-library.md:312-315`:

```json
// .vscode/settings.json -- refdes init writes this for you
{
  "yaml.schemas": { "./.refdes/schema.json": ["items/**/*.yaml"] }
}
```

What `refdes init` actually writes, on my machine:

```json
{
  "yaml.schemas": {
    "/home/jorb/.paseo/worktrees/…/initvs/.refdes/schema.json": [
      "items/**/*.yaml"
    ]
  }
}
```

The absolute path is deliberate — `src/refdes/scaffold.py:23-37` explains that
`redhat.vscode-yaml` does not scope relative schema paths reliably across
multi-root workspaces ("finding 9"), and `tests/test_scaffold.py` asserts it.
Fine. But the consequence was not thought through:

- `refdes init` writes no `.gitignore`, and `.vscode/` is not ignored
  (`git check-ignore .vscode/settings.json` → exit 1). So the file is meant to
  be committed, and committing it puts **one developer's home directory into
  the repo**. Every other clone of that project gets schema completion pointing
  at a path that does not exist, silently, with no error anywhere in VS Code or
  refdes.
- The documented form and the emitted form differ, so a reader who copies the
  docs snippet gets behaviour the tool considers broken, and a reader who trusts
  "refdes init writes this for you" gets a machine-specific file.

Related, same function: when `.vscode/settings.json` already exists, `init`
skips it **silently** (`scaffold.py:117-120`). No message, no merge, no
"existing settings left alone, wire up `yaml.schemas` yourself if you want it".
A newcomer with an existing workspace settings file — extremely common — gets
schema completion that does not work and no clue why, while `init` exits 0 and
prints three cheerful lines.

Fix: either emit the relative form and accept the multi-root caveat (documented
in one place), or keep the absolute path and have `init` write
`.vscode/settings.json` into `.gitignore` alongside it — plus a one-line
`note:` when an existing file is skipped, and ideally a merge that adds the
`yaml.schemas` key rather than abandoning the file.

---

## 1. What this run covered

Covered, with real projects under `.scratch/user-sim-run2/`:

- **Workspaces** (`ws/`): `item_layout: workspace`, three workspaces with one
  `shared: true`, ID allocation into `items/<workspace>/<board>/`, cross-workspace
  link warnings, `check --workspace` / `--board` filtering, workspace-move drift
  detection and `--accept-board-move`, board/workspace namespace collision at
  load, `ls` behaviour, orphaned items in an unregistered folder.
- **Imports** (`up/`, `down/`): a real two-project artifact import, links and
  `checks:` against imported bounds, upstream limit tightening propagating to a
  downstream failure, version-pin mismatch refusal, missing-artifact error,
  cross-project composite link expansion into downstream source.
- **`fetch`** (`fetcht*/`): local-file citation pinning by sha256, drift
  detection naming every citer, `--update`, `--path`, `--item`, `keep_copy:` on a
  local path (refused), `..` and absolute path escapes (refused), the
  `unpinned_citations` gate transition from FAIL to pass, `--no-write fetch`
  refusal, `check --refresh` writing nothing.
- **`standard upgrade`** (`std_upgrade*.py`): v1→v2→v3 chaining in one jump, the
  `constraint`→`bound` type rename with `CON-`→`BND-` id rewrite, and the
  composed `title:`→`text:`→`body:` and `equivalent:`→`drop_in:` field
  migrations, key minting during migration,
  content-hash carry-forward across baselines, mid-chain rollback on an
  ill-formed migration, `--to` below the floor, `--to` past the ceiling,
  `--no-write` refusal.
- **`standard add-preset` / `remove-preset`**: the one shipped preset
  (`design-debate`), an unknown preset name, removal.
- **A real `release` pass** (`rel/`, `gate/`): gate failure on an uncovered
  bound, the coverage fix, stamping, baseline file contents, re-stamp-unchanged,
  re-stamp-changed refusal, `release_gate:` overrides, unknown rule names, empty
  gate, `--no-write release`, the follow-the-release log-entry hint.
- **`--no-write` systematically** (`nw_sweep*.py`): every command in the CLI run
  twice against a pristine project with a content hash taken before and after,
  plus the read-only-tree variants.
- **`history`** (`nw-src/`): `capture` (fresh, repeat, unknown id),
  `migrate-seals`, `redact` without and with `--confirm`, the redaction event
  file it leaves, re-capture after redaction, all three under `--no-write`.
- **PDF source picks** (`pdf_pick*.py`): the four `serve` source-picker routes
  over real HTTP — `/api/item/<ref>/sources`, `/sources/entries`, `/sources/page`,
  `/sources/propose` — including the token header and the ephemeral port.
- **VS Code adapter**: static only. `package.json`, `extension.js`,
  `serveClient.js`, the problem-matcher regex against real diagnostic lines, and
  the `refdes index --compact` / `/api/revision` / `/api/item/<ref>` shapes the
  adapter consumes. See §2, F7 for why it could not be run.
- **Smoke test of run 1 §3**: idempotency, `serve` side-effect freedom (re-verified
  this run: `serve` rewrote nothing), diagnostic quality, the tightening-a-bound
  headline promise (re-verified through imports rather than boards this time).

Not covered, and why:

- **Running the VS Code extension.** No `code` CLI, no VS Code runtime, no
  display, and `node` is outside this sandbox's shell whitelist. Static reading
  and contract-checking only.
- **`fetch` against a real remote URL.** No network egress from the sandbox.
  All citation work used local files, which exercises the pinning, drift,
  `keep_copy` and gate paths but not HTTP status handling, redirects, or
  `rev:`-from-`Last-Modified`.
- **A real PDF.** The source-picker routes were exercised with a synthetic
  source; actual PDF text-layer extraction, page-number resolution and the
  `pypdf`-missing fallback were not.
- **`keys adopt` / `revise` / `calc-rewrite` recovery paths** beyond what the
  `--no-write` sweep and the standard migration happened to touch. Run 1's BUG 2
  (lost `key:` line) was not re-run.
- **Windows and macOS paths**, line endings, and case-insensitive filesystems.

---

## 2. Friction, ranked by how much it would derail a real newcomer

### F1 — `refdes ls` has no `--workspace`, in a release where workspaces are a headline feature

`check` has `--workspace` and `--board`. `ls` has `--type`, `--board`, `--file`,
`--tag` — and no `--workspace`. In a three-workspace project the obvious first
question ("what's in product-a?") has no answer through the listing command;
you have to know that `check --workspace product-a` exists, or fall back to
`--file items/product-a/…`, which requires knowing the folder layout you were
trying to discover. `index --compact` does emit a `workspaces` key and a
`workspace` field per item, so the data is right there.

### F2 — the citation severity table says `--require-citations` applies to `check`; it is a `build`-only flag

`docs/markdown.md:435` introduces the severity table with "**Verification**,
checked at every `build` and `check`, offline", and four of its six rows end
with "(error with `--require-citations`)". The flag exists only on `build`.
Verified on one drifted local citation:

```
$ refdes check                                    -> exit 0
  WARNING <project> — local citation 'docs/spec.txt' has changed since it was pinned …
$ refdes build --dry-run                          -> exit 0
  WARNING <project> — local citation 'docs/spec.txt' has changed since it was pinned …
$ refdes build --dry-run --require-citations      -> exit 1
  ERROR   <project> — local citation 'docs/spec.txt' has changed since it was pinned …
$ refdes check --require-citations
  refdes: error: unrecognized arguments: --require-citations
```

So the documented way to make citation drift fail a build does not exist on the
command the docs recommend for CI and pre-commit. A newcomer tightening citation
policy will try the fast command first, get a usage error, and conclude either
that the policy is unenforceable or that `build` is the CI command (which it
isn't — it renders a site). Either add the flag to `check`, or scope the table's
rows to say "build only".

### F3 — `refdes release --help` never names the gate rules it runs

The eight rule names are documented properly in `docs/lifecycle.md:47-57` and
shown in the sample gate report in `docs/cli-reference.md:165-173`, and a typo
is caught with the full list:

```
configuration error: refdes-project.yaml: release_gate.nosuch_rule is not a
known rule (one of draft_items, unpinned_citations, …).
```

But `refdes release --help` mentions `release_gate:` in passing and names none
of the rules, so the help for the release command cannot answer "what is it
going to check?" — you have to know to open `lifecycle.md`. Low severity because
the documentation is good once found; it is the help text that is thin.

### F4 — an upstream key change turns a *downstream* file, rewritten by a read-only-feeling command, into a build error whose message describes causes that didn't happen

The composite `IFC-CAN-001@5efq7knmrg8` that `refdes check` writes into a
downstream author's file (§0, BUG 1) is a permanent commitment to an upstream
key. When upstream loses and regenerates that key — a hand-edit, a bad merge, a
formatter — downstream fails with:

```
ERROR   items/decisions/pins.md:2 [DEC-A-001] — constrained_by points at key
'5efq7knmrg8' (labelled IFC-CAN-001), which no item declares. A live item
labelled IFC-CAN-001 declares key '96ej5t8stwz'. Its key may have been lost and
regenerated, or the label may now name a different item. The label is not used
as a fallback. Check git history to confirm identity. If it is the same item,
restore its original key upstream.
```

The message is well-written and, in the single-project case run 1 examined,
right. In the import case it sends the downstream author upstream to fix
something they cannot see, and never mentions the far likelier local cause: the
composite in *their* file was written by a tool run, not by them, and it is
three commits deep in a file they last edited to change a title. Worth a
"this composite was written by refdes during a load, not by hand — see
`docs/multi-board.md`" clause, and worth the BUG 1 fix.

### F5 — `standard upgrade --help` says "rolling back cleanly" about an operation that is only per-step atomic

`--to 9` from v1 applies v1→v2, then v2→v3, then fails looking for a v3→v4
migration, exits 1, and leaves `standard.version: 3` with the item files already
rewritten to v3 shape. That is correct behaviour and `docs/cli-reference.md:660-667`
documents it precisely — "Stops at the first version step that fails, leaving
the project fully valid at whatever version it reached", and explicitly "a
`--to` past the newest bundled version … is also an exit 1 with the config left
at the version it had". The docs are better than the help:

> Refuses (**rolling back cleanly**) rather than guessing at an ambiguous or
> ill-formed step.

Read as the only description of the command, that says the invocation is
all-or-nothing. It isn't — earlier steps in the chain stay applied. Anyone
choosing between "just run `--to 9` and see" and "carefully step one version at
a time" will choose wrong from the help text alone. Reword to "refuses the
failing step, rolling it back cleanly; earlier steps in the chain stay applied".

### F6 — inconsistent exit codes for "no such thing"

`fetch --item NOPE-1` → exit **1**. `history capture NOPE-001` → exit **2**.
Both are "the id you gave me does not exist", both are user input errors, and
`docs/cli-reference.md:13` reserves `2` for configuration errors. A script that
distinguishes "the project is broken" from "I typo'd" gets the wrong answer half
the time depending on which command it called.

### F7 — the VS Code adapter cannot be exercised without a VS Code, and nothing in the repo says so

`editors/vscode/README.md` describes activation, completion, diagnostics and the
serve panel as though they were the feature. There is no headless harness, no
`.vscode-test` setup, and no note that verifying this surface requires a real
VS Code. Static reading found no defects — the problem-matcher regex
`^(ERROR|WARNING)\s+(\S+?):(\d+)(?:\s+\[[^\]]+\])?\s+—\s+(.*)$` matches every
item-scoped diagnostic the CLI emits, and correctly does *not* match `<project>`
or line-less `refdes-project.yaml` diagnostics, which the extension publishes
through its own path instead — and `refdes index --compact` supplies every field
the README claims. But "no defects found by reading" is a much weaker statement
than it would be with a test harness, and the gate has no way to say more than
that today.

### F8 — `serve` for scripted use needs two undocumented-by-default facts

Both are discoverable, neither is obvious: `serve` binds an **ephemeral port**
(no `--port` flag), and every `/api/` route needs the **`X-Refdes-Token`**
header rather than the session cookie. Anyone automating the source-picker
routes scrapes the launch URL from stdout; the token is urlsafe base64 and so
contains `_`, which a `[0-9a-zA-Z-]+` regex silently truncates — giving a 403
that looks like an auth bug rather than a scraping bug. A `--port` flag and a
`--token-file` would remove both traps.

### Lower severity, but each one costs a newcomer a beat

- `refdes init` prints `wrote refdes-project.yaml` and nothing about the
  `.vscode/settings.json` it also wrote, so the second file is invisible unless
  you list the directory.
- `refdes init` with an existing `.vscode/settings.json` skips it silently — see
  §0, BUG 3.
- A workspace name that collides with a board name fails at load with an
  excellent message ("boards and workspaces share one namespace for generated
  report names … rename one of them"), but only *after* you have written both.
  Nothing in `docs/workspaces.md` warns about the shared namespace up front.
- `release` ends with a suggested log entry using a literal `LOG-...` id and
  today's date; copying it verbatim produces an invalid id. The hint is lovely,
  the placeholder is a trap for copy-paste.
- `refdes audit` reports a hash-only citation as `unpinned  hash-only  cited by
  DEC-PWR-001` — two words that read as a contradiction until you learn that
  "hash-only" means pinned-by-hash-without-a-rev. The vocabulary is consistent
  internally and opaque on first contact.

---

## 3. What worked cleanly

- **`--no-write` is honest, and it is honest everywhere.** Every command in the
  CLI was run under `--no-write` against a pristine project with before/after
  content hashes. Nothing outside `.refdes/schema.json` changed, in any command.
  The refusals match `docs/cli-reference.md:11` exactly: `fetch`, `init`,
  `standard upgrade`, `standard add-preset`, `standard remove-preset`,
  `former-ids propose --confirm`, `history capture`, `history redact`,
  `history migrate-seals` all refuse with exit 2; `revision` and `release` print
  `would stamp N items to .refdes/baselines/<name>.` and write nothing; `keys
  adopt` prints the full plan; `stub-tests` says `would write 1 stub(s) to
  items/stub-tests.md: BND-THM-001`. A stale schema warns
  `not refreshed (--no-write)` rather than silently writing. This is a lot of
  surface to keep consistent and it is consistent.
- **The release gate behaves like a real gate.** It fails naming the uncovered
  bound, it fails naming the unpinned citation and the item that cites it, it
  passes when both are fixed, and it refuses to re-stamp a name with different
  content in terms that explain the permanence:
  `'v0' is already stamped as a release (at …) with different content. Baseline
  names are permanent once written -- delete .refdes/baselines/v0.yaml first if
  that was intentional, or choose a new name.` Re-stamping unchanged content is
  a no-op with a clear message. `release_gate:` overrides work, unknown rule
  names are caught with the full list, and an empty `release_gate: {}` means
  defaults rather than "no gates".
- **`standard upgrade` chains correctly and migrates real content.** v1→v3 in
  one invocation applied both deltas in order and composed them correctly:
  `constraint` became `bound`, `CON-` ids became `BND-`, `title:` went
  `title:`→`text:`→`body:` across the two steps without losing its value,
  `equivalent:` became `drop_in:`, keys were minted, and previously stamped content hashes carried
  forward rather than churning. An ill-formed migration mid-chain rolled back
  cleanly. `--to 1` from v1 is a configuration error, not a crash.
- **Imports do the hard thing right.** Tightening a bound in the *upstream*
  project and rebuilding made the *downstream* project's check fail on its own
  arithmetic, with both numbers shown, without either project sharing a file.
  Version-pin drift is refused with a message that names both versions and says
  which side to change. A missing artifact is an error, not a silent empty
  import. Imported items are validated by their own schema and correctly absent
  from downstream coverage.
- **`fetch` on local files is careful and well-gated.** Pinning records sha256;
  drift warns once and names every citer; `--update` re-pins; `keep_copy:` on a
  local path is refused with a reason; `..` and absolute escapes are refused;
  `--no-write` refuses. The `unpinned_citations` gate rule flipped from FAIL to
  pass across a single `refdes fetch`, which is exactly the workflow the docs
  describe.
- **`history` is guarded the way a redaction surface should be.** `redact`
  without `--confirm` exits 2 and prints both the irreversibility warning and
  the honest caveat that Git history, clones and published sites are out of
  reach. With `--confirm` it writes a redaction event naming what was removed by
  digest and event id only, and repeats the Git caveat. `capture` is idempotent
  and says so. `migrate-seals` records legacy seals as hash-only markers, leaves
  the original seal file untouched, and is idempotent.
- **Workspaces enforce the thing that matters.** A link from `product-b` into a
  non-shared `product-a` warns that `product-b` would gain a hidden dependency;
  the same link into `shared: true` `platform` is silent. Workspace-move drift
  is detected, refused, and escapable only through an explicit
  `--accept-board-move`. Board/workspace name collisions are caught at load with
  a message that explains the actual reason (generated report filenames).
- **`serve` remains side-effect-free** — re-verified this run against a keyless
  project that every other command rewrites: `serve` started, served `/api/items`,
  `/api/item/<ref>` and `/api/revision`, and left every file byte-identical.
- **The source-picker HTTP surface is coherent.** All four routes respond, the
  candidate list is sensible (numeric tokens from the cited text, page and
  section guesses), and the propose route validates rather than trusting the
  client.
- **Run 1's baseline held.** Idempotent rebuilds, `serve`'s token/Origin posture,
  diagnostic quality, and the bound-tightening headline promise all still work;
  nothing in run 1 §3 regressed.

---

## 4. Suggested shape for run 3

Lead with the BUG 1 follow-through, because it is the only finding this run that
changes what a *green* build means:

- re-run the fresh-clone git repro against `check`, `ls`, `index`, `audit` and
  confirm whether `_load_write_notice()` now fires from all of them, and whether
  the `check` description still claims "the one exception is `.refdes/schema.json`"
- re-run both read-only-tree variants and confirm they degrade to warnings
- then the still-open run 1 items: BUG 1 (editor `defaults.prefix`), BUG 2
  (lost-`key:` recovery via `keys adopt`), BUG 3 (`--reseal` auditability),
  F4 (`getting-started.md` reaching a green build)

Areas neither run has covered, in rough order of value:

1. **A real remote `fetch`** — HTTP status handling, redirects, `rev:` inferred
   from `Last-Modified`/`ETag`, a 404 on a previously-pinned citation, and what
   `missing_kept_copies` does when the keep-copy download fails halfway. Needs
   network egress; this sandbox has none.
2. **A real PDF through the source picker** — text-layer extraction, page
   resolution, the `pypdf`-missing fallback, and `--require-citations` interacting
   with a citation that has a page but no rev.
3. **The VS Code adapter under a real VS Code** — or, better, a headless
   `.vscode-test` harness so the gate can run it. Until that exists, this surface
   is ungateable and should be labelled as such in the README.
4. **Concurrent editing** — two `serve` instances over one project, an edit
   landing during a `build`, and whether the optimistic-concurrency token holds
   against a CLI write (run 1 only tested editor-vs-editor).
5. **Scale** — the largest project the docs imply (many boards × many workspaces
   × thousands of items), for both correctness of coverage accounting and
   whether `check` stays fast enough to remain a pre-commit command.
6. **`keys adopt` / `revise` / `former-ids` as recovery tools**, deliberately
   breaking identity and repairing it, rather than as sweep casualties.
7. **Windows** — `docs/` mentions Windows-specific schema-path behaviour
   (finding 9) that no run has tested.
