# Fix run-14 findings (F14-1..F14-5)

Task: fix the five findings from the run-14 user-simulation release gate
(`origin/user-sim-run14:in-prog-logs/user-sim-release-gate-run14.md`), one
commit per finding, one PR. Red-first tests, docs claims verified by running
the real commands, changelog fragment per user-visible change.

## F14-1 — stale inline-calc span showed raw binary float (commit 1)

Reproduced on main: span `Pin := 4.8 W - 0.4 W | W = 4.3 W` with `sigfigs: 2`
warned `stored result says 4.3 W, now computes 4.3999999999999995 W`.

Red-first tests in tests/test_inline_calc.py:
`test_run14_stale_span_displays_when_the_value_clearly_reads_stale`,
`test_run14_raw_display_is_normalised_not_a_binary_dump`.

Fix in inline_calc.py `_stale_message`: the message previously computed
"inside_window" by interval overlap and then printed the raw pint value.
Replaced with the acceptance test itself (same rounding + tie rule the
acceptance check uses) so the warning fires only when the stored value
clearly reads stale, and added `_clean_raw(dec, cap=12)` (localcontext) so a
displayed value is the decimal the author would write, not a binary dump.
Verified by CLI repro: `4.3999999999999995` -> `4.4`, `3.4495000000000005`
-> `3.4495`. docs/math.md updated with the verified examples. The F12-4 test
(stale display never shows a value that looks accepted) stays green.

## F14-2 — calc fence with K/W unit errors on offset unit (commit 2)

Reproduced: `Rth = 42 K/W` inside a `degC` fence -> pint
`Ambiguous operation with offset unit (degree_Celsius, kelvin)` at
items/log.md:12. The clean form is `42 delta_degC/W` — verified clean
(`1 items, 0 errors, 0 warnings`). Decision: document only, no code change.
Wrapping pint's exception is not a tiny change and the pint message is not
unactionable. docs/math.md gained a paragraph stating the rule: a temperature
rise is `delta_degC` (or kelvin), `K`/`degC` as a divisor unit is an offset
unit and pint refuses it.

## F14-3 — changelog claimed NAVI_MINT_REFUSED appears in the warning (commit 3)

Verified on main: the mint-refusal WARNING prints without the code —
`Diagnostic.__str__` (model.py) formats location/type/message only; the code
reaches JSON via serve/api.py. The fragment
changelog.d/navis-slice-2.added.md said the code "appears in the warning".
Reworded to: the warning carries the NAVI_MINT_REFUSED diagnostic code (the
code field every diagnostic has, machine-readable, exposed in the serve API;
it is not printed in the warning text). Docs-only.

## F14-4 — Navis marker bytes leak into list-page title/summary (commit 4)

Reproduced: an item with a navi marker and no `title:` takes its title from
its body; the marker bytes then re-appear in the list-page summary column,
tree, hover preview and item-page h1 (the one projection that read the raw
body). Red-first test
test_navis.py::test_title_projection_carries_no_marker_bytes (red on main,
green after).

Fix: `Item.title`'s body fallback strips markers via `navis.strip_markers`
(deferred import; strip_markers returns the same object for a marker-free
body). History-disclosure captured-snapshot bodies are left verbatim —
they're the historical record as captured (rendered from the store,
item.html.j2 `<pre>{{ row.body }}</pre>`); docs/markdown.md now names that
single place marker bytes can appear, pointing at the baseline-snapshot-events
anchor. Byte-identity: this repo's own (no-marker) project builds
byte-identical to origin/main — diff -rq of the two _site trees empty, twice.

## F14-5 — picker XLSX endpoint undocumented (commit 5)

Verified: `GET /api/item/<ref>/sources/entries` was named only in
changelog.d/ fragments and design docs; the user-facing picker page
(docs/markdown.md) described the panel without naming it, and
docs/output.md / docs/cli-reference.md don't list serve endpoints at all.
docs/markdown.md's picker section now names all four reads
(sources, sources/entries?path=&q=, sources/propose, the set_body save)
with a real response fetched from a running
`refdes serve --no-open --port 8757` against a CSV-citing project. Field
prose checked against serve/sources.py `_entry_dict`/`entries_payload`.

## Verification

- Red-first for the three code-behavior tests (F14-1 x2, F14-4 x1): shown
  failing against origin/main's src, passing on the branch.
- Full suite: 5567 passed, 2 skipped (11:09).
- ruff on touched files: my added lines introduce no new findings (model.py
  has 3 pre-existing findings on main, unchanged by my edit).
- docs anchors/examples tests: pass.

## Decisions made

- F14-2: document the offset-unit rule; do not wrap pint's message in code.
- F14-3: reword the existing fragment to match actual print behavior; do
  not start printing codes in warnings (the machine-readable field is the
  interface).
- F14-4: strip in the title projection, not in the stored body; leave
  captured snapshot bodies verbatim and fix the docs' "nowhere" claim to
  name that one place.
