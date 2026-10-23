- The editor's write route resolves retired ids. `GET /api/item/<ref>` has
  answered an id some item records in `former_ids:` since run-5 B5, and
  `_find_item` in `serve/edit.py` documented that it accepted "the same
  spellings the read API accepts" -- but its retired-id step was the one
  spelling it did not have, so `POST /api/item/REQ-000/edit` for an item
  `REQ-007` carrying `former_ids: [REQ-000]` returned 422 "no item
  'REQ-000'" while the read route found it. Both routes now run one shared
  resolver, `serve/resolution.resolve_ref` (extracted from the read route,
  not copied), so the spelling lists cannot drift: the dict key, the display
  id, the surrogate key, then a retired id. A retired id that is also a live
  display id resolves to the live item (the live lookups run first, as in
  `refdes ls`); a retired id two items claim resolves to nothing -- the
  write refuses and names both claimants, the read 404s. That is a real
  change on the read route: the map it used to consult keeps the first
  claimant of a contested id (`ids.collect_former_ids` reports the double
  claim as a build error but records the first claim, leaving only
  live-id collisions out), so a double-claimed retired id used to answer
  200 with that first claimant; both routes now refuse to pick. A retired
  id found nowhere keeps the ordinary "no item" refusal. A save that lands
  under a retired id patches the item's CURRENT spelling (a retired id is
  not in the file) and the applied response now carries the item's live
  `id` and
  `handle`, so the browser can correct its ref -- the same correction
  `GET /api/item/<retired>` already hands back. A conflict under a retired
  id keeps its diff: the conflict screen plans the draft against the
  item's live handle, not the retired spelling (which is not in the file),
  so the author whose disk moved sees the same side-by-side as on any
  other edit.
