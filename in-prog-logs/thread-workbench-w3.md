# Thread workbench W3 ("values") — notes

Scope per docs/design/thread-workbench.md §8: D1 inline calc values
(pane-only per §7.1) + a show-values toggle on calc tables. Response-only
decoration per §3.3/§4, exactly as W1/W2 established.

## This pass found W3 already shipped — so it verified rather than rebuilt

`git log` on this branch (fresh off `origin/main`): W3 landed as `99eabcd`
"feat(serve): inline calc-value attributions and values toggle (workbench
W3) (#31)", 48 commits back from HEAD. Its pieces are all in the tree:
`serve/server.py::_decorate_calc_values` + `_add_values_toggle` (called from
`_decorate` after `_decorate_images`), the `static/preview.js`
`wireValueToggles` listener, `static/bar.css`'s badge/toggle rules and
`.refdes-values-off`, `tests/test_serve_preview_values.py`, and the fragment
`changelog.d/thread-workbench-values.added.md`. Its implementation log is
`in-prog-logs/wb-w3-values.md`.

Nothing was re-implemented: a second decoration path for the same fact is
exactly the "second compiler" §3.3 rules out. What follows is the
verification, plus the residue this pass closed.

## Verified against the tree, not memory

`.scratch/w3_smoke.py` (kept, per the repo's scratch convention) starts a
real `EditorApp` over a one-item calc project, fetches
`/preview/dec-001.html`, then runs the same sources through
`render.render_site`:

- served: `<code data-refdes-calc="V_in" title="V_in = 12 V (block: supply)">12
  V</code><span class="refdes-calc-attr">V_in · supply</span>` — the badge's
  number is the snapshot's own string (`item.calc_values == {'V_in': '12 V',
  'I_in': '0.5 A', 'P_diss': '294 mW'}` printed in the same run), so the
  decoration shows what the build evaluated, not a recomputation;
- `{{V_in | mV}}` stayed `<code>12000 mV</code>` and the author's own
  `` `not-a-value` `` stayed `<code>not-a-value</code>` — both undecorated;
- two calc tables → two `refdes-values-toggle` buttons, one in each caption;
- the publish side of the same project: `_site/` contains none of
  `refdes-calc-attr` / `refdes-values-toggle` / `data-refdes-calc` /
  `refdes-serve-bar`, and publishes the plain `<code>12 V</code>`;
- `pytest tests/test_serve_preview_values.py tests/test_serve_preview_reload.py
  tests/test_serve_preview_decorations.py tests/test_serve_static.py -q` →
  70 passed before this pass's changes, 12 in the values module after.

## What this pass added

1. `tests/test_serve_preview_values.py`:
   `test_a_real_publish_of_the_same_project_shows_none_of_it` — the §4
   "Never touches `_site/`" invariant checked at the **publish** boundary
   (the existing pair pins the serve generation directory; nothing pinned
   `render_site`'s own output). Same sources on disk, so the contrast is
   served-decorated vs. published-plain, in one test.
   `test_a_calc_table_nobody_cites_in_prose_gets_no_toggle` — pins the
   reading of "a show-values toggle on calc tables" the implementation took
   (see below), which the design doc's wording alone does not settle.
2. `docs/design/thread-workbench.md`: the Status header still said "W3
   ('values') is in progress" three phases after it merged. Corrected to
   name W1–W3 landed with their logs, and §8's bullets marked. A note under
   §5 now records, in the design doc itself, the one place the shipped D1 is
   narrower than its row says (dotted prose mentions) and why.
3. This log, as the W3 entry in the w1/w2 series.

## Decided locally (not blocking, recorded for review)

- **Log naming.** The shipped phase logged itself as `wb-w3-values.md`, not
  the `thread-workbench-wN.md` the series uses. Not renamed — `99eabcd`'s
  commit message cites that path, and rewriting a merged commit's referenced
  file for a filename convention is churn. This file is the series entry and
  points at it instead.
- **Toggle semantics, confirmed as shipped.** The button controls the D1
  attributions page-wide and appears only on a page that carries at least
  one attribution; a calc table with no `{{name}}` cited in prose gains no
  button (there is nothing to hide). The alternative reading — substituting
  values into the tables' expression cells — was rejected in
  `wb-w3-values.md` as inventing a feature §8 never describes, and this pass
  agrees: the tables already print expression and result.
- **Dotted `ITEM.NAME` prose mentions stay undecorated.** `wb-w3-values.md`
  records a review veto on §3.3 grounds (they are not prose syntax, so a
  value beside them would be the pane implying meaning the site does not
  have). This pass did not revisit the veto; it moved the consequence into
  the design doc, where §5's D1 row otherwise reads as if dotted refs ship.
  **Still open for Jared:** make prose dotted refs real site-side syntax
  first? If they do, the pane half is trivial — the targets' `calc_values`
  already exist.
- **Known imprecision, left as documented.** Identification is a parallel
  walk of the body's `INLINE_VALUE_RE` refs against the page's `<code>`
  elements, advancing only on an exact match of the build's formatted value.
  An author's own code span whose text happens to equal the next expected
  value can take the badge, and the real reference then goes undecorated.
  The build destroys the distinction (`{{name}}` becomes `` `value` ``), and
  marking it site-side would change what the published site renders (§9), so
  the pane cannot do better without a site change. The attribution it shows
  is still a real build fact about that item.

## W4 observation (per §7.4, stated plainly)

Nothing cheap and obvious was visible in the W3 touch path; no speculative
optimizations were made. This pass touched no build code at all — one test
module, one design doc, one log.
