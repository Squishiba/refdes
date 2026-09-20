The vocabulary page draws the schema with one small diagram per item type,
beside its own heading, instead of one whole-schema graph above the index.
Each drawing is a fixed three-column layout — types that point at this one
on the left, the type in the centre, types this one points at on the right —
and an arrow reads *subject verb object*. A verb declared under its inverse
name (`documented_by:` on the documenting side) is drawn in its forward
direction; a verb with no declared target list points at a single *any type*
box; a self-referencing verb draws a second box of the same type rather than
a loop; verbs that share a pair and a direction share one arrow and stack
their labels. It is plain inline SVG with no graph library, no Mermaid and
no reader-side JavaScript, coloured with the site's own CSS custom
properties, and every node is an anchor into the entries below.

Above the index, the page now opens with the coverage spine: the three
verbs `refdes` actually counts toward coverage -- addresses, satisfies,
verifies -- as one set of arrows, each label carrying the status gate the
build enforces (`satisfies [accepted]`, `verifies [passing]`). A schema
that declares none of the three gets no drawing at all. `refdes
schema --graph` prints the spine first, then the per-type diagrams.

The whole-graph layout this replaces was rejected: at twenty-nine edges it
produced overlapping labels, arrows sharing one path, and text wider than
its box. `refdes schema --graph` now emits the per-type diagrams — all of
them with no argument, one of them given a type name, with unknown names
erroring against the list of known ones. The checked-in docs-site SVG asset
is gone; `docs/vocabulary.md` carries no diagram reference.
