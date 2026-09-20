- **A build now warns when a link and a status disagree about the same
  fact.** `superseded` and `selected` are each stored twice: once as a status,
  once as the `supersedes:`/`selects:` link pointing at the item that carries
  it, and neither half changes the other — the verbs' own definitions have said
  so all along, because the state can disagree with itself. Nothing had ever
  checked. Both directions are reported, per pair: `DEC-003 supersedes DEC-002`
  while DEC-002 sits at `accepted` warns that the link does not move a status
  on its own and names both fixes (set the status, or drop the link);
  `CMP-001` at `status: selected` with no `selects:` anywhere warns that
  nothing selects it and names both fixes the other way. A warning, never an
  error, and never a rewrite: the build cannot know which half was the
  mistake. Computing the status from the link instead — dropping both from the
  enums — was the alternative, and it is not what shipped, because `selected`
  is component's `satisfying_statuses` value and coverage reads it, and an
  authored lifecycle field should not silently mean whatever the graph happens
  to say. Nothing is reported where the vocabulary does not carry both halves:
  a type whose `status` choices never offer the paired value, or a project that
  never declares the verb, hears nothing. Applies to every hardware standard
  version — the pairs exist in all three — and this repo's own project gained
  the `selects:` link it was missing on DEC-PWR-001.
