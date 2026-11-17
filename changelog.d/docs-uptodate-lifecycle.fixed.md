- Docs: `checks.md` said a `checks:` `value` had to come from a `calc` block.
  An inline calc span defines a value in the same item-wide scope, so a check
  may name one too.
- Docs: `coverage.md` said the standard sets `coverable_statuses:` on
  `requirement`/`bound`; `bound` inherits it (`extends: requirement`) rather
  than declaring it.
- Docs: `output.md`'s per-board and per-workspace report lists omitted
  `tree-<scope>.html`, said "six pages" though the set varies, and implied
  every registered board gets a full set. A scope with nothing to show gets
  none, and `log`/`references`/`parts` appear only when there is content.
- Docs: `output.md` described the threaded log's task pane as read-only without
  saying that `refdes serve`'s preview makes it writable (ticks, Save, the
  conflict panel). It now points at the browser-editor walkthrough.
- Docs: `output.md`'s `items.json` key list omitted the conditional top-level
  `navis` key, contradicting "Everything else is always present". The payload
  is now documented with its real field shape.
- Docs: `troubleshooting.md` said a `text:` under hardware@3 "gets the rename
  diagnostic below" without documenting it; the
  `'requirement.text' is now 'requirement.body'` (and `bound`/`test` spellings)
  message is now quoted.
- Docs: `upgrading.md` named the deprecated `refdes revise` alias where the
  current command is `refdes rename`.
