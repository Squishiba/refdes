# f16-docs — three run-16 docs gaps (upgrading, cli-reference, navis)

Task: close F16-4 (docs/upgrading.md), F16-6 (docs/cli-reference.md serve
section), F16-1 (docs/navis.md + getting-started.md), docs only, every claim
from a run against this worktree's source. Report read via
`git show origin/user-sim-run16:in-prog-logs/user-sim-release-gate-run16.md`.

Setup: `/home/jorb/work/venv-refdes/bin/python -m refdes.cli` with
`PYTHONPATH=<worktree>/src` (the venv's own refdes is the 0.5.0 wheel —
`--version` proves it, so the absolute PYTHONPATH is load-bearing). Scratch
projects under `.scratch/run16/proj-{a,b,c,d,e}`.

## F16-4 — item-level `history:` hard error (proj-a, hardware@2 pin)

Reproduced: a `log` entry with `history: log` →
`refdes check` prints
`ERROR   items/log.yaml:4 [LOG-PWR-001] — item-level history: was renamed
to on_change: -- rename this key in the source file. Its override is used in
this build so the change policy is not silently lost.` (exit 1). Renaming
`history:` → `on_change:` (v2 pin keeps mode `log`) clears it. With the
error present, `refdes calc-rewrite` refuses:
`project has existing build errors -- fix those first, so a calc that
changes meaning under this rewrite can't hide behind an already-broken
build` — so the report's ordering claim (step 4 refuses while red) holds
(verified with a colon-unit calc in the same project).

Docs change: added the error to step 2's error block with the one-line fix,
and the calc-rewrite consequence, quoted verbatim from the run.

F16-4 remedy follow-on (proj-b, hardware@3 + copied design-debate preset
from the source v2 preset into `refdes-schema.yaml`): both refusals
reproduced. First
`configuration error: types.debate.fields.chat_id: on_change mode 'log' was
renamed to 'timeline' -- the mode marks a change for the future field-level
timeline, not the \`log\` item type; rename it` (exit 2); after renaming it,
`configuration error: types.debate.links.resolved_by names target type
'decision', which is not declared (removed by an override?)` (exit 2);
`resolved_by: [log]` loads green. Added to the `decision`-retired table row
(quoting the message fragments).

## F16-6 — serve task-pane passage (proj-d: 2-entry thread, tip carries a
declared task list; real `refdes serve` on ports 8891 writable / 8892
`--no-write`, curl with the launch-token cookie)

- Writable preview page (`/preview/log-002.html`): carries
  `class="refdes-taskpane-tick"` checkboxes, loads
  `taskpane-ticks.js`, pane has the Tasks toggle. The module carries
  verbatim: `Preview: ticking a row changes this page only -- nothing is
  saved.` and wires sessionStorage (per-tab draft), a `Discard` button, a
  status count, and a `beforeunload` prompt; its header comment states the
  save is W5b.4c-2, "so there is no request here".
- `--no-write` preview page: Tasks toggle present, ZERO tick checkboxes,
  ZERO ticks-module tag — the read-only pane, exactly as built.
- `refdes build` → `_site/log-002.html`: same (toggle, no checkboxes, no
  module).

Save-UI check for the sentence's wording: `git log origin/main --oneline`
has W5b.4c-2a (#468, request/response logic, "nothing visible yet") and
W5b.5 (#470) but NO `save UI` / W5b.4c-2b — so "nothing is saved to the
project from the pane yet" is true as written; re-check before the PR.
Not documented: Save button / conflict panel (in review). Not browser-driven
this session: the draft/Discard/prompt claims come from the shipped JS the
server served (grep of `taskpane-ticks.js` above), not from a click.

## F16-1 — navis scan needs an id (proj-c + proj-e)

proj-c: marker in a body of an id-less `log` item + marker in an id-bearing
sibling. `refdes navis ls` / `navis all` list only the id-bearing marker;
`refdes index`'s `navis` key holds only it; `refdes build` publishes a panel
whose rows contain only the id-bearing text. `refdes id` →
`allocated LOG-003`, and the same `navis ls` then lists the formerly invisible
marker (and mints its key). proj-e re-ran getting-started's exact flow
(requirement written with `body:` prose containing a marker, no `id:`):
`navis ls` → `no Navis: ...`; after `refdes id` → listed. Mechanism noted in
the report (load-block excludes id-less items); docs state the observable
only, per task. No code touched.

Docs change: navis.md "The CLI" (where the scan/list is described) states
the id rule and names `refdes id` as the minter; getting-started.md gets one
sentence at the `refdes id` step.

## Runs

- `docs-site/gen_examples.py --check` → up to date, exit 0.
- `refdes build` in docs-site → 0 errors, site written.
- `pytest tests/test_docs_anchors.py tests/test_crossplatform_lint.py` →
  28 passed.
- Full suite: see below (run once).
- Servers stopped by the PIDs started (8891/8892 killed; token files
  removed on clean stop).

## Not verified

- Pane click behaviours in a real browser (no browser driven this session;
  claims limited to the served markup + shipped JS, quoted above).
- The 0.5.0 wheel end-to-end probe (used a v2-pinned project with the
  0.5.0-era key spellings; the item-level `history: log` reproduction is the
  current build's, which is what the docs quote).
