- **Added:** `include:` now composes a whole slice of a type, not just its
  fields. A set carries `fields:`, `links:` and `body:` (docs/design/
  composition.md): including a set can grant a type its link verbs and its
  body policy as well as its fields. Sets merge in include-list order, the
  type's own declaration merges last and wins, and every merge is by-name
  with whole-spec replacement. Two included sets declaring the same link
  verb or body with different specs is a load error naming both sets —
  neither author wrote that conflict at the point of use. An include that
  contributes nothing that survives the merge warns in the build output
  instead of failing it: deliberate shadowing is legitimate, silent
  dead weight is not.
