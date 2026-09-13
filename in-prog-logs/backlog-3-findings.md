# backlog.md — record three findings from this session's code review

## Step 0

`git merge --ff-only main` → `e2a04eb..72ccf1d`, clean fast-forward. Tree
stayed clean (nothing dirty before or after).

## What changed in docs/design/backlog.md (the only file edited)

- Header commit reference updated → `72ccf1d` (the tree everything below was
  verified against), following the precedent from the 25-28 session.
- New section `## Internal review, findings 29–31` inserted between the
  25-28 section and `## Surrogate keys — remaining layers`. It names the
  provenance at the section level (`Internal review`, not one of the two
  GitHub issue #7 attachments) and again in each entry as a bold
  `**Source: internal review, not issue #7.**` lead line, so the
  attribution can't be mistaken for the Source section's documents.
- Entries 29, 30, 31 follow the established structure: prose finding with
  file:line refs, `**Status:**` line, `**Local model:**` verdict. All three
  verdicts are `(not decided — my read)`, honestly — the suitability of
  none of the three was put to the rule in conversation, and none of them
  originates in an issue that carried a verdict.
- The `## Source` section was NOT restructured — it still describes the two
  attachments only.

## Verification of every claim written (all against the tree, not the brief)

- **29** — `templates/log.html.j2:42` renders `{{ entry.body_html | safe }}`
  bare; the other three sites wrap: `item.html.j2:62`
  `figured(item.body_html)`, `document.html.j2:78`
  `anchored(figured(item.body_html))`, `page.html.j2:19`
  `figured(page.body_html)`. `figured()` is `_figured` (`render.py:44-52`):
  numbers `{id=...}` figures per document (`assign_figure_numbers`), then
  `resolve_figures` (`build.py:1143-1177`) substitutes the two deferred
  markers — `<span class="fig-num" data-fig="...">` emitted by
  `_apply_figure_attrs` (`build.py:1080`) and
  `<span class="fig-ref-pending" ...>` that `_linkify` mints for
  `[[fig:id]]` (`build.py:905-910`). Log entries are items, so their bodies
  already carry both markers; the log template never runs the resolve pass.
  The log page write (`render.py:731-737`) passes no `figured` closure at
  all (contrast the document page's, `render.py:777-779`) — a fix needs
  both the template wrap and the closure wiring. `.fig-num`/`.fig-ref-pending`
  have no CSS (checked style.css), so unresolved they are invisible.
- **30** — `_esc` at `build.py:864-871` and `blocks.py:70-77`: escapes
  `& < > "`, not `'`. Checked every call site: build.py `_esc` values land
  in double-quoted attributes (`data-*` at 905-909, 1080; `style=` 1062;
  `id=` 1079) or text nodes; blocks.py's five uses (189, 191, 339, 390, 462)
  are all text nodes. No single-quoted attribute exists in either module
  (grep for `='` patterns returned nothing). So the "safe today" claim
  holds and the trap is genuinely latent.
- **31** — `render.py:600-608` is `autoescape=True` (commit `5a1f212`,
  confirmed in main's log); `render.py:629-639` escapes `<`/`>` in the
  previews payload (commit `b88f2f1`); `base.html.j2:60` is the only
  `| safe` sink. Tests: `test_citation_page_value_is_html_escaped`
  (`tests/test_citations.py:723-745`) — attribute-context breakout via
  citation `page:`; `test_preview_data_escapes_script_close`
  (`tests/test_render_assets.py:517-559`) — JSON payload. Text-node sites
  confirmed: `index.html.j2:54,81` and `coverage.html.j2:48` render
  `{{ item.title }}` with no `| safe`; no test pins the escape there.

## Difficulties

- The Read tool initially returned the file as 439 lines when it is 764 —
  some truncation on the first read. Caught it via `Select-String`/grep
  (findings 25-28 and the Surrogate-keys section were missing from the
  first dump) and re-read in chunks before writing anything. No content
  was affected; just a read-tool quirk.

## Deliberately not touched

- The `## Source` section, every existing entry, the header prose, and the
  surrogate-keys section (other than the header commit hash in the intro).
- Any code, test, or CHANGELOG file.

## Status

Finished pending verification below.