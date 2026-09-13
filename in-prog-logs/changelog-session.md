# changelog-session

Task: add CHANGELOG.md `[Unreleased]` entries for a batch of ten commits,
editing only CHANGELOG.md (plus this progress log). Sync first with
`git merge --ff-only main` (done; fast-forward e2a04eb..b88f2f1, tree clean).

## What was added

Under the existing `[Unreleased]` headings (no new headings, no release
version, no restructuring):

- **Breaking** -- extended the existing "bundled standard moves to
  `hardware@3`" entry from three changes to five:
  - item 4: `citations:` becomes an includable `field_sets:` entry; breaking
    rename `component.datasheets` -> `component.citations`; `decision` gains
    the field too; `refdes standard upgrade --to 3` carries the rename
    (commit f8e7ee0).
  - item 5: `decision` gains `recorded_by: [log]`, purely additive (commit
    3c52c4e).
  - updated the "To move:" paragraph so the named renames include
    `datasheets:` -> `citations:`, and "Parts 1 and 2 need no migration"
    became "Parts 1, 2, and 5 need no migration".
- **Added** -- `{{index}}` gains a `tag="..."` parameter, validated like
  `board=` against tags local items actually carry (commit 1cf3e88).
- **Fixed** -- four entries:
  - calc lexer: prefixed non-ASCII units (`kΩ`, `MΩ`) and bare `%` outside a
    tolerance now parse (3a2fced).
  - citation `page:` now deep-links `#page=N` on remote and local-copy hrefs
    (a077cb2).
  - Jinja autoescaping was silently disabled (suffix-matching bug on
    `*.html.j2` names) and is now actually on -- described plainly as a fix
    (5a1f212).
  - preview-data JSON payload escapes `<`/`>` at dump time so a title
    containing `</script>` can't break out of the script element (b88f2f1).

## Judgement calls (kept out of the changelog)

- **97aea5f** (tests: UP031 percent-format -> f-strings): test-only refactor,
  no behaviour change -- no user-facing entry. Noted here as requested.
- **1fa52af** (design: bring backlog.md current): internal design decision
  record, no user-facing behaviour change -- judged not to belong in a
  user-facing changelog; not entered.
- **8e33c08** (docs: correct the body:-in-list-files tradeoff statement):
  wording correction to authoring guidance (plus a comment in parse.py), no
  behaviour change, and the false claim was never in the changelog itself --
  judged not notable enough for an entry. The changer's own batch commit
  summary also lists only the other seven commits, which matches.

## Verification

- `git status --short` -> only CHANGELOG.md and in-prog-logs/changelog-session.md.
- `python -m pytest tests/ -q` -> 663 passed (no code changed).

## Status

Finished. Commit made locally (not pushed).