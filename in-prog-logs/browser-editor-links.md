# Browser editor, Slice 2 -- structured links

Implementation notes and open design calls for the link add/remove slice
(docs/design/browser-editor.md, "Slice 2 -- structured links"). Three
chunks: patcher ops (`a5bbdf3`), service + API (`0df682`), UI + static
tests (this commit).

## Calls made during implementation

- **Patcher ops take the written text; the service decides it.**
  `AddLink(verb, target)` receives the final composite string. The patcher
  never resolves identity or consults the schema -- same division as
  `SetField`, and it keeps the patcher's proof purely textual.
- **Matching a removal target** (`_link_matches`): composites match on the
  key half; a bare wanted text matches a composite's display half *or* its
  key half alone (so `RemoveLink("satisfies", "k7f3m2q9x4a")` works);
  bare-to-bare matches text. Ambiguity (two spellings of the same target in
  one list) refuses rather than picks.
- **Scalar widening**: adding to `satisfies: REQ-001` produces
  `satisfies: [REQ-001, NEW]` -- the original spelling is kept verbatim
  (quotes included), and the flow form is chosen because it is the shape
  the repo's own files use for multi-target verbs.
- **Removing the last target deletes the whole verb entry** (and its block
  lines), not `satisfies: []` -- an empty list is a value the schema
  validator and every reader would have to learn to ignore.
- **Flow separator on removal**: the removed target takes the separator
  that *followed* it; the preceding one keeps the author's spacing. This
  is arbitrary but must be pinned, so tests pin it.
- **`links.composite_for` is now the one public composite rule** -- the
  freeze pass (`_planned_target`) and the edit service both call it, so an
  editor-written link and a freeze-expanded link are spelled identically
  (keys.md §3).
- **Null-artifact-key refusal lives in the service**, not the patcher: the
  patcher cannot know an item is imported; the service has the loaded
  project. The reason text names the rule so an author who hits it learns
  why instead of guessing.
- **Removal resolves nothing**: a dangling composite (`REQ-009@zzz...`) has
  no item behind it, and cleaning up a broken link must not require the
  broken thing to exist. Only adds resolve + type-check.
- **Sealed check runs before link resolution** -- a sealed refusal is a
  sealed refusal even when the request also names a bogus verb.
- **The UI picker sends handles, never composites.** The service owns the
  DISPLAY-ID@key spelling; a static test asserts links.js contains no
  composite-building template.
- **Link ops ride the one draft** (`draft.links = {add, remove}`), the one
  Save, the one revision, the one conflict screen -- the design's rule
  against a second draft mechanism.
- **`follows:` is editable through the picker like any declared verb.**
  Writing a composite there is consistent with the freeze pass (a bare
  `follows` freezes to the same composite). Thread-ordering semantics of
  `follows` edits are not restricted beyond the schema; if the design
  later wants chain-aware validation on *edits* (not just freeze), that
  is a service-side rule to add -- flagged, not built.

## Deliberately not here (Slice 3)

- No item creation, no id/key editing, no deleting items.
- No link *reordering*; add appends, remove deletes.
