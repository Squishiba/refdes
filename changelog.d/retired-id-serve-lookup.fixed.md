- A retired id resolves in `GET /api/item/<ref>`, and in the VS Code extension's
  id lookup. `docs/ids.md` promises that "every place that answers 'what is
  REQ-PWR-001?' answers it", and `editors/vscode/README.md` that "hovering the id
  you have from a schematic or a commit message tells you which item it is now",
  but `_find_item` tried only the `project.items` dict key and `item_by_ref`, so a
  retired id answered `{"error": "no item matches 'REQ-PWR-007'"}` with a 404, and
  `itemsById()` — keyed on `item.id` alone — meant `provideHover` returned nothing
  before it even asked. `refdes ls REQ-PWR-007` has resolved that spelling to the
  live item since #150, so the CLI and the editor disagreed about the same id.
  `_find_item` now consults `project.former_ids` after the live spellings and
  returns the live item, echoing the item's own key (or display id) as the handle
  rather than the retired spelling; `itemsById()` indexes each row's `former_ids`
  in a second pass, so a live id still wins any collision, which is what `refdes ls`
  does with one. Hovering a retired id now shows that item's card, including the
  `_formerly known as …_` row it already rendered for the live id.
