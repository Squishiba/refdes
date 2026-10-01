- `refdes ls` shows a **workspace column** on a project that declares
  `workspaces:`, one level above the board column — so in a multi-workspace
  project the unfiltered listing says which workspace each item is in, and the
  existence of `--workspace` is discoverable from the listing that flag
  filters. Before, the only way to see an item's workspace was to filter for
  it, and a three-workspace project's plain `ls` gave no hint that three
  existed. The column reads the same resolved `item.workspace` the flag
  filters on; an item in no workspace (e.g. sitting directly in `items/`,
  outside every workspace folder) is shown as blank padding rather than a
  placeholder, because no `--workspace` value selects it either — and a
  filtered listing whose rows all lack a workspace drops the column, the same
  way a listing with no boards drops the board column. A project with no
  `workspaces:` registry has no workspace for any item, so it gets no column
  and byte-identical output, keeping the `workspaces:` feature opt-in end to
  end. `refdes index` is unchanged: it has exported a per-item `workspace`,
  and the registry itself, all along. (user-sim release gate run 3, finding N5)