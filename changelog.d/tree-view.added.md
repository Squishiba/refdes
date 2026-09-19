A generated `tree.html` page shows the whole project as one containment
tree — workspace, board, `part_of` group, item. Multi-parent items expand
once under a deterministic primary parent and link back from the others;
items with no board and no group land in a visible `Project-wide` bucket
rendered last with a count, so the tree is total: nothing is ever silently
dropped. Collapsed with plain `<details>` (no JavaScript), it prints fully
expanded, and the sidebar links it for every project with items.
