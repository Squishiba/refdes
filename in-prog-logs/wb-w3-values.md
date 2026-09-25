# Thread workbench W3 ("values") — CHUNK 1 investigation + plan

Scope per docs/design/thread-workbench.md §8: D1 inline calc values
(pane-only per §7.1) + a show-values toggle on calc tables. Response-only
decoration per §3.3/§4, exactly as W1/W2 established.

## What prose value references exist today (verified by running a real build,
## `.scratch/w3_probe.py`, not memory)

1. **`{{name}}` inline calc value** — `build.INLINE_VALUE_RE` (bare name,
   optionally `| unit`), substituted in `build.render_bodies` via
   `_inline_value_replacer` *before* markdown sees the text.
   - Published page renders it as `` `value` `` → `<code>12 V</code>`.
     **The value IS on the published page; the name is destroyed.**
   - `{{name | unit}}` converts via `calc.convert_value(item._env[name], unit)`
     at build; the converted string is stored nowhere — only `calc_values`
     (name → formatted nominal) survives.
   - A `{{name}}` that names nothing warns and stays literal text.
   - `{{...}}` inside a calc fence is also substituted, but the fence is then
     replaced by the table placeholder, so that substitution never reaches
     the HTML — a refs scan must exclude fences or the ordering skews.
2. **Dotted `ITEM.NAME` references** — real only *inside calc blocks*
   (`calc.CROSS_REF_RE`), where the table already shows expression + result.
   In **prose** they are not a supported syntax:
   - bare `DEC-001.V_in` in prose → `BARE_REF_RE` linkifies the ID half, so
     the page shows `<a class="ref" ... data-ref="DEC-001">DEC-001</a>.V_in`.
     **No value is shown anywhere at the use site.**
   - `{{DEC-001.P_diss}}` does not match `INLINE_VALUE_RE` (bare names only);
     it survives as literal text with the ID half linkified:
     `{{<a ...>DEC-001</a>.P_diss}}`. (named-calc-blocks §4.3: this spelling
     is deliberately not added to the site; D1 is where prose dotted values
     were punted to.)
   - The cross-item expr cell of a calc table is *also* linkified (tables are
     injected before `_linkify`), so a dotted matcher must skip
     `<table class="calc">` regions — those rows already show the result.

## What D1 adds beyond the published page (the delta — it is not nothing)

- **Name attribution at `{{name}}` use sites.** The site shows the number but
  not which calculation it is; the pane adds the name beside the value
  (D1: "name as attribution"), plus the owning **block name** for free via
  `CalcLine.block` (named-calc-blocks §5.5: "which named calculation a value
  came from, beside the value itself ... No new mechanism").
- **The value at dotted `ITEM.NAME` prose use sites.** The site shows no
  number there at all; the pane appends the target's already-computed value.
- Both are overlays: text unchanged, spans/attributes added, stripped at
  publish (response-only, like the toolbar/W1 probe/W2 decorations).

## Which existing Python data supplies it (nothing is re-evaluated)

- `item.calc_values` — name → formatted result string, built in
  `build._run_item_calcs` (`item.calc_values[outcome.name] = line.result`).
- `item.calcs` (`CalcLine`) — `.name`, `.result`, `.block` for attribution.
- `project.item_by_id(ref)` → target's `calc_values` for dotted references.
- `build.INLINE_VALUE_RE` / `BARE_REF_RE` shapes, reused for matching.
- **Never used:** `item._env`, `calc.convert_value`, any evaluator. Unit-
  converted `{{name | unit}}` references are *not decorated* — their rendered
  text is a build-time conversion that is stored nowhere, and recomputing it
  would be re-evaluation, which W3 forbids. Stated limitation, not papered.

## How it is stripped / absent on the published site

Identical boundary to W1/W2: decoration happens in `serve/server.py::_decorate`
on the HTTP response only. The generation directory on disk (what a publish
would look like) and `_site/` never contain it. Pinned by a test that walks
the generation tree asserting no W3 markers, plus a before/after tree-hash
test proving serving a decorated response leaves every file byte-identical.

## Orchestrator review of this plan (refdes-2)

- Toggle interpretation: OK as decided above.
- **Vetoed: decorating dotted `ITEM.NAME` text in prose.** It is not a
  supported prose syntax, so showing a value there would make the pane imply
  meaning the site does not have (§3.3: additive only, never a second
  interpretation). D1 is scoped to `{{name}}` inline values only.
- **Open question recorded for Jared:** should prose dotted refs
  (`DEC-001.V_in`, or the `{{DEC-001.P_diss}}` spelling authors reach for)
  become real syntax site-side first? If they do, the pane decoration for
  them is trivial (target's `calc_values` already exist). Until then the
  pane stays silent on them.

## Implementation (CHUNK 2, as revised by the review)

`serve/server.py` — new `_decorate_calc_values(page, item)` called
from `_decorate` after `_decorate_images`, before the bar/panel are appended:

1. **Inline attribution (the only decoration).** Scan `item.body` with
   `INLINE_VALUE_RE` (fences removed via `calc.CALC_BLOCK_RE.sub("", body)`
   first, mirroring the build) for bare-name refs whose name is in
   `calc_values`, in order. Walk the page's `<code>` elements in document
   order with a pointer: decorate only when the code element's inner text
   equals the html-escaped expected `calc_values[name]` (author code spans
   that don't match are skipped, the pointer never advances on them).
   Decoration: `data-refdes-calc` + `title` on the `<code>` tag and a
   visible `<span class="refdes-calc-attr">name · block</span>` badge after
   it (badge skipped inside `<pre>`). Known limitation (documented): an
   author code span whose text coincides with the current expected value can
   be decorated; the shown value is still a real build fact.
2. **Show-values toggle on calc tables** (§8 W3). Interpretation decided
   locally: the toggle shows/hides the D1 decorations page-wide, and lives on
   each calc table (the design's stated location; the D1 badges are the only
   values the pane adds). Injected response-only into each table's caption
   (a caption is synthesized for unnamed blocks): `<button class=
   "refdes-values-toggle" aria-pressed="true">values</button>`. Wiring in
   `static/preview.js` (module, `script-src 'self'`, no inline handlers —
   `addEventListener` only), visibility via `bar.css`
   (`.refdes-values-off .refdes-calc-attr { display: none; }`). Default on.
   Rejected reading: substituting values into expr cells — invents a feature
   the design never describes and does text surgery on linkified cells.
4. **No `?workbench=1` gate**, following the W2 precedent (§7.5 "or a
   toggle"; the served preview *is* the workbench surface; gating forks the
   decoration path for no v1 benefit).

## W4 observation (per §7.4)

Nothing cheap and obvious in the W3 touch path; no speculative optimizations
were made. (The decoration adds two regex scans per served item page; the
build path itself was not touched.)

## Chunk 2/3 results

- `serve/server.py`: `_decorate_calc_values` + `_add_values_toggle`, called
  from `_decorate` after `_decorate_images`. One implementation bug caught
  by the live smoke test: attributes initially landed after the `>` of
  `<code>` instead of inside the tag; fixed.
- `static/preview.js`: `wireValueToggles` (addEventListener only, no inline
  handlers); `static/bar.css`: badge/toggle styles + `.refdes-values-off`
  hiding rule + print suppression.
- Tests: new `tests/test_serve_preview_values.py` (10 tests: named/unnamed
  block attribution, unit-converted ref undecorated, author code span and
  dotted prose mention untouched, no-calc item clean, one toggle per table,
  synthesized caption, generation tree hash identical before/after serving,
  on-disk files free of markers). `tests/test_serve_static.py`: W3 wiring
  check (toggle class in preview.js/server.py, no onclick anywhere).
- Docs: `docs/cli-reference.md` serve section gained a workbench bullet.
- Changelog: `changelog.d/thread-workbench-values.added.md`.
- Gate: `python -m pytest -q -x` -> 2123 passed; `ruff check --select E9,F
  src tests` clean.

## Open question for Jared (from the refdes-2 veto)

Should dotted `ITEM.NAME` mentions in prose become real site-side syntax
first (with `{{DEC-001.P_diss}}` the spelling authors already reach for)?
If they do, the pane decoration for them is trivial — the targets'
`calc_values` already exist. Until then the pane stays silent on them, per
contract §3.3.
