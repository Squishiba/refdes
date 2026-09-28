- The unknown-key error for a `boards:` or `workspaces:` entry now names the page
  that documents the block, so a reader told which key is wrong is also told
  where the keys are explained: `boards.<name>.<key> is not valid -- a boards:
  entry takes ... See docs/multi-board.md.` Each block points at its own page
  (`workspaces:` at `docs/workspaces.md`, which documents its keys; the boards
  page only links onward to it). No other config block's message changes, and
  the error is still a plain configuration error on every command, read-only
  ones included.
