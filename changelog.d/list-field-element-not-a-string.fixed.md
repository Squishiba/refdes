- **A list-of-strings field refuses an element that is not a string.**
  `tags:` (every bundled type) and `refdes:` (component) are `type: list` —
  a list of plain strings — and an element written as a mapping was accepted
  silently: `refdes check` reported `0 errors`, the built page rendered the
  tags row as a Python dict repr, and `refdes ls --tag x` matched the item on
  the mapping's *value*. Every entry of such a field is now checked, the way
  an `options:` or `tasks:` entry already was: the build fails with
  `tags[1]: {...} is not a string -- a tags entry is a plain string, one per
  line`. The scalar form of the field (`tags: power, analog`) keeps its own
  existing refusal, and an empty entry keeps being the field's own business.
