- `docs/design/thread-workbench.md` still said "W3 ('values') is in
  progress" three phases after it landed (`serve/server.py::_decorate_calc_values`,
  `static/preview.js`, `tests/test_serve_preview_values.py` are all in the
  tree). The Status header now names W1–W3 landed and points at their
  `in-prog-logs/` entries, §8's phase bullets say so too, and a note under
  §5 records the one place the shipped D1 is narrower than its row: dotted
  `ITEM.NAME` mentions in prose stay undecorated, because they are not prose
  syntax and a value beside them would be the pane implying meaning the site
  does not have (§3.3) — held open for Jared as the question of whether they
  become real site-side syntax first. `in-prog-logs/thread-workbench-w3.md`
  joins `thread-workbench-w1.md`/`-w2.md` as the phase's entry in that
  series, alongside the implementation log `wb-w3-values.md`.
- New test `test_a_real_publish_of_the_same_project_shows_none_of_it` pins
  the thread-workbench invariant (§4, "Never touches `_site/`") at the
  publish boundary rather than the serve one: the same sources a decorated
  preview was served from, run through `render_site`, produce a site with no
  workbench marker and the plain published `<code>12 V</code>`. A second
  test pins that a calc table with no `{{name}}` cited in prose gains no
  show-values toggle.
