- Calc blocks can be named: ```` ```calc id="losses" ````. A named block's
  rendered table gains an anchor (`id="calc-losses"`) and a caption carrying
  the name, so an item with two calculations can finally say which is which
  (docs/design/named-calc-blocks.md Phase 1). Naming is opt-in: an unnamed
  block renders byte-for-byte as before, `env` and value-name rules are
  unchanged (a name is a label on the rendering, not a scope), and block
  names are unique per item — a duplicate is a build error naming both lines
  and the rename fix. The fence info string is now validated: text after
    ```` ```calc ```` that is not `id="..."` (a bare word, an unquoted value,
  `name=`, a name outside `[a-z][a-z0-9_-]*`) is a build error at the fence
  line naming the fix, where before it was silently ignored. A dotted
  cross-item reference with a block half spliced in
  (`DEC-PWR-001.losses.P_diss`) is an error naming the working form
  `DEC-PWR-001.P_diss`.
