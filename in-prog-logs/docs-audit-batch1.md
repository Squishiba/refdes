# Docs accuracy audit — batch 1 (markdown, math, links, blocks, pages, output, themes)

Task: audit `docs/markdown.md`, `docs/math.md`, `docs/links.md`, `docs/blocks.md`,
`docs/pages.md`, `docs/output.md`, `docs/themes.md`, one page at a time. Every
concrete claim is verified by running the real tool in a throwaway project under
`.scratch/`, never from memory or by reading the source. Only proven
discrepancies are edited, always with the smallest possible edit. No source or
test file is touched; a source bug found is recorded here and in the PR body, not
fixed. `docs/cli-reference.md`, `docs/standard-library.md` and `AGENTS.md` belong
to another worker and were not edited.
## How the verification was run

The installed `refdes` is an editable pointing at a worktree that no longer
exists, so every command is run as

```
$env:PYTHONPATH="<worktree>\src"
python -c "import sys;from refdes.cli import main;sys.exit(main(sys.argv[1:]))" <args>
```

Global flags (`--no-write`, `--require-citations` is a subcommand flag) go before
the subcommand. The throwaway project is `.scratch/proj` (`refdes init`, i.e.
`standard: {base: hardware, version: 3}`); a second project `.scratch/platform`
supplies an import for the cross-item-reference checks. Helper scripts live in
`.scratch/`: `r.py` (run the CLI and capture output), `linkcheck.py` (resolve
every relative link and heading anchor on a page), `mkpdf.py` (a small PDF with
an outline, for `section:` citations), `sub.py` (a literal string replace, to
avoid PowerShell quoting), `dump_schema.py` (`refdes schema` to a file).

Anchor convention used for link checking: **GitHub's**, because `docs/*.md` are
not part of any refdes project's `pages:` tree (this repo's `refdes-project.yaml`
declares no `site.pages`, and `pages_dir` defaults to `pages/`), so nothing in
the tool renders these files. GitHub keeps `_` and `-` in a heading slug and
drops other punctuation. This is also the convention the previous audit applied
when it corrected `coverage.md`'s two links into `links.md#blocked_by-and-the-cascade-report`.

## Link and anchor check (all seven pages)

`python .scratch/linkcheck.py markdown.md math.md links.md blocks.md pages.md
output.md themes.md` from the repo root.

Broken before this pass: two anchors in `docs/links.md` (both `[below](#…)`
pointers into a heading whose slug GitHub spells with an underscore). Both
fixed. No other broken relative link or anchor on any of the seven pages; every
`docs/*.md` cross-reference and every `docs/design/*.md` reference resolves.

Two stale anchors were also found on pages owned by other workers and are
reported, not fixed: `docs/standard-library.md:520` still points at
`links.md#blocked-by-and-the-cascade-report` (same underscore bug this pass fixed
in `links.md:119`), and `docs/cli-reference.md` / `docs/troubleshooting.md` /
`docs/design-log.md` point at `ids.md#renumbering-former-ids`, whose heading is
spelled differently.

## docs/markdown.md

### Claims checked

*Standard markdown* — one item body containing `# H1`/`## H2`/`### H3`,
`**bold**`, `*italic*`, `` `code` ``, `~~struck~~`, `[text](url)`, a nested
bullet list, a numbered list, a blockquote, `---`, a GitHub table, a fenced code
block with a language, and a five-column wide table. Built and read
`_site/req-pwr-001.html`: `<h1>/<h2>/<h3>`, `<strong>`, `<em>`, `<code>`,
`<s>`, `<a href>`, nested `<ul>`, `<ol>`, `<blockquote>`, `<hr />`, `<table>`,
`<pre><code class="language-python">`. All present.

*Wide tables scroll in their own box* — `assets/style.css` carries
`.body table, .grid { display: block; overflow-x: auto; }`.

*`---` starts a new item only with a YAML key and a later closing `---`* — a body
whose only `---` lines are followed by a blank line and a table kept the item
intact (2 items in, 2 items out) and rendered `<hr />`; a `---` followed by
`type: bound` did open a second item. Also confirmed in
`src/refdes/parse.py`'s `md_front_matter_blocks` (`KEY_LINE_RE` gate) and, by
experiment, that a `---` indented inside a `body:` block scalar is not a fence at
all.

*Calc blocks* — ```` ```calc id="losses" ```` renders
`<table class="calc" id="calc-losses"><caption class="calc-caption">losses</caption>`.
The four fence-line failures each produce a build error at the fence line naming
the fix: bare word (`'losses' is not an attribute`), unquoted value
(`id=losses` → same message), unknown attribute (`unknown attribute 'name'`), and a
name outside the grammar (`block name 'Losses' must match [a-z][a-z0-9_-]*`).
`refdes build` exit 1, no site-level crash.

*Inline values* — `{{P_diss}}` → `<code>0.2981 W</code>`; `{{P_diss | mW}}` →
`<code>298.1 mW</code>`.

*Cross-references* — bare `BND-PWR-001` autolinks to
`<a class="ref" href="bnd-pwr-001.html" data-ref="BND-PWR-001">`;
`[[REQ-PWR-001|the input range]]` renders the custom text. `[[fig:…]]` and
`[[cite:…]]` verified under their own sections.

*`#field` fragments* — link text is `CMP-FRAG-001#part_number` unless a `|label`
is given; an undeclared field warns "names field 'nosuchfield', which type
'component' does not declare" and renders `<span class="ref ref-missing">`; a
declared-but-empty field (`refdes`) still has `<tr id="field-refdes"
class="field-anchor">` on the target; `checks` links to `#field-checks`; the
`citations` field links to `<section class="citations" id="field-citations">`.

*Images* — a local `src` resolves against the source file's own directory
(`items/figures.md` + `figures/pattern.png` → `items/figures/pattern.png`, and it
does *not* resolve against `items/decisions/figures/...`), is copied to
`_site/assets/items/figures/pattern.c414cd0e204de974.png` (same directory
structure, short content hash in the leaf name), and the rendered `src` points at
the copy. An unresolvable `src` is a build error reading exactly
`image src 'figures/nope.png' does not exist`.

*Image bytes in the content hash* — `src/refdes/build.py:1435` has
`HASH_FORMAT = 5`; swapping the bytes of `pattern.png` changed the referring
item's content hash (`163011d993f76cad` → `ecd635df1c826bba`) while an item with
no image hashed identically before and after.

*`site.assets:` search path* — with `assets: [assetsdir, photos/shared]`, a bare
`curve.png` that does not resolve beside its source is found at
`assetsdir/curve.png` and copied **verbatim** to `_site/assets/assetsdir/curve.png`
(no content hash), while a relative `figures/pattern.png` in the same body is
still content-hashed. Adding `photos/shared/curve.png` turns the same line into
the documented refusal, naming every candidate: `image src 'curve.png' is
ambiguous: it exists in more than one site.assets directory
(assetsdir/curve.png, photos/shared/curve.png). Write the path relative to
items/assets.md instead of the bare filename, or rename one of them`.

*`[text](file.pdf)` is not rewritten* — the href is emitted verbatim; the declared
asset directory is copied but the link itself is untouched.

*Figure attributes* — `{id="fig-curve" width=60% caption="…"}` produces
`<figure class="md-figure" id="fig-curve" style="width: 60%">` with
`<figcaption>Figure 1 — …</figcaption>` and the `alt` still on the `<img>`;
`caption` falls back to `alt` when omitted. An inline image (in a sentence)
keeps `width` on the `<img>` and drops `caption`/`id` with
`caption= is ignored on an inline image; put the image in a paragraph of its own to
get a captioned figure`. `the set {braces, commas}` is untouched.

*Per-document figure numbering* — the same figure is `Figure 1` on its own item
page and `Figure 2` in `document.html` when another item's figure precedes it
there. A cross-item `[[fig:…]]` from an item's own standalone page warns
"exists on REQ-BND-001 but is not rendered on this page — figure references only
resolve within the same rendered document" and renders unresolved. A duplicate
figure id is a build error naming both locations. A missing one warns.

*Citations* — `refdes schema` shows the `citations` property on `component`
with `path`/`rev`/`page`/`section`/`part_number`/`keep_copy`/`id` and
`required: [path]`; `src/refdes/standards/hardware/v3/base.yaml` declares it as
`{ type: citations, on_change: invalidate }`, exactly as the page says. A local
`path:` citation is read from disk with no network, pinned by `refdes fetch`
(`fetched docs/mech/board-outline.pdf sha256=58f380142b76… hash-only`), and
published to `_site/assets/citations/58f3…f184780aa.pdf`; `references.html`
lists it once, grouped by path. Refusals all confirmed by running `refdes fetch`
on a project containing them: `keep_copy:` on a local path (`error: keep_copy: on
local citation path … is meaningless`), an absolute path, a `..` escape, and a
backslash. A local file that changed since it was pinned warns naming every citer
and becomes an error under `--require-citations`; a cited local file that does not
exist is an error at `build` with no flag. Citations get their own
`<section class="citations">` on the item page rather than a field-table row.

*`section:`* — a real PDF with an outline resolves
`section: Application and Implementation` to page 1, the lockfile records both
`sections:` and `sections_sha256:`, the failed lookup prints
`no outline entry titled 'No Such Section'`, and the unresolvable section is
dropped from the lockfile rather than left pointing at a page. The resolved page
fills both the `#page=1` fragment and the Page column. The page's own claim that
`section:` is allowed on a local `path:` citation (no `keep_copy:`) and refused on
a hash-only remote one is consistent with what ran: `keep_copy: true` on a local
citation is refused outright.

*`[[cite:id]]`* — links to `cmp-sec-001.html#cite-ds-1` (the declaring item's own
page, never `references.html`), custom text works, and an unknown id warns
`reference to citation 'nope', which does not exist`. A citation id outside
letters/digits/`-`/`_` is rejected at declaration
(`citations[0].id: 'bad id!' is not a valid citation id (letters, digits, '-', '_'
only)`).

*Verification table* — the "no lockfile entry" row was checked directly: a remote
citation with no lockfile record is an `info` (hidden until
`check -v`) and an error under `--require-citations`. `refdes fetch --help`
confirms it is "The only command that touches the network", that the local copies
land in `.refdes/copies/`, and that all four documented invocations
(`refdes fetch`, `--item`, `--path`, `--update`) exist.

*Not supported* — raw HTML is escaped, definition lists and footnotes render as
literal prose, and `::: {.warning}` renders as text. `pyproject.toml` lists
`markdown-it-py>=3.0` and no `mdit-py-plugins`, which is the reason the page gives.

### Discrepancies fixed

1. **"A requirement's `text`" is the hardware@2 field name.** At `hardware@3`
   `requirement.text` was renamed to `requirement.body`; `refdes schema` lists
   `requirement`'s properties as `body`, `governed_by`, `history`, `id`,
   `last_reviewed`, `note`, `owner`, `part_of`, `prefix`, `rationale`, `refines`,
   `source`, `status`, `tags`, `title`, `type`, `workspace` — there is no `text`.
   Changed to `body`.

2. **The local-path citation example uses a type that has no `citations` field.**
   `BND-MECH-001` is a `bound`, and `refdes schema` shows `bound` carrying no
   `citations` property (`decision` and `component` are the only two that do), so
   the example builds with `WARNING … unknown field 'citations' on bound`. The
   same page's own field-declaration snippet is a `component`, so the smallest fix
   that keeps the illustration is to make the example a `component` too.

### Unverifiable here, left as-is

The remote-URL half of the citation chapter (fetching over the network,
`keep_copy: true` for a remote citation, the inconsistent-`keep_copy:` warning
across items, `--update` against a remote path). Network happened to be available
in this environment and `refdes fetch` did pin one real datasheet, but pinning a
*remote* citation is not the same claim, and none of the remote-specific
diagnostics in that section were reproduced. Left as written.

## docs/math.md

### Claims checked

*The opening example* — built the exact block from the page. The documented
output table is exact: `V_out → 3.3 V`, `P_diss → 0.2981 W`, `A_board → 1.26 in²`,
`P_dens → 0.2366 W/in²`.

*Block naming* — `id="losses"` yields the `calc-losses` anchor and the `losses`
caption; an unnamed block gets neither. `src/refdes/calc.py:836` has
`BLOCK_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,39}")`, which is the page's stated
"1–40 characters, matching `[a-z][a-z0-9_-]{0,39}`" exactly. A 59-character name
is refused; a name outside the grammar is refused. `[[DEC-PWR-001#calc:losses]]`
links to the table; a miss warns and names the blocks that do exist
(`has no calc block named 'nope' (it names: second)`); a bare `#losses` fragment
warns that type `decision` declares no field `losses`; `{{calcblock item=… block=…}}`
on a narrative page renders the named block's table. A value assigned in one block
is visible in another (item-wide scope), two blocks assigning the same name get the
ordinary "assigned twice" error, two `id="losses"` fences in one item is an error
naming both lines, and the same block name in two different items is fine.

*Cross-item references* — `V_in = DEC-PWR-001.V_in` evaluates, stores expanded on
disk as `DEC-PWR-001@kd0yezrscp5.V_in`, arrives with its `± 5%` intact
(`12 V 11.4 V … 12.6 V`), and re-expresses under a pipe unit
(`| mV` → `12000 mV 11400 mV … 12600 mV`). Under `--no-write` the bare spelling
resolves and nothing is written; the next writable `build` freezes it to the
composite. A reference that also assigns the same name in the same item gets the
"assigned twice" error. All four documented error messages were produced by
running them: missing item, unknown name (`does not define 'Iout' (it defines: …)`),
target's own calc failed, and `calc reference cycle: DEC-CYC-A -> DEC-CYC-B ->
DEC-CYC-A`. `DEC-PWR-001.losses.P_diss` is refused naming `DEC-PWR-001.P_diss` as
the working form. A reference into an imported item is refused with
`points at DEC-UP-001, an imported item; references into imported items are not
supported`. Renaming a value inside the target fails loudly at the dependent's own
reference line.

*`refdes audit`* — after stamping a baseline and moving `V_in` from `12 V` to
`11.4 V`, `refdes audit` printed the documented two lines verbatim
(`changed   2   DEC-B-001, DEC-PWR-001` /
`DEC-B-001 -- referenced DEC-PWR-001.V_in: 12 V (11.4 V … 12.6 V) -> 11.4 V (10.83 V … 11.97 V)`).
Changing only `eff` in the target left the dependent out of the changed list
entirely, as the page says.

*`source()`* — the documented CSV pins with `refdes fetch`
(`extracted analysis/power-budget.csv rail_3v3_power = 1.85`); `| 1` and `| W`
label the bare number without converting it (`1.85` under `| mW` still displays
`1.85 mW`); `± 2 %` on the source line works; `source()` outside the whole
right-hand side is refused, as is a missing `| unit`; a citation on another item
does not authorize the read. A changed file warns with the documented sentence and
promotes to an error under `--require-citations`; the same sentence appears under
each affected calc row on the rendered page; `refdes fetch --update` prints
`analysis/power-budget.csv: rail_3v3_power: 2.5 -> 2500` and, on an exact 1000×
change, the advisory
`changed by exactly a factor of 1000 (2.5 -> 2500) -- check the spreadsheet's unit (mW vs W?) against the `| unit` on the calc line; advisory only`.

*Tolerances* — the documented interval output is exact: `V_in = 12 V ± 5%` renders
`12 V  11.4 V … 12.6 V` and `P = V_in * 2 A` renders `24 W  22.8 W … 25.2 W`.
`x - x` on `x = 5 V ± 5%` reports `0 V  -0.5 V … 0.5 V`, i.e. the documented
conservative width. Two `±` on one assignment is refused
(`only one ± tolerance is allowed per assignment`).

*Units* — every "Write / Not" row behaves as documented: `2 W/in^2`, `9.81 m/s^2`,
`47 uF`, `N·m`; `2 W / in^2` and `47 micro farad` do not parse as one unit. `µ`,
`μ` and `u` all work as micro; `Ω` and `ohm` both work. `mil` and `mils` both
display as `th`; `thou` does too. `thou`, `degC`, `delta_degC`, `dBm`, `ppm`,
`uF`, `uH`, `GHz`, `mAh`, `oz`, `ohm` and `kWh` all evaluate; `1 AWG` is
`unknown unit 'AWG'`. `units.aliases: {sq: inch**2}` works (`2 sq` → `2 in²`).
Brackets escape a unit: `0.5 [h]` and `2 [N*m]` both evaluate, and bare `1 N*m`
is read as `N` times a variable, which is why the brackets exist. A variable named
`A` colliding with the ampere is a warning with the documented wording,
`1.2 [A]` silences it, and `5 W/h` is never flagged even when `h` is a variable.
Whitespace around `|` is optional (`P2 = V_out / I_load   |W` evaluates).

*Unit assertions* — `declared as W but the expression evaluates to V/A` is the
real message. Assertions do pin the display unit where that means a scale change:
`0.2366 W/in^2 | mW/in^2` renders `236.6 mW/in²`, and the page's
`P_dens = … | W/in^2` example renders `0.2366 W/in²` as it says.

*Retired spelling* — `P : W = 3 V / 1 A` is refused with
`the 'name : unit = expression' spelling was retired -- write `P = 3 V / 1 A | W`;
run 'refdes calc-rewrite' to fix a whole project`, and `refdes calc-rewrite --help`
confirms every property the page attributes to it (transactional, result and unit
compared before and after, hashes carried across baselines, sealed append-only
entries listed and left alone).

*Functions* — `sqrt`, `abs`, `min`, `max`, `exp`, `ln`, `log10` all work;
`exp(1 V)` is refused (`exp() needs a dimensionless argument, got V`); `sin` is
refused with exactly the documented list
`unknown function 'sin'; available: abs, exp, ln, log10, max, min, sqrt`;
`sqrt()` and `sqrt(1, 2)` are both refused.

*Project equations* — `equations:` in `refdes-project.yaml` works, `note:` is
accepted and read by nothing at build time, `± 15%` on a call site propagates, a
dimensionally wrong argument is refused at the call site, arity is checked with
exactly `current_limit() takes 3 argument(s) (K, V, R), got 2`, redefining `sqrt`
is refused (`'sqrt' is a built-in function; a project equation cannot shadow it`),
and an equation cycle is reported as `equation cycle: loop_a -> loop_b -> loop_a`.

*Inline references* — the page's rendered example is exact: `{{P_diss}}` over
`{{A_board}}` gives `The converter loses 0.2981 W over 1.26 in² of board.`, and
`{{P_diss | mW}}` gives `298.1 mW`. A wrong-dimension unit is a build error and the
reference is left as written; an unknown name warns and is left as written.

*Error list* — `unknown unit 'wat'` and `exponent must be dimensionless` (via
`2 m ** V`, since `**` is the power operator) are both real and reachable.

### Discrepancies fixed

1. **"cannot divide by a value whose tolerance range includes zero"** in the
   "Errors you will see" block. Running `u = 1 / 0` produces
   `calc 'u': division by a value whose tolerance range includes zero` — no
   "cannot". `src/refdes/calc.py:95` carries the message without it. Dropped the
   stray word.

2. **The display-units table's numbers do not follow from its expressions.**
   `volt * ampere` evaluates to `1 W`, not `3.96 W`; `millivolt / ampere` to
   `1 mΩ`, not `41.67 mΩ`; `1 / microsecond` to `1 MHz`, not `454.5 kHz`. All
   three were run; the rendered results are as above. Corrected the right-hand
   column to the values the left-hand column actually produces.

3. **"`min` and `max` take two or more"** — they take any number. `min(1)` and
   `max(1)` both evaluate to `1`; `src/refdes/calc.py:147-154` defines both as
   `*vs` with no arity check at all, unlike `sqrt`, which is checked. Changed to
   "any number of arguments".

4. **"Pin it with `tq = ... | N*m`"** for the torque limitation. It does not work:
   `2 N·m`, `2 N·m | N·m`, `2 N·m | N·m` and `2 [N*m] | N*m` all render `2 J`.
   The same is true of `1 V·A | V·A`, which still renders `1 W` — an assertion pins
   a *scale* (`0.2366 W/in^2 | mW/in^2` → `236.6 mW/in²`) but does not stop the
   compound-to-named collapse. The sentence promising a pin was removed; the
   sentence after it ("none solve it without a separate notion of quantity kind")
   is the accurate part and was left alone.

### Source bug found, reported, not fixed

`refdes build` crashes with an uncaught `TypeError` on a calc line whose result is
complex. Minimal repro, in any project:

```
---
type: decision
id: DEC-SQRT-001
title: sqrt of a negative
---

```calc
v = sqrt(-1)
```
```

```
File "src/refdes/build.py", line 1206, in _run_item_calcs
    line.result = calc.format_value(outcome.value, project.sigfigs)
File "src/refdes/calc.py", line 813, in format_value
    return format_quantity(value.nom, digits)
File "src/refdes/calc.py", line 802, in format_quantity
    return _sigfig_str(float(q.magnitude), digits)
TypeError: float() argument must be a string or a real number, not 'complex'
```

pint happily produces a complex quantity for `sqrt(-1)`, and `format_quantity`
assumes a real magnitude. Every other dimensional mistake in the language is a
clean `CalcError` at the referring line — `docs/math.md` states "There is no path
by which a dimensional mistake produces a number" — so a traceback here is both a
crash and a gap in that promise. Not fixed, per the task's no-source-edits rule.

### Unverifiable here, left as-is

`refdes fetch --update` against a *remote* citation (re-resolving every section an
item cites for that path, including items outside the run's `--item`/`--path`
scope, and the "the section you cited no longer exists in the new revision (was
page N)" line). Those need a second revision of a real datasheet, which this
environment cannot produce. `source()` "is not callable from a project equation"
was likewise not exercised. Left as written.

## docs/links.md

### Claims checked

*The standard-library vocabulary* — every row of the "Starter link types" table
was read off `refdes new <type>` for all seven types (the resolved-schema view,
`# <verb>: []  # target: …`): `refines` on requirement→requirement and
bound→bound, `derives_from` on bound→[requirement, bound], `governed_by` on
requirement→[requirement, bound], `satisfies` on decision and component→
[requirement, bound], `constrained_by` on decision and component→[bound],
`verifies` on test→[requirement, bound], `selects` on decision→component,
`addresses` on log→[requirement, bound], `amends` on log→log, `records` on
log→decision, `supersedes` on decision→decision, `blocked_by` on
decision→any, `part_of` on requirement/bound/decision/test/component→group,
`drop_in` and `alternate` on component→component. Every row of the table is
correct.

*Inverses* — built a project exercising all fifteen verbs and read the
`Incoming` column off every generated item page: `refined_by`, `derived_by`,
`governs`, `satisfied_by`, `constrains`, `verified_by`, `selected_by`,
`addressed_by`, `amended_by`, `recorded_by`, `superseded_by`, `blocks`,
`contains`. Every inverse in the table is correct.

*The self-inverse merge* — a component's page carries one
`<ul class="tight self-inverse">` listing `Drop-in: CMP-019` and
`Alternate: CMP-021` with `Outgoing: None.` and `Incoming: Nothing links here.`,
i.e. the declaration and the computed backlink are merged into one list rather
than shown twice. Repeating the same target twice
(`drop_in: [CMP-014, CMP-014]`) de-duplicates to one visible entry with no
diagnostic.

*`refdes schema --graph`* — writes plain `<svg>` to stdout.

*Vocabulary page graph* — `vocabulary.html` opens with an inline `<svg>`, and
there is no `<script>` inside the SVG block.

*Link and status disagreement* — DEC-003 `supersedes:` DEC-002 while DEC-002 is
`accepted` warns with exactly the documented sentence
(`supersedes DEC-002, but that item's status is 'accepted', not 'superseded' --
the link does not move a status on its own. Set DEC-002's status to
'superseded', or remove the supersedes link if it is not true.`), and a
`selected` component nothing selects warns with the documented
`status is 'selected' but nothing selects it` line.

*The `blocked_by:` cascade* — `refdes audit` prints a `Blocked chains:` section
with one line per resolved chain and staleness flagged inline; a two-hop chain
renders in full (`DEC-IO-016 <- DEC-IO-003 <- DEC-IO-001 (accepted, root)`), not
collapsed; the blocked item's own page carries a `<section class="blocked-chains">`
panel. The stale-blocker `info` matches the documented text exactly and is hidden
by default (it appears under `refdes check -v`, not plain `refdes check`). A
`blocked_by` cycle is a hard build error naming the whole cycle.

*Target restrictions* — `drop_in: [REQ-PWR-002]` on a component is a build error
(`drop_in may point at ['component'], but … is a requirement`); `alternate:`
without `rationale` is a build error citing `required_when: {'links':
'alternate'}`; a link to a nonexistent item is a build error.

*Version claims* — in a `standard: {base: hardware, version: 1}` project,
`part_of` is `unknown field 'part_of' on component` and there is no `group` type,
while `equivalent:` builds; `equivalent: [CON-PWR-002]` (a constraint, not a
component) also builds clean, confirming the "empty target list reads as
unrestricted" note. `refdes standard upgrade --to 2` on that project refuses and
rolls back, naming the offending link
(`rewritten project has build errors -- rolled back: … equivalent may point at
['component'], but BND-PWR-002@… is a bound`).

*Composite expansion* — `refdes ls` expanded a bare `satisfies: [REQ-PWR-002]`
to its composite; `--no-write schema` left it bare; the next writable `build`
froze it.

*Cross-references in prose* — a bare ID autolinks, a token that merely looks like
an ID (`MIL-STD-810`, `DO-254`, `LTC3388-1`) stays plain text, and a backticked
one stays plain too. `[[DEC-B-001#calc:second]]` links to the block's table;
`[[DEC-B-001#calc:nope]]` warns naming the blocks that do exist; a bare
`[[DEC-B-001#second]]` warns that type `decision` declares no field `second`.

*Hover previews* — the preview payload is inlined in
`<script id="preview-data" type="application/json">`. A `types: {bound: {preview:
[status, limit, rationale]}}` overlay demonstrably changes which fields appear
there (`status`, `limit`) against the standard's own `status`, `title`, `limit`.
`app.js` wires `focusin`/`focusout` and Escape.

### Discrepancies fixed

1. **Two dead heading anchors.** `see [below](#governed-by-vs-refines-vs-constrained-by)`
   and `see [below](#blocked-by-and-the-cascade-report)` both point at headings
   whose GitHub slug keeps the underscore
   (`### \`governed_by\` vs. \`refines\` vs. \`constrained_by\`` and
   `## \`blocked_by:\` and the cascade report`). The second is the same slug the
   previous audit corrected `coverage.md` to use, so the page was also
   internally inconsistent. Both anchors corrected.
2. **"the six standard types"** → seven. `refdes new --list` and the resolved
   schema both show seven types at `hardware@3`; the page's own table two
   sections down names `group` as one of them.
3. **"`follows:` today is an unknown-link error."** It is a warning. Running
   `follows: [LOG-PWR-000]` on a `decision` in a `hardware@3` project gives
   `WARNING items/…:2 [DEC-FOL-001] — unknown field 'follows' on decision.` and
   `refdes build` exits 0. Reworded to say what a reader actually sees. (Note:
   `changelog.d/follows-docs-honesty.fixed.md`, already merged, and
   `docs/design-log.md`, owned by another worker, carry the same wrong wording.)

### Unverifiable here, left as-is

The `coverage.html` sentence under "Three existing surfaces" — whether a
`claimed` item whose claimer is blocked gets the grouping summary. Reaching it
needs a requirement in a `claimed` stage, and `coverage.md` (which owns that
wording) was already audited and merged in the previous pass. The claim is a
pointer to that page, whose link resolves.

## docs/blocks.md

### Claims checked

*Registry* — `_REGISTRY` in `src/refdes/blocks.py:855` holds exactly
`calcblock`, `compare`, `index`, `cascade`, `tree`; the page's family is
accurate.

*Scope* — a `{{…}}` directive in an item body is left as literal text
(`<p>{{index by=&quot;status&quot; type=&quot;decision&quot;}}</p>`) with no
diagnostic, and a ```` ```calc ```` fence on a page renders as literal code. Both
halves of "neither is legal in the other kind of document" hold.

*`{{index}}`* — one `<h4>` per distinct `by` value with a two-column ID/Title
table beneath, items ID-sorted within a group, and `(unset)` last. A list-valued
field indexes under every value. An `enum` field orders groups by its declared
`choices:` (decision's `proposed, in_progress, accepted, on_hold, rejected,
superseded` rendered as proposed, accepted, on_hold — not the lexicographic
accepted, on_hold, proposed). An imported item is never listed. `by` restricted
to `text`, `enum`, `date`, `person`, `list`, `quantity` exactly as the table
says (`'checks' is type 'checks', not a groupable field. index supports text,
enum, date, person, list, and quantity fields.`). `subtypes` defaults to
`coverage.group_inherited` (true) and lists a subtype item marked
`(power_decision)`; `subtypes="false"` lists `decision` alone. `tag=` and
`board=` validate against real tags and boards.

*`{{cascade}}`* — the walk resolves transitively, marks a revisited node
`(already shown above)`, and renders a root with nothing to show as
`nothing found (direction="up")`, not an error. `direction`, `depth` (positive
integer, default 3) and `via` all validate; `via` names link *types*
(`satisfied_by` is refused with `unknown link type 'satisfied_by'. Did you mean
'satisfies'?`). The default `via` walked nothing from a log entry with
`addresses`/`records`/`amends` and nothing from a decision with `supersedes`,
while an explicit `via="addresses,records"` walked both — exactly the documented
exclusion set.

*`{{tree}}`* — `<details>` based, no JavaScript, `depth="1"` closes the deeper
levels and the default opens two, `via=` is refused as the unknown parameter it
is (`unknown parameter 'via'. tree accepts: board, workspace, depth.`), and a
board with `includes: [GRP-001]` shows `0 own, 2 shared` with members marked
`(shared, via GRP-001)`.

*`{{calcblock}}`* — renders the owner's own table with the same anchor, caption
and rows, under a caption line naming the linked owner and the block. All six
documented failure modes were reproduced verbatim, including the two distinct
"no calc blocks" / "calc blocks but none is named" messages and the
imported-item refusal. Every failing directive renders `<p class="block-error">⚠ …</p>`
in place while the build exits nonzero.

*Unknown name* — `{{TBD}}` is left completely untouched.

### Discrepancies fixed

1. **"A separate, not-yet-implemented feature … walks `blocked_by:` links".** It
   ships. The same page's later section calls its three surfaces existing, and
   running the tool confirms all three: `refdes audit` prints `Blocked chains:`,
   the blocked item's page carries a chain panel, and the stale-blocker check is
   an `info`. Dropped "not-yet-implemented".

### Source bug found, reported, not fixed

`{{tree}}` on a narrative page emits broken HTML — one nested anchor per item:

```html
<a class="ref" href="bnd-pwr-001.html" data-ref="<a class="ref" href="bnd-pwr-001.html" data-ref="BND-PWR-001">BND-PWR-001</a>"><a class="ref" href="bnd-pwr-001.html" data-ref="BND-PWR-001">BND-PWR-001</a></a>
```

The whole tree is `<a>`-wrapped `<a>`s, with an `<a>` sitting inside the outer
element's `data-ref` *attribute value*. Repro: any project, a narrative page
containing `{{tree}}`. In a 35-item project every one of the 35 items rendered
this way; `{{index}}`, `{{cascade}}`, `{{compare}}` and `{{calcblock}}` on the
same page are clean, and the standalone `tree.html` is clean too. The cause is
that `_render_tree` (`src/refdes/blocks.py:512`) reuses
`tree_mod.render_tree_html(...)`, which already emits the finished
`<a class="ref" …>` markup for the standalone page; when that markup is spliced
into a narrative page, the page's reference linkifier walks the result and
re-wraps every item id it finds — including the ones already inside an anchor.
`docs/blocks.md` and `docs/output.md` both promise the block is "the same forest"
and "the same view as `tree.html`", so the page is right and the renderer is not.
Not fixed, per the task's no-source-edits rule.

### Left as-is, judgement call

"`board=` / `workspace=` narrow the forest to one scope … At most one of the
two." Giving both is *not* refused; the workspace wins and the board is ignored
silently. The sentence reads as guidance to the author rather than a promise of
validation, so it is not strictly false, but it is the kind of line a reader
could take the wrong way. Left unchanged rather than reworded on a judgement
call.

## docs/pages.md

### Claims checked

*Pages-only project* — built one (`.scratch/docsite`, `site.pages: pages`, no
items): `0 items`, and `_site/` contains only the four pages plus `assets/` and
`.refdes-manifest.json`. No `coverage.html`, `log.html`, `document.html`,
`summary.html` or `items.json`. The nav shows only the pages.

*Front matter* — no front matter needed; the title comes from the first `#`
heading (`index.md` → "Index", `alpha.md` → "Alpha page"). `order: 5` and
`order: 50` sort the unlisted pages after the two named in `site.nav`;
`nav: false` keeps `hidden.html` out of the sidebar while still rendering it.

*Contents list* — a page with more than two `##` headings gets
`<aside class="page-toc">`; `alpha.md` (three headings) has it, `index.md` (two)
and `zebra.md` (one) do not. `.page-toc` is `position: sticky`.

*Page-to-page links* — `[Alpha](alpha.md)` becomes `<a href="alpha.html">`; a
link to a page that does not exist is left as `nope.md`.

*Board and workspace grouping* — with a `boards:`/`workspaces:` registry, a page
tagged `board: power` joins that board's group alongside its reports, and a page
tagged `workspace: rev-b` joins the workspace group. The board group rendered
`Summary`, `Coverage`, `Full record`, `Tree`, and gained `Design log` once the
board had a log entry of its own — which is the "only the reports that have
something to show" rule.

*Item dashboard* — with both pages and items, `index.html` is the page and the
dashboard moves to `items.html`.

*Calc blocks* — a ```` ```calc ```` fence on a page renders as literal code.

### Discrepancies fixed

1. **The on-page contents list does not highlight as you scroll.** The page says
   it "highlights the section currently in view as you scroll". `app.js` runs an
   `IntersectionObserver` scroll-spy, but it is wired to
   `document.querySelectorAll(".doc-item")` / `".toc a"` — `document.html`'s own
   contents — and there is no `.page-toc` reference anywhere in `app.js` or in
   `style.css`'s highlight rules. The list is sticky and every anchor works; the
   highlight is a `document.html` feature. Clause removed.
2. **"A schema block is still required by the config format, even when nothing
   uses it."** It is not required. Renaming the pages-only project's
   `refdes-schema.yaml` out of the way and rebuilding is clean
   (`0 items, 0 errors, 0 warnings`), and `AGENTS.md` says outright that
   "`refdes-schema.yaml` is optional … most projects never have one". The
   example above it still shows a schema block, which is fine as part of a
   working example. Sentence removed.

## docs/output.md

### Claims checked

*The site file list* — every entry exists in a full project: `index.html`,
`summary.html`, `coverage.html`, `log.html`, `references.html`, `parts.html`,
`document.html`, `tree.html`, `vocabulary.html`, `<id>.html`, `items.json`,
`assets/`. `assets/theme.css` appears only once a theme is configured. `log.html`
sorts oldest first (2026-01-01, 2026-01-02, 2026-02-01).

*Per-board and per-workspace pages* — with a `boards:` registry the power board
got `document-power.html`, `coverage-power.html`, `summary-power.html`,
`tree-power.html` immediately, `log-power.html` once it had a log entry,
`references-power.html` once it had a citation, and `parts-power.html` once it
had a `part_number` — i.e. the "only the reports that have something to show"
rule. A registered board with no items got no pages at all.

*Key collision* — a board and a workspace both named `shared-key` is refused at
load with exactly the documented reasoning
(`'shared-key' is declared as both a board and a workspace -- boards and
workspaces share one namespace for generated report names`).

*Margins* — all four rows of the table reproduce. `<= 0.15 W/in^2` against
`0.10 W/in^2` gives `0.3333…` (+33.3%); against `0.2366 W/in^2` gives
`-0.5773…` (−57.7%); `>= 0.90` against `0.93` gives `0.0333…` (+3.3%);
`9 V .. 36 V` against `35 V` gives `0.0370…` (+3.7%). The three `—` cases
reproduce too: `== 5 V`, and `<= 85 degC` (a one-sided comparison against an
offset temperature unit) both give `margin: null`, while `<= 350 K` gives
`0.1428…` and `0 degC .. 60 degC` gives `0.25`. `summary.html` renders the
table tightest-first. `items.json` carries `checks[].margin` as a fraction.

*`items.json`* — top-level keys are `boards`, `coverage`, `diagnostics`,
`items`, `next_ids`, `title`, `types`, `version`, `workspaces`. A coverage entry
is `{stage, addressed_by, claimed_by, satisfied_by, verified_by}` with the
documented `stage` value. `calcs[].bounds` is empty without a tolerance.
`citations` is keyed by field name and every entry has `path`, `state`,
`pinned`, `kept_copy`, `sha256`, `fetched`, `local_path`, `section_page`,
`detail`; `fields.citations` holds the authored intent alone. `external`,
`origin`, `former_ids`, `source.file`/`.line` and `content_hash` are all
present. `types[].fields[].type` is there, so a consumer can find a citations
field without being told.

*Item page* — type badge, ID, check state, a coverage strip on a requirement
(`satisfied / addressed / claimed / satisfied DEC-SAT-001 / verified`), a field
table with each field's `on_change` mode, the body with calc tables and
autolinked IDs, a checks table with pass/fail and worst-case detail, a
citations table, a traceability section with Outgoing/Incoming, and provenance
carrying `items/…:2` and the content hash. An imported item's page is stamped
`imported from platform`; a log entry's page carries `append-only`.

*Theming* — `site.theme: paper` + `site.tokens:` writes `assets/theme.css`,
linked after `assets/style.css`; a bare `--token` pair lands in `:root` and is
re-asserted inside the dark blocks; a `[data-theme="dark"]` block is emitted;
`theme: default` writes no file and emits no `<link>`. An unknown theme name is
`site.theme 'papr' is not a theme. Available themes: default, high-contrast,
paper, slate. Did you mean 'paper'?`; an unknown token name is
`is not a design token` and a near-miss gets `Did you mean '--accent'?`; a value
containing `;` is refused. A low-contrast override warns per pair
(`--accent on --bg is 1.41:1, below the 4.5:1 WCAG AA minimum`) and the build
still produces the site.

*Site navigation* — `aria-current="page"` on the current page; the sidebar
groups are `<details>` (open for the group the current page lives in, closed
otherwise); the narrow-viewport toggle is a checkbox + `<label>☰ Navigation</label>`
with `.sidenav-toggle-input:checked ~ nav` in the stylesheet and no script in
the sidebar at all.

*`document.html`* — every item as a section, grouped by type in schema order
(requirements, then bounds, then decisions); 76 cross-references rewritten to
`href="#…"` against 1 unrewritten (the nav link); the print stylesheet hides
the sidebar and sets `.doc-item { break-inside: avoid }`.

*Static site* — the only `https://` URL in the whole rendered output is the
`https://example.com` link I authored in a test body.

### Discrepancies fixed

1. **The `site.tokens:` example is refused by the loader.** It mixes a bare
   `--accent:` pair with `light:`/`dark:` headings; running it gives
   `configuration error: refdes-project.yaml: site.tokens.--accent is not valid
   here. A tokens: block that uses the light and dark headings may contain only
   them; a bare --token pair applies to both palettes.` The example was reduced
   to the bare-pair form, and the rule the tool actually enforces was added to
   the paragraph below it.
2. **The on-page contents list does not highlight as you scroll** (same
   underlying finding as `pages.md`). Reworded, and the scroll-spy attributed
   to `document.html`.

## docs/themes.md

### Claims checked

*The gallery* — the four built-ins are exactly `default`, `high-contrast`,
`paper`, `slate`, taken from the loader's own list
(`site.theme 'papr' is not a theme. Available themes: default, high-contrast,
paper, slate.`).

*The token tables* — these are generated, and the page says so with a test to
back it. `python -m pytest tests/test_themes_page.py -q` passes (7 tests), so
every value in all three tables equals what `refdes.theme.BUILTIN_THEME_LIST`
produces today. `python -m pytest tests/test_theme.py -q` also passes (55 tests),
which is the `check_builtin_themes` non-warning path the page describes.

*`default`* — `theme: default` writes no `assets/theme.css` and emits no
`<link>`, exactly as the section says (twice).

*`assets/theme.css` shape* — a bare token pair lands in `:root` and is re-asserted
inside `@media (prefers-color-scheme: dark)` and `[data-theme="dark"]`, so a
light-only override cannot bleed into dark mode.

*Value validation* — every documented refusal reproduced: a bare `--` token
name, an empty value, a `{` brace, `<` (which catches `</style>`), `url(`,
`expression(`, and a value over 200 characters. Non-hex values (`red`,
`rgb(1,2,3)`, `var(--fg)`) are accepted and produce no contrast warning, i.e.
skipped by the checker rather than guessed at.

*Contrast* — a failing pair is a warning naming the pair, the two values and the
measured ratio, and the build still produces the site.

### Discrepancies fixed

1. **The "Writing your own" example is refused by the loader**, for exactly the
   reason `output.md`'s identical example is: a bare `--accent:` pair mixed with
   `light:`/`dark:` headings. Split into two separate examples — one bare pair,
   one `light:`/`dark:`-only — with a sentence saying that mixing them is a
   load-time error, so an author never has to guess which override won.

### Left as-is, judgement call

`site: theme:` and `site: tokens:` in the opening paragraph are inline prose
shorthand for `site:` / `theme:`; the YAML blocks lower on the page are correct.
Not worth reformatting.

