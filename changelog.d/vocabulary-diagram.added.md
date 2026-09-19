The vocabulary page now opens with a diagram of the vocabulary: item types as
nodes, every declared link verb as a labelled arrow to each type it may
target, `group` and `part_of` included, and a verb with no declared target
list drawn as one arrow to a single *any type* node. It is plain inline SVG
from a hand-rolled layered layout — no graph library, no Mermaid, no
reader-side JavaScript — so it renders offline, with JavaScript disabled, and
on paper, and it colours itself with the site's own CSS custom properties, so
dark mode and the print stylesheet come free. Nodes are anchors into the
entries below the fold.

`refdes schema --graph` emits the same drawing as an SVG document instead of
Mermaid source, and `docs/links.md` points at the page rather than carrying a
copy of a graph that had already gone stale. The docs site, which renders
markdown with HTML disabled, checks in the identical SVG as an asset.
