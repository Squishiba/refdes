- `refdes ls` takes `--workspace NAME`, the listing counterpart of the
  `--workspace` filter `check` already had: in a project with `workspaces:`
  declared, "what's in product-a?" is the first question a workspace invites and
  `ls` could narrow by board, type, source file and tag but not by workspace —
  leaving `index --compact` (which has exported a `workspace` per item, and the
  registry itself, all along) or a `--file items/product-a/…` path guess as the
  only ways to ask it. It filters exactly as `--board` does: an exact match on
  the item's resolved workspace, combined as a plain AND with every other `ls`
  filter, and an unknown name answered with "no items match" rather than
  `check`'s registry error. On a project with no `workspaces:` registry no item
  has a workspace, so the flag matches nothing there; every other `ls` output is
  unchanged. (user-sim release gate run 2, finding F1)
