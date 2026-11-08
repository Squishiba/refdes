# W5b.3 tests: ticks in the pane, serve response only

Started from `ecf8add2` on `feat/w5b3-pane-ticks`. Scope was test-author only:
add `tests/test_task_pane_ticks.py`, no source changes, no PR.

## Contract pinned

The tests pin W5b.3 as a pair everywhere possible:

- `refdes build` keeps the task pane read-only: no task-pane checkbox in the
  pane's control surface, no `taskpane-ticks.js`, no token/write-route text,
  with W5a's glyph and toggle still present.
- `refdes serve` preview responses add the interactive pane controls and the
  response-only module tag.
- The preview generation on disk stays byte-identical to the built pane slice.
  The whole page cannot be byte-identical because preview adds the serve bar
  and draft/banner chrome outside the pane.

Pinned markup:

```html
<label class="refdes-taskpane-tick" for="refdes-taskpane-tick-<tip>-<task id>">
  <input
    type="checkbox"
    id="refdes-taskpane-tick-<tip>-<task id>"
    data-refdes-task="<task id>"
    data-refdes-task-state="<state>"
    data-refdes-tick-states="<comma-separated legal target states>"
    data-refdes-tip="<tip ref>"
  >
  <row text>
</label>
```

Data attributes chosen:

- `data-refdes-task`
- `data-refdes-task-state`
- `data-refdes-tick-states`
- `data-refdes-tip`

Module path pinned:

- `/edit/static/taskpane-ticks.js`
- packaged as `src/refdes/serve/static/taskpane-ticks.js`

Pinned Q6 target sets:

- open: enabled, unchecked, `done,dropped`
- done: enabled, checked, `open`
- dropped: enabled, unchecked, `open`

Pinned Q4:

- an older entry's checkboxes name the tip, not the viewed entry.
- in a fork, each panel's checkboxes name that panel's tip.

Pinned inert cases:

- derived rows have no glyph and no checkbox.
- no-thread pages have no pane and no tick module.
- threads with no declared task list have no checkbox and no tick module.
- `--no-write` serve is pinned conservative: read-only pane only, no
  checkbox, no module. The plan is silent on this exact pane case; the
  writable twin in the same test proves the refusal is the `--no-write` flag.

## Red evidence

Targeted command:

```sh
PYTHONPATH=/home/jorb/.paseo/worktrees/16msma8v/feat-w5b3-pane-ticks/src \
PYTHONDONTWRITEBYTECODE=1 \
/home/jorb/work/venv-refdes/bin/python -m pytest -q -n 4 --dist worksteal \
  -p no:cacheprovider \
  --rootdir /home/jorb/.paseo/worktrees/16msma8v/feat-w5b3-pane-ticks \
  /home/jorb/.paseo/worktrees/16msma8v/feat-w5b3-pane-ticks/tests/test_task_pane_ticks.py
```

Final targeted result: `19 failed`, no passes. All red failures are the
missing W5b.3 behavior: no checkbox, missing module, missing CSS rule,
preview response equal to disk, writable twin not shipping controls.

Full suite was run once before push:

```sh
PYTHONPATH=/home/jorb/.paseo/worktrees/16msma8v/feat-w5b3-pane-ticks/src \
PYTHONDONTWRITEBYTECODE=1 \
/home/jorb/work/venv-refdes/bin/python -m pytest -q -n 4 --dist worksteal \
  -p no:cacheprovider \
  --rootdir /home/jorb/.paseo/worktrees/16msma8v/feat-w5b3-pane-ticks
```

Result: `20 failed, 6077 passed, 2 skipped in 100.40s`.

The 20th failure was `test_crossplatform_lint.py::test_crossplatform_lint_ratchet`
from this new test file writing multi-line fixture text in text mode. It was
fixed by writing fixture bytes. Targeted `test_crossplatform_lint.py` then
passed (`26 passed`). The full suite was not rerun after that narrow lint fix.

## Iteration notes

- Initial broad "no checkbox in `_site/`" guard was too broad: the site's
  sidenav toggle is an existing read-only checkbox. Scoped that assertion to
  the pane's control surface.
- Initial hostile task row used a flow YAML scalar with embedded double
  quotes; it made the fixture fail to parse. Switched to a block YAML task.
- The serve fork fixture needed a warm check and a de-chained fork edge,
  following `test_serve_preview_task_pane.py`'s existing pattern.
- Guard tests are paired with positive W5b.3 assertions so no test passes
  today merely because the feature is absent.

## Not added

- No source changes.
- No PR.
- No changelog fragment: this is test-only.
