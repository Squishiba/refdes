- Removing the last link from a verb whose flow list spans lines no longer
  deletes a comment living inside it. The whole-entry delete (the last target
  is going, so the `verb:` line goes too) guards its covered text for `#` in
  the key-to-value gap and the line tail after the value's end -- invisible
  to both was a comment inside a multi-line flow node, between the brackets:
  `satisfies: [\n  REQ-001  # keep me\n]` saved as "applied" with the entry
  and its comment gone. The guard now scans the value's own span for a `#`
  that sits outside every scalar beneath it, so a comment between the
  brackets refuses with the entry's existing message ("a comment sits on
  the 'satisfies' entry ... deleting the entry with its last link would
  destroy it"), while a `#` inside a quoted target's own text is data and
  stays a plain apply.
