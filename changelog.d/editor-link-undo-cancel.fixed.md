- The link picker's undo button now takes a pending link op back instead
  of flipping it. Undoing a pending add used to leave a pending removal of
  a link the item does not have (and undoing a pending removal, a pending
  add of a link it already has); the server refuses exactly those ops with
  422, so Save went red, the draft stayed dirty through reloads, and the
  only way out was Discard -- taking the rest of the draft with it. Undo
  now cancels: the draft is clean, its mirror is gone, and a reload comes
  back clean. Clicking Add on the candidate of a link you have
  pending-removed cancels that removal, rather than stacking an
  `add_link` for a link the item already has.
