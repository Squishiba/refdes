# Fixing the stale `Status:` lines in `docs/design/backlog.md`

**Scope:** a factual-correctness pass over `docs/design/backlog.md`, plus one
retired-calc-spelling example in `docs/design/calc-sources.md`. No rewrite, no
restructuring — every edit below is a claim that was *false* and is now
*true*, or (for the header) *stale* and is now *current*.

- Verified tree: branch `rare-jellyfish` at `bda7ab5`, 2026-09-27.
- Source of the finding list: `in-prog-logs/release-readiness-audit.md` §6
  (ten rows) and §6.1.

## 0. What I could and could not verify

Per `AGENTS.md` I re-verified every claim against the tree rather than
trusting the audit. Concretely, that meant:

- **I could not run the tool.** This checkout has no installed `refdes` and no
  project dependencies (`python3 -c "import refdes"` → `ModuleNotFoundError`,
  and there is no `python`, only `python3`; no `.venv`). So every claim below
  about CLI surface, calc grammar, and shipped behaviour is **from reading
  the source**, cited by file and line — not from executing anything. I am
  stating that rather than implying I ran commands I did not run.
- **I did run one live check**, the one thing the audit claims about the
  outside world, because it is a claim about the world and not about the
  tree: `gh api repos/Squishiba/refdes/pages`.
- **Ten rows in the audit's table; nine were stale, one was already
  accurate.** I checked all ten and fixed nine. The tenth (finding 37,
  `backlog.md:2478`) claims nothing false — see §2.10.

## 1. Header (`backlog.md:12`)

Two defects, both confirmed:

- `git log -1 --format='%h %ad' --date=short e73ffea` → **`e73ffea 2026-09-14`**.
  The header said `(2026-09-15, `main`)`.
- `git rev-list --count e73ffea..HEAD` → **220** commits past it. The audit
  measured 210 at its own tree; the gap only widens, which is the point.

**Fixed** to name this pass and today's date, keeping the file's existing
self-warning about decay (which was correct and is left alone).

## 2. The nine stale lines

### 2.1 `backlog.md:334` — "No implementation exists." (browser editor, finding 15)

Stale. Verified in the tree:

- `src/refdes/serve/` is a package of 10 Python modules — `api.py`, `edit.py`,
  `filters.py`, `preview.py`, `security.py`, `server.py`, `sources.py`,
  `state.py`, `upload.py`, `__init__.py` — plus `static/`.
- `src/refdes/serve/static/` carries the whole front end: `app.js`,
  `editor.js`, `create.js`, `links.js`, `update.js`, `drafts.js`,
  `filters.js`, `images.js`, `sourcepicker.js`, `list.js`, `item.js`,
  `preview.js`, `controls.js`, `api.js`, `index.html`, `style.css`, `bar.css`.
- `src/refdes/serve/edit.py:1-2` — "The editor's one write path:
  `apply_edit(project_root, request)`".
- `refdes serve` is registered in the CLI (see §2.5).

**Fixed** to say the editor ships and to name what shipped. The two
architectural commitments the entry records (filtering, identity-for-the-author)
are *also* now implemented, so those sentences are corrected too — but the
"Decisions"/"What v1 must deliver" framing and the entry's structure are kept.

### 2.2 `backlog.md:360-361` and `:396-397` — "`threads.md` is design only"

Stale twice. Verified:

- `docs/design/threads.md:17` reads **`**Status: Phase 3a implemented.**`**
  (read directly, not via grep-for-"design only").
- `src/refdes/chains.py` exists, 31,200 bytes, and its docstring
  (`chains.py:1`) is "`follows:` chain walk: tips, the per-field fold, fork and
  cycle diagnostics" — with an explicit note that it reads raw `follows:`
  targets rather than `backlinks`/`resolved_links`.

The audit's judgement that the *conclusion* of the `:396-397` paragraph ("if
this work happens, it happens as `threads.md`, not as a resurrection of
finding 17") still holds is one I agree with and kept. Only the premise was
false.

### 2.3 `backlog.md:844` — "No `xlsx`/`csv`/`openpyxl` reference exists anywhere in the package"

Stale. Verified:

- `src/refdes/sources.py` exists. `sources.py:230` is `extensions = (".csv",)`
  on the CSV reader; `sources.py:465` is `reader = csv.reader(fh, strict=True)`;
  `sources.py:3` carries the `source("analysis/power-budget.csv", "some_key")`
  grammar in its own module docstring. (A second reader, `extensions =
  (".pdf",)`, is at `sources.py:678`.)
- `src/refdes/calc.py:643` gives the accepted line shape as
  `name = source("cited/file.csv", "key") | unit`.
- The *design* status moved on independently: `docs/design/calc-sources.md:1-3`
  reads "**Status: Reviewed** — Jared's decisions recorded 2026-09-19; question
  2 … decided 2026-09-21 … All section 11 questions are now answered."

**Fixed.** The xlsx/openpyxl half of the original sentence is *still* true
(`calc-sources.md:23-25` still scopes XLSX to "an optional `openpyxl` reader
in a later minor release"), so I kept that half and corrected only the part
that is now false.

### 2.4 `backlog.md:1402-1403` — "Nothing here is implemented yet; `includes:` still appears nowhere in the package."

Stale, and the "nowhere in the package" half is checkably false. Verified:

- `src/refdes/boards.py:116-146` is `included_map()`, a dedicated `includes:`
  resolver: `spec.includes` is read at `boards.py:135` and iterated at
  `boards.py:138`, resolving each named group's `contains` backlinks.
- `src/refdes/boards.py:149-158` is `displays()`, the one display predicate,
  carrying the explicit warning "Never use this where a number is produced --
  tallies, coverage and gates keep using `item.board` alone."
- `src/refdes/model.py:174` — `includes: list[str] = field(default_factory=list)`
  on the board spec.

**Fixed** to describe the shipped design, including the display/count
asymmetry the entry's own prose had already reasoned its way to.

### 2.5 `backlog.md:1426-1428` — "the editor does not exist yet … there is no `serve`"

Stale twice over, and the enumeration is now short by four commands.
Verified from `cli.py` directly — every `add_parser(` in the file:

| Command | `add_parser(` at | name literal on |
|---|---|---|
| `serve` | `cli.py:1367` | `cli.py:1368` |
| `keys` | `cli.py:1674` | `cli.py:1675` |
| `calc-rewrite` | `cli.py:1715` | `cli.py:1716` |
| `history` | `cli.py:1787` | `cli.py:1788` |

(`keys`, `calc-rewrite` and `history` each have their own sub-subparsers:
`keys adopt` at 1679, `history capture`/`redact`/`migrate-seals` at
1799/1814/1839.)

The line's own parenthetical `(cli.py:1182-1520 registers …)` is also stale as
a line range — the parser block now runs past 1839. **Fixed** by dropping the
line range (it will go stale again) and replacing the list with the commands
actually registered.

### 2.6 `backlog.md:1652-1653` — theming "Implementation not started."

Stale; shipped in three steps, which is exactly how the entry's own
"Recommendation and v1 scope" ordered it. Verified:

- Step 1 (the token layer) is covered by `tests/test_style_tokens.py` and
  `docs-site/gen_themes.py`, both present.
- Step 2a: `site: theme:` and `site: tokens:` are in the config key allowlist
  at `src/refdes/configcheck.py:48`, validated at `configcheck.py:210` and
  `:213`, and plumbed through `src/refdes/schema.py:772-773`
  (`theme=site["theme"]`, `theme_tokens=site["tokens"]`) into
  `src/refdes/model.py:772-781`.
- Step 2b: `src/refdes/theme.py` (26,542 bytes) and `src/refdes/contrast.py`
  (7,059 bytes) exist. `theme.py:3` names its own scope: "Finding 34 step 2b
  (on top of 2a's `site: theme:` / `site: tokens:` plumbing)". `contrast.py:1`
  is "WCAG contrast arithmetic for theme palettes".

**Fixed**, with the v1 *refusals* the entry lists left intact — those are
still what the code refuses, per `theme.py`'s "A theme is data, not a program"
and "A typo must not fall back silently" sections.

### 2.7 `backlog.md:2589-2591` — "The embedded diagram is still stale"

Stale. Verified:

- `grep -n -i 'mermaid|flowchart|graph TD' docs/links.md` matches **one** line,
  `:100`, and it is prose saying the diagram is *not* Mermaid. There is no
  checked-in diagram.
- `docs/links.md:94-105` now points at the generated page
  (`[vocabulary page](vocabulary.md)`, "generated from the resolved schema
  rather than hand-drawn, so it can't quietly go stale").
- `grep -n part_of docs/links.md` matches `:121` (the verb table row) and
  `:125` (the `hardware@3` note) — never a diagram, because there is none.
- `src/refdes/cli.py:1607` — the `--graph` help now says the SVG is laid out
  "here rather than handed to Mermaid or graphviz", and the flag no longer
  emits Mermaid at all.

The paragraph's *argument* — that generation is not what keeps a document
honest, and nothing regenerates a checked-in diagram — is intact and is
exactly what happened. Only "is still stale" is wrong. **Fixed** to record
that the deletion this entry decided on (`backlog.md:2580-2586` already said
the block "is deleted with it, not regenerated") has in fact happened.

### 2.8 `backlog.md:101-113` — GitHub Pages "has_pages: false", deploys failing

Stale, and this is the one claim in the table about the outside world, so I
checked it live rather than by reading a file:

- `gh api repos/Squishiba/refdes/pages` → `"status": "built"`,
  `"html_url": "https://squishiba.github.io/refdes/"`, `"build_type": "workflow"`,
  `"source": {"branch": "main", "path": "/"}`, `"public": true`,
  `"https_enforced": true`.
- `gh api repos/Squishiba/refdes --jq .has_pages` → `true`.
- `gh run list --workflow docs.yml --limit 5` → five consecutive
  `completed / success` runs on `main`, most recently `36371871267` at
  `2026-09-28T02:58:41Z`, 31s. The oldest of the five is
  `36365943376` at 2026-09-28T01:25:55Z.

**Fixed.** The "fix is a repository setting, not code" diagnosis was right and
is preserved as history; what changes is that the setting has been made.

### 2.9 `calc-sources.md:14` — the retired calc spelling

Separate item, same spirit. `docs/design/calc-sources.md:14` — the document's
headline example, under **Decision (recap)** — reads:

```calc
eff : 1 = source("analysis/power-budget.csv", "tps62913_half_load_eff")
```

`changelog.d/calc-colon-units-retired.breaking.md` makes that spelling a build
error. **The design doc's own example would now fail its own build.** The
current form is the Calcpad-style pipe (`changelog.d/calc-pipe-units.added.md`,
`docs/math.md:171`, `calc.py:643`'s own error message). Rewritten to match
`calc-sources.md:138`, which already had it right:

```calc
eff = source("analysis/power-budget.csv", "tps62913_half_load_eff") | 1
```

**Checked and deliberately not changed:** `calc-sources.md:952` also contains
`eff : 1 = source(...) ± 2 %`. It sits inside §11's record of a *rejected*
option ("A. No (recommended) … **Decision:** … Not option A as written"), so it
is a historical quotation of a decision, not a live example. Left alone on the
same reasoning the audit applied to `docs/design/extends.md:507`/`:515`. Flagged
here so the decision is visible rather than silent.

### 2.10 Checked, found accurate, left alone

- `backlog.md:2478` (finding 37), "The tree page already exists
  (`src/refdes/tree.py`)". `src/refdes/tree.py` exists, 19,054 bytes. The
  audit called the surrounding "decided" framing an understatement rather than
  a false claim, and I agree — "already exists" is true. No edit.

## 3. Two more factual errors found while verifying §2.6, and fixed

The theming entry (finding 34) carries a survey paragraph headed "**What
exists today, verified against the files.**" I checked it, because it makes
checkable numbers, and it is now wrong throughout:

- `src/refdes/templates/assets/style.css` is **572 lines**, not 441.
- `var()` appears **580** times, not 138.
- There is now a non-colour token block — `style.css:29+` reads "Design tokens
  (finding 34 step 1): the non-colour knobs a theme needs" — so "eleven custom
  properties" is no longer the whole token set.
- `base.html.j2:6` → the stylesheet link is at `:7`, and `:8` is a *new*
  conditional link for the generated `theme.css`.
- `render.py:880-882` and `render.py:1112-1114` no longer point at the
  `_site/assets/` style.css copy. `render.py:754-759` and `:811-814` are where
  that machinery lives now, but I did not renumber — the copy is still done,
  and a replacement pointer would be another thing to go stale.
- Two colour literals *do* survive, so that part held: `color: #fff` and
  `rgba(0,0,0,.18)` are still in the file, now at `style.css:256` and `:528`.

**Not a rewrite of the survey** — that would be re-doing the finding. Instead
the paragraph is now framed as what it was: a point-in-time survey dated
2026-09-21, with a note giving the current numbers and saying the counts
describe the pre-theming stylesheet. One clause further down ("A theme cannot
reach any of them **today**") was a direct present-tense falsehood and is now
past tense with a pointer to the Status line.

I also corrected one **line-number** citation in the sentence I was already
editing for §2.7: it pointed at `docs/links.md:143` for the `part_of` verb
table row, which is `:121` (and `:143` is now an unrelated paragraph about
`governed_by`).

### 3.1 A third one, in the same entry: a retired spelling in a live syntax description

The finding-38 entry describes the inline syntax a doc generator would have to
cover, and described a `calc` block's assignments as
``name : unit = expr` assignments (`calc.py:792-796`)``. That is wrong twice:
`calc.py:792-796` is tolerance-comparison code, and `name : unit = expr` is
the *retired* spelling (`calc.py:1415-1416` is where that retirement is
enforced). Corrected to the pipe form with its real anchors —
`PIPE_UNIT_RE` at `calc.py:1105`, split at `calc.py:1354-1357`.

**Pre-existing line-number drift I found here and did NOT fix:** the same
sentence's other pointers — `parse.py:576-609`, `blocks.py:416-426`,
`blocks.py:46`, `build.py:52`, `build.py:78` — no longer point at what the
sentence says they point at. That is a *class* of problem across a 2,900-line
decision record (every `file.py:NNN` in this file is a candidate, since line
numbers move and prose citations do not), and chasing it is a different,
much larger pass than the one asked for. **Flagged, not attempted.** A
follow-up that re-derives every `file.py:NNN` in `backlog.md` mechanically is
the right shape for that; doing it by eye inside a status-correction pass is
how half the numbers here got wrong in the first place.

## 4. Also confirmed, and the reason I left them alone

- The audit's §6.1 observation that `docs/design/extends.md:507` and `:515` are
  *inside a fenced block quoting the history of a Status-line rewrite* still
  holds (I did not re-read them in detail; nothing in my scope touches that
  file, and the instruction not to "fix" them is preserved by not editing it).
- The four `**Local model:**` / `**Local model (not decided — my read):**`
  verdicts in the entries I touched. Each is a decision record about a *class*
  of work ("design-judgment-heavy UI work with no mechanical acceptance test"),
  and a decision record does not become false because the work got done. Their
  surrounding prose ("Its dependencies are no longer the obstacle…") is still
  true. Left alone deliberately — rewriting them would be a rewrite, and the
  entry explicitly marks them as decisions rather than status.

## 5. What was NOT done

- `AGENTS.md`'s own surrogate-keys paragraph is stale the same way
  (audit §6.1, first bullet) — out of scope for this task, which named
  `backlog.md` and `calc-sources.md`. **Not touched.** It is the obvious next
  pass, and it currently contradicts the folded `CHANGELOG.md:184`.
- `refdes-project.yaml:8` and `refdes-schema.yaml:4` still say `field_sets:`
  (audit §7.2) — out of scope. **Not touched.**
- The pre-existing `file.py:NNN` citation drift described in §3.1 — out of
  scope. **Not touched**, and flagged.
- No `ruff check .`, no test run, no `refdes` invocation: nothing installed to
  run them with, and this pass changed no Python.

**Status: finished.** Nine stale `Status:` lines corrected, the file header
refreshed, one retired calc spelling fixed in `calc-sources.md`, and three
further factual errors found while verifying (the theming survey's numbers, a
drifted `docs/links.md` line pointer, and a retired spelling in a live syntax
description) corrected. Pre-existing `file.py:NNN` citation drift across the
file is flagged in §3.1, not fixed. Verified tree `bda7ab5`.
