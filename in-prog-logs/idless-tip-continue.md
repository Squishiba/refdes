# idless-tip-continue (finding F16-2, run-16 user-sim)

Task: a preview task pane handed the browser a save context
(`data-refdes-tip-key` + `data-refdes-revision`) for a thread tip that has a
`key:` and no `id:`, but `POST /api/item/<ref>/continue` refuses exactly
such a tip (`links.composite_for(tip)` is None: a composite is
`DISPLAY-ID@key`, both halves required), and the refusal text rendered an
empty subject (`refused:  carries no artifact key` — the double space IS the
missing id). The pane offered a save the endpoint always refuses.

## What was done

1. **Pane gate** (`src/refdes/serve/server.py`, `_pane_save_context`): the
   gate was `tip is None or not tip.key`; now `... or not tip.id`. A tip
   with no `id:` gets no save context, same as a keyless tip: its panel
   keeps W5b.3's checkboxes, names neither attribute, and is preview-only
   through the path `tick-pane.js` `panelFromRows` already spells
   (canDraft=false -> "ticks on this tip are preview-only - nothing is
   saved"). Docstring updated to name the id-less tip as its own arm.
2. **Refusal subject** (`src/refdes/serve/edit.py`): new `_tip_subject(tip)`
   — `tip.id`, falling back to `the tip <key>` for a tip with a key and no
   id. Applied to the `composite_for` refusal and the five sibling refusals
   in `_continue_locked` that share the `{tip.id}`-as-subject pattern:
   ambiguous, undeclared (`{tip.id}'s` possessive), cleared, imported
   (external tip), sealed. Messages for id-bearing tips are byte-identical
   (the helper returns `tip.id`); no existing test text was edited.
3. **Doc line**: `changelog.d/continue-idless-tip.changed.md` — a tip needs
   an `id:` to be continued; the pane offers no save for one; the refusal
   names the key. No docs/ page change: grep found no user doc documenting
   the endpoint or the pane's preview ticks (the serve section of
   `docs/cli-reference.md` documents the site's read-only pane; the
   `refdes thread` CLI docs are the only "tick" hits).

## Red/green

New file `tests/test_idless_tip_continue.py` (3 tests, cold-served project,
two forked-free threads, minted keys authored in; id-less tip on one,
id-bearing control on the other):

- `test_an_id_less_tip_panel_carries_no_save_context` — FAILed red (panel
  carried `data-refdes-tip-key` for the id-less tip), passes green.
- `test_the_endpoints_refusal_for_the_id_less_tip_names_the_key` — FAILed
  red (message was exactly `refused:  carries no artifact key, ...`), passes
  green (key named, no empty subject, bytes untouched).
- `test_an_id_bearing_tip_keeps_its_context_and_its_200` — control: passed
  red (unchanged behavior) and passes green (context present, 200 applies,
  continuation's `follows:` is the composite).

Runs: new file + `test_task_pane_tick_context.py` + `test_task_pane_ticks.py`
+ `test_serve_continue.py` + `test_serve_continue_http.py` +
`test_tick_save.py` + `test_serve_create.py` + `test_crossplatform_lint.py`
(264 passed, -n 4 worksteal); full suite ONCE: 6388 passed, 2 skipped.
`ruff check --select I` on the touched files: clean. pr_size: 33 added lines
under src/.

## Notes

- The fixture needed `keys.mint()`-real keys: an authored malformed key
  (`abc123keyed`, copied from the pane-context test's style) dies at the
  creation gate's corruption lint the moment the save writes a composite
  embedding it — that is the control's 200 path, so the key must be valid.
  The pane tests run cold, where a malformed key is only a load-time lint.
- Out of scope, left alone: the `carries no artifact key` wording of the
  link-verb plan messages (`edit.py` ~1065/~2018/~2046, `_planned_target`
  family) interpolates `{target.id}` the same way and renders an empty
  subject for an id-less link target; the task scoped this fix to
  `_continue_locked`'s refusals. The forked-tips refusal at
  `_continue_locked` already labelled id-less tips (`tip.id or tip.key`) —
  untouched, it shares no pattern with the six fixed here.
- Task finished. Branch `fix/idless-tip-continue` from origin/main (merged
  #472 before commit; first-action merge reported up-to-date, #472 landed
  after it, plain-merged before pushing).
