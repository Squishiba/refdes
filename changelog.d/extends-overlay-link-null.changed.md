- An overlay's `links: { verb: null }` on a type that `extends:` another now
  suppresses a link the type only inherits from its parent. It had been popped
  as a silent no-op and then made a load error; the null is now interpreted
  after inheritance, the same as a null in the type's own declaration. A null
  for a verb the parent never declares is still an error. The resolved
  hardware@3 schema is unchanged (`docs/design/extends.md` §12).
