- The troubleshooting page's required-field entry claimed `bound` has no required
  field under `hardware@3`; it requires `limit:`, and `group` requires `title:`.
  The entry now lists the types as the schema declares them.
- The hand-rename walkthrough's sample console block prints a coverage warning;
  it now says why (the example's requirements are `active` — a draft requirement
  is excluded from coverage, so a project of drafts prints no warning there).
- The calc section told you to pin a torque display with `tq = ... | N*m`; the
  pin is accepted but the display is canonicalised, so it still reads `J`. The
  entry now says so and points to naming the unit in prose.
- The empty-`body:` warning block now quotes the full message, ending with its
  own "A warning, not an error" sentence.
