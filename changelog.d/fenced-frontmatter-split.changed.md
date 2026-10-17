- A `---` line inside an open fenced code block no longer splits a markdown
  item file (finding R10-X1 of the run-10 release-gate simulation). Pasting a
  front-matter example into an item's body as a ` ```yaml ` fence used to mint
  a live phantom item from the fenced text: `duplicate id` errors, a fenced
  `checks:` read as a real field, and the phantom listed by `refdes ls`. The
  splitter now recognises fenced code blocks (CommonMark's rules: a ` ``` `/
  `~~~` opener indented at most three spaces, closed by the same character in
  a run at least as long with nothing after it; fences do not nest) and treats
  their contents as body text. Every `---` outside a fence splits exactly as
  before; an unclosed fence opener protects nothing, so a file whose fence is
  never closed parses as it does today. Suppression is never silent: a
  front-matter-shaped `---` (a YAML key on the next line, a closing `---`
  later) inside a fence warns once at its line, since the parser cannot tell
  a pasted example from an item hidden behind an unclosed earlier fence —
  a deliberate example now costs one warning, and an item can never vanish
  from the load without a word. No item in this repo's `items/` and no
  test fixture carried a `---` inside a fence, so no existing file changes
  meaning; docs pages are rendered by their own front-matter rule and were
  never affected. `docs/authoring.md` §"Several items in one file" states the
  exception.
