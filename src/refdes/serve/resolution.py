"""One item-reference resolver, shared by the read and the write API route.

Both `/api/item/<ref>` (read, `api._find_item`) and the editor's write route
(`edit._find_item`) name an item by a spelling the author has, and the two
routes must not drift on what a spelling means: the browser reads the handle
from one route and posts the edit to the other, and a retired id the read
route resolves while the write route 422s on it is the split EDIT-03 fixes.
This module is the single place that answers "which item is `ref`?".

Accepted spellings, in order:

1. the `project.items` dict key -- a surrogate key, or the provisional
   handle of a keyless item (what `/api/items` rows carry as `handle`);
2. the display id, then the surrogate key, via `Project.item_by_ref`;
3. a retired id some item still records in `former_ids:` -- the id a
   schematic or a commit message names after a rename (docs/ids.md).

A live spelling always wins a retired one: step 3 runs last, and the item
whose *current* id is `ref` is found by step 1/2 before the scan starts.
Two items claiming the same retired id resolve to nothing: the resolver
reports the claimants and each route refuses with them. The built map does
NOT behave this way -- `ids.collect_former_ids` records the FIRST claimant
under the contested id and reports the second claim as a build error (only
a retired id colliding with a live id is left out of the map) -- so
reading the map here would pick a winner, which is exactly what the write
route must never do.

The retired step scans the declared `former_ids:` fields directly rather
than reading `project.former_ids`, because that map is build output and
the write route's `_load_before` deliberately runs on an *unbuilt*
`load_tree` snapshot where it is empty. A retired id that is also a live
id resolves to the live item by ordering alone: the live lookups run
first, the scan is never reached. Within the scan, an item recording its
own current id is excluded (a build error, not an identity), and several
claimants are reported, never picked -- where the built map would have
kept the first. The point of scanning: the write route must not depend on
a build to answer identity questions.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Item, Project


@dataclass(frozen=True)
class Resolution:
    """What one spelling resolved to.

    `item` is the item, `handle` is its CURRENT live identity (key, else
    display id) -- never the retired spelling, so the caller can address the
    item again with what it got and a browser can correct its ref. `retired`
    says the match came from step 3. `claimed_by` is non-empty only for an
    ambiguous retired id: the display ids of the claiming items, which is
    what a refusal must name.
    """

    item: Item | None = None
    handle: str | None = None
    retired: bool = False
    claimed_by: tuple[str, ...] = ()


def resolve_ref(project: Project, ref: str) -> Resolution:
    """Resolve one item reference against the spellings documented above."""
    if not ref:
        return Resolution()
    item = project.items.get(ref)
    if item is not None:
        return Resolution(item=item, handle=ref)
    item = project.item_by_ref(ref)
    if item is not None:
        return Resolution(item=item, handle=item.key or ref)
    # The retired step. An item recording its own current id is excluded
    # (the live lookups above already found it; the self-reference is a
    # build error, not an identity).
    owners = [i for i in project.local_items if ref in i.former_ids and i.id != ref]
    if len(owners) > 1:
        return Resolution(claimed_by=tuple(i.id or i.key or "?" for i in owners))
    if owners:
        item = owners[0]
        return Resolution(item=item, handle=item.key or item.id, retired=True)
    return Resolution()
