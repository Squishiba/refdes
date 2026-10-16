# User-simulation release gate — run 9 (f33efa4..12bbf6b as an author)

Report-only run: no code or docs changes. Every claim below was produced by
running this branch's own code (`PYTHONPATH=<worktree>/src … python -m
refdes.cli`, refdes 0.5.0, Python 3.13) in fresh probe projects under
`.scratch/run9/`, one per sweep case, each started from `refdes init`
(hardware@3).

The delta's nine src commits, verified with
`git log --oneline f33efa4..12bbf6b -- src/`:

```
6d017b1 fix: four CLI/message nits the docs checks found (#286 #294 #287) (#305)
1c4e9a8 fix(blocks): four {{block}} defects from the blocks.md docs check (#306)
5937a36 fix(editor): keep new workspace creates in their workspace (#302)
4a79d51 fix: the vocabulary page's text tells the truth about five keys (#304)
a3e9600 fix(build): an unreadable image is a named build error, not a crash (IMAGE-ASSET-007) (#268)
4357a6c fix(theme): a light override keeps its light value in :root (#296)
bd4a82f fix: a blocked_by diamond (reconverging paths) is not a cycle (#295)
8da0dc7 Fix run-7 small nits: audit pages-unchecked, stamp refusal cause, ls tag strings (F13/F14/F16) (#273)
086b7b0 fix(lifecycle): adopted no-op re-stamp + docs/lifecycle.md verification (#277)
```

## 0. Headline summary

All nine merged fixes reproduce as advertised, each in a fresh project, from
the PR's own claim, and each survived a push on an adjacent spelling:
#305 (refuses `--workspace ''` in `ls` and `check`, quotes the XLSX
destination text, help lists every promoted class), #306 (mutual-exclusion
error, composite `from=`, empty-board note — plus the stale-label half of a
composite refreshing to the renamed id), #302 (HTTP create lands in the
selected empty workspace's own path, prefix not inherited, explicit override
wins, destination outside `items/` refused), #304 (all five vocabulary
definitions match live behavior, and the behaviors themselves reproduce),
#268 (named reference error, no traceback, check/build counts equal, FIFO
and site.assets refusals), #296 (light values in `:root` for both custom
tokens and the `paper` built-in), #295 (diamond clean, true cycle still
names the full path), #273 (audit names the unchecked-pages reason, stamp
refusal keeps its read-only cause, mapping tags no longer substring-match),
#277 (adopted no-op re-stamp, conflict on real change, non-adopted
unchanged).

Two new findings, both silent-friction, neither introduced by this delta:
**R9-F1** — a `checks:` written as a fenced ` ```yaml ` block in a markdown
item's body renders as literal text and the bound check silently never runs
(the docs page shows a ` ```calc ` fence and a ` ```yaml ` fence adjacent,
which invites exactly this); **R9-F2** — adding `id="…"` to a calc fence of
an item that is already *captured* trips the "edited after captured"
semantic-content warning, although `math.md` says a block name is "a label
on the rendering". Nothing in this run blocks a release on behavioural
grounds; F1 is the one worth a look.

---

## 1. The delta, swept as an author

### 1.1 #305 — `--workspace ''` refused, XLSX destination named, help completed

Fresh project, `workspaces: {product-a, product-b}` registry, one item with
`workspace: product-a` in front matter (`refdes ls --workspace product-a`
lists it):

```console
$ refdes ls --workspace ''      # exit 1, no listing printed
ERROR   <project> — --workspace '' is not a workspace declared in
refdes-project.yaml's workspaces: registry. An empty value filters nothing and
is refused rather than silently listing everything; omit the flag to list
every item.
$ refdes check --workspace ''   # exit 1
ERROR   <project> — --workspace '' is not a workspace declared in
refdes-project.yaml's workspaces: registry.
1 items, 1 errors, 0 warnings
```

The documented asymmetry for unknown *names* holds: `ls --workspace nosuch`
prints `no items match` (exit 0), `check --workspace nosuch` gives the
registry error (exit 1). `audit` has no `--workspace` flag at all (usage
refuses it), matching the PR's "check and ls" grep.

XLSX (item cites `analysis/model.xlsx`, calc `source("analysis/model.xlsx",
"badname")`, defined name `badname` → bare `A1:B2`):

```console
$ refdes fetch
FAILED  analysis/model.xlsx: key 'badname': defined-name destination 'A1:B2'
is not a cell reference this reader can parse -- a defined name must point at
exactly one cell, like Sheet1!$B$2 (the existing record for
analysis/model.xlsx is unchanged)
```

No `NoneType` in sight; file, key and destination text all named. Adjacent
spellings: `Sheet1!A1:B2` takes a different, already-clean path (`defined
name must refer to one cell: not a single cell`), and a valid `Sheet1!$B$2`
fetches (`extracted analysis/model.xlsx good = 12.5`).

`build --help` lists every class `--require-citations` promotes (unpinned,
missing cached blob, local-citation-changed, SOURCE FILE CHANGED pin,
unresolvable `section:`/`page:`), names what stays a warning (inconsistent
`keep_copy:`, case-differing path, disagreeing page/section), and records
that corrupt blob / missing file are already errors — the PR's full list.
The docs-only item (candidate-parts.md's suppressibility sentence) is not
behavioural; not probed.

### 1.2 #306 — the three {{block}} defects

Project with `boards: {power, aux}`, `workspaces: {rev-a}`, two log items in
power/rev-a.

1. `pages/t.md` line 3 `{{tree board="power" workspace="rev-a"}}`:
   `ERROR   pages/t.md:3 — {{tree board="power" workspace="rev-a"}} — board=
   and workspace= are mutually exclusive. tree accepts: at most one of the
   two.` — build refused, file+line named.
2. `{{cascade from="LOG-A-002@q4gdf6tjv4q" direction="up" via="blocked_by"}}`
   (key from `refdes ls --keys`) builds clean; the root row prints
   `data-ref="LOG-A-002">LOG-A-002` — resolved display id, walk ran (child
   row `Blocked by … LOG-A-001`).
3. `{{tree board="aux"}}` with nothing in board `aux`: renders
   `No items in aux.`, and `grep -c "<li>IO</li>"` = 0.

Push: renaming the cascade root (front-matter `id: LOG-A-002` → `LOG-A-009`)
leaves the composite's display half stale — the block resolves by key and
the root row now prints `LOG-A-009`. A bogus key (`LOG-A-002@zzzzzzzzzzz`)
is a named build error (`… does not exist.`), build refused.

### 1.3 #302 — editor create lands in the empty declared workspace (serve API)

`item_layout: workspace`, workspaces `product-a`/`product-b`, boards
`board-a`/`board-b`; the only item file is
`items/product-a/board-a/requirements.yaml` (defaults `prefix: REQ-A`, one
requirement). Server on 127.0.0.1:8765 via
`serve --no-open --token-file …`; cookie from `GET /edit/?token=…`, API
reads need `X-Refdes-Token` (POST also needs a matching `Origin` —
`serve/server.py` header rules).

```console
$ GET /api/create/preview?type=requirement&board=board-a&workspace=product-b
{"id":"REQ-001","reason":null,"destination":"items/product-b/board-a/requirements.md","destination_exists":false}

$ POST /api/items/create  {"type":"requirement","fields":{"title":"24V rail"},
                           "destination":"items/product-b/board-a/requirements.md"}
{"kind":"created","ok":true,"id":"REQ-001","key":"75ejkyyeb69",
 "path":"items/product-b/board-a/requirements.md", …}   # http 200
```

The new file is Markdown inside product-b's registered path with
board-a's segment contributed; the id is `REQ-001` — product-a's
`REQ-A` prefix is *not* inherited — and product-a's yaml is byte-identical
afterwards (md5 unchanged). Push: workspace-only preview after that file
exists reuses it (correct); `board=board-b&workspace=product-b` suggests a
new `items/product-b/board-b/requirements.md` (create honoured it);
`board=board-a&workspace=product-a` still suggests the existing scoped yaml;
unscoped preview unchanged (product-a's file). Destinations outside `items/`
refuse with `a destination must live under items/, where the project's
sources are` (422). One API-only nit (F18, below): `preview?…&workspace=
nosuchws` silently degrades to the unscoped suggestion — unreachable from
the editor UI (the picker only offers registered workspaces), and create
takes no workspace parameter, so the blast radius is a direct API caller.

### 1.4 #304 — the vocabulary page tells the truth

`_site/vocabulary.html` (after `refdes build`, one item so the page is
generated). All five sections match live behavior:

- **verifies**: the example declares the verb from the test only —
  `TST-PWR-001 verifies: [REQ-PWR-001]` with "REQ-PWR-001 gains verified_by:
  [TST-PWR-001] as the computed backlink — the inverse name is not
  authorable on the requirement." Authoring `verified_by:` on a requirement
  really is refused: `unknown field 'verified_by' on requirement -- did you
  mean the link 'governed_by'?`
- **body**: "for types whose content is the statement itself the type
  requires it — an empty body is then a warning, not an error, so a draft
  stub can still build." Reproduced: a stub requirement warns, exit clean.
- **former_ids**: "Nothing writes it when ids are re-minted: add entries by
  hand, or with `refdes former-ids propose --confirm` against a baseline."
  Reproduced: `refdes former-ids propose` with no baseline → `no baseline
  stamped yet -- nothing to compare against. Run 'refdes revision <name>'
  first.`
- **board**: "resolved only against the `boards:` registry …; an
  unregistered segment warns and leaves the board unset". Reproduced: a file
  under `items/nosuch/` with a `boards: {power}` registry warns
  `no board: 'nosuch' is not in the boards: registry`.
- **section**: "The type asserted for the items that follow it… an item
  naming a different type inside the section is an error, not an override" —
  the item-page-heading story is gone.

### 1.5 #268 — unreadable image is a named build error

`items/shot.png` with mode 000, referenced as `![the rail](shot.png)`:

```console
$ refdes check      # exit 1, no traceback
ERROR   items/log.md:2 [LOG-A-001] — image src 'shot.png' exists at
'items/shot.png' but cannot be read: Permission denied. Make the file
readable, or point the reference at a readable file
1 items, 1 errors, 0 warnings
```

`refdes build` reports the same count and writes the site. Push: a mode-000
file inside a registered `site.assets: [static]` directory, referenced by
nothing, is refused by every build naming the file and the removal advice
(`site.assets file 'static/locked.pdf' cannot be read: Permission denied.
… remove it from the site.assets: directory -- it is not published`);
check/build counts equal (3 errors each), stable on a second run;
`chmod 644` makes the errors disappear. A FIFO referenced as an image is
`does not exist` (the resolution gate's `isfile` rejects it before the
probe — the PR's documented race posture, not a regression).

### 1.6 #296 — light override keeps its light value

`site: tokens: {light: {--bg: "#fffdf5"}, dark: {--bg: "#101018"}}`, build:
`_site/assets/theme.css` starts

```css
:root {
  --bg: #fffdf5;
}
@media (prefers-color-scheme: dark) {
:root {
  --bg: #101018;
```

Push: `theme: paper` with no tokens puts the built-in's light palette in
`:root` (`faf6ee` present). `theme: paper` *plus* a `--bg` token correctly
replaces paper's own light bg in `:root` (the override wins; paper's
displaced `#faf6ee` is expected, not a loss).

### 1.7 #295 — the diamond is not a cycle

Five log items, `LOG-A-005 blocked_by [LOG-A-003, LOG-A-004]`,
`LOG-A-003 blocked_by [LOG-A-004]`: `refdes check` → `5 items, 0 errors,
0 warnings` (exit 0; the pre-fix repro was
`blocked_by cycle: LOG-A-005 -> LOG-A-004`). `refdes audit` shows both
chains: `LOG-A-005 <- LOG-A-003 <- LOG-A-004 (root)` and
`LOG-A-005 <- LOG-A-004 (root)`. Push: adding `LOG-A-004 blocked_by
LOG-A-005` (a true 2-cycle behind the diamond) still raises
`blocked_by cycle: LOG-A-003 -> LOG-A-004 -> LOG-A-005 -> LOG-A-003`.

### 1.8 #273 — audit reason, stamp cause, ls tags

- **F13 (audit)**: a local `.txt` citation cited with `page: 3` prints
  `pages unchecked hash-only  cited by LOG-A-001` plus the reason
  "it is not a PDF, so its pages are never counted". A PDF whose count
  fails prints the count-failure reason
  (`pypdf could not read the PDF: …`). The third reason (local bytes,
  fillable by plain `refdes fetch --path`) needs a record written by a serve
  accept-pin — not reachable from the CLI surface I drove; it is pinned by
  #273's tests. Adjacency: replacing a pinned PDF's bytes makes `check` warn
  `local citation 'docs/three.pdf' has changed since it was pinned -- … run
  'refdes fetch --update --path docs/three.pdf'` — names the exact repair.
- **F14 (stamp)**: `.refdes` chmod 500, `refdes revision rev-a` →
  `error: cannot write .refdes/baselines/rev-a.yaml (read-only tree?) --
  revision 'rev-a' was not stamped. Make the tree writable …` — the
  read-only posture is byte-identical as promised. The ENOSPC cause-reading
  is not simulable on this disk; #273's tests pin it.
- **F16 (ls tags)**: item with `tags: [{board: power}, thermal]` (mapping
  element, a #235 load error, item still lists):
  `ls --tag power` → `no items match`; the free-text query `ls power` →
  `no items match`; the string tag `ls --tag thermal` →
  `LOG-A-001  log  dict tags item`. The dict's repr no longer matches.

### 1.9 #277 — adopted no-op re-stamp

`refdes keys adopt` (records `.refdes/keys-adopted.yaml`), then
`refdes revision rev-a` (stamped: 5 items), then the same command again:

```console
$ refdes revision rev-a
revision 'rev-a' unchanged since 2026-10-16T18:46:26Z -- nothing to stamp.   # exit 0
```

The false "already stamped … with different content" conflict is gone.
Push: editing an item and re-stamping the same name gives the real conflict
(`'rev-a' is already stamped as a revision … with different content.
Baseline names are permanent once written …`, exit 1); a non-adopted
project's identical re-stamp is also a no-op (exit 0), so the fix didn't
move the un-adopted path.

## 2. Daily-driver pass (author with design logs)

Fresh project, written as an author writes: requirement + bound
(`limit: "<= 0.15 W/in^2"`) + four log entries — the first with a calc block
and a check against the bound, the second `follows`/`addresses`, the third
`blocked_by`, the fourth `amends:`; a `pages/overview.md` with a prose
`[[LOG-A-001]]` link and an image; `check`, `build`, then read the HTML.

What worked well: `follows` capture printed `captured LOG-A-001: LOG-A-002
now follows it` on first check; the check verdict renders as a task
(`Failing checks  LOG-A-001  P_dens violates BND-THM-001`) and `check`
reports `P_dens violates BND-THM-001: worst case 0.2366 W/in² vs <= 0.15
W/in^2` (exit 1); the image lands at
`assets/pages/rail.2d4566582844690f.png` with the `src` rewritten;
`[[LOG-A-001#calc:thermal]]` resolves to `log-a-001.html#calc-thermal`.

Confusions (both new findings):

- **R9-F1 (moderate)** — following `docs/checks.md`'s "Declaring a check"
  example, which shows a ` ```calc ` fence and a ` ```yaml ` fence with
  `checks:` adjacently, I wrote the check as a body fence in the markdown
  item. The fence renders as literal prose text on the page
  (`checks: - value: P_dens against: BND-THM-001`), the bound check silently
  never runs, `check` reports 0 errors. Moving `checks:` to the front matter
  makes it work. Nothing on the fence path says "this block is inert here".
- **R9-F2 (low)** — adding `id="thermal"` to the calc fence of LOG-A-001,
  which `follows` had already captured, trips
  `LOG-A-001: edited after captured -- current semantic content differs from
  the snapshot … append a new entry with amends: … instead`. `math.md` says
  the block name is "a label on the rendering" — a pure label edit reads as
  a semantic content change, and the advice (append an amends entry) is
  disproportionate for a label.
- Nit: `[[LOG-A-001#calc]]` (no name) warns as a *field* reference
  ("names field 'calc', which type 'log' does not declare") — the anchor
  spelling `#calc:thermal` is not hinted; the warning is at least loud.

## 3. Findings summary

IDs are per-run (prefix R9) because run 8a's numbering lives in PR #309, not
on main.

| # | Severity | Finding |
|---|---|---|
| R9-F1 | moderate | A `checks:` list written as a fenced ` ```yaml ` block in a markdown item body renders as literal text; the bound check silently never runs, `check` says 0 errors. `docs/checks.md`'s "Declaring a check" example (calc fence + yaml fence adjacent, §96-117) invites the shape; the front-matter spelling works and reports the violation. No diagnostic on the inert fence. §2 |
| R9-F2 | low | Adding a calc-fence `id="…"` (a "label on the rendering", `math.md`) to an item that is already *captured* by a `follows` trips the "edited after captured — current semantic content differs" warning, advising `amends:` for a label-only edit. §2 |
| R9-F3 | nit | Preview nit, API-only: `GET /api/create/preview?…&workspace=<unregistered>` silently falls back to the unscoped suggestion. Not reachable from the editor (the picker lists only registered workspaces; create takes no workspace field). §1.3 |
| R9-F4 | nit | `[[ID#calc]]` without a block name is interpreted as a field reference (warns "names field 'calc'"); the anchor spelling is `#calc:<name>` and the warning doesn't hint it. Loud, so cosmetic. §2 |

Carry-forward: #273's F13 local-bytes-fillable reason and F14's ENOSPC
cause-reading were not reproducible from the CLI surface here (§1.8);
#305's docs-only item 4 not probed (§1.1). All nine PRs: FIXED.

---

## Appendix — reproduction

- Branch `user-sim-run9` at `12bbf6b` (== main); probes ran this worktree's
  `src/` via `PYTHONPATH`, refdes 0.5.0, Python 3.13.
- Probe projects under `.scratch/run9/` (gitignored), one per §:
  `p-base` (bare `refdes init`), `cf305`, `cf305x`, `cf306`, `cf302`,
  `cf295`, `cf273{,b,c}`, `cf277b`, `cf296{,b}`, `cf268`, `cf304`, `dd`.
  Each item set is quoted inline in its section.
- The serve sweep: port 8765, token file `.scratch/run9/ed-token.txt`
  (token is per-launch, not reproduced), cookie jar `.scratch/run9/jar.txt`;
  server launched in the background and killed by PID at the end. API reads
  need `X-Refdes-Token`; POSTs also a matching `Origin`.
- Gates (this branch is report-only — no code changes, gates confirm the
  baseline): full suite `4005 passed, 2 skipped`, exit 0 (5:36,
  `.scratch/suite.txt`, no load-flake re-run needed);
  `ruff check --select E9,F src tests` → All checks passed;
  `python docs-site/gen_examples.py --check` → up to date.
