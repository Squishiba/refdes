Preview decorations for the thread workbench (W2, "squiggles"). A served
preview page of an item now carries, response-only like the W1 probe and the
toolbar, the two author-time signals the build already computes: D3, the
item's own build diagnostics in a panel at the foot of the page (filtered by
item id or own source file, rendered in the index page's diagnostic markup),
and D2, image provenance — a resolved `<img>` gains hover-visible
`data-refdes-src`/`title` attributes naming its source path and, when the
build content-hashed it, the hash; one the build could not resolve (missing
or ambiguous) gains a visible inline marker instead of rendering as a silent
broken image. `build._process_images` records each per-item resolution result
(`{"src", "ok", "rel", "dest"}`) on the new `Project.image_results` as pure
bookkeeping over values it computes anyway — no second asset search, no new
evaluation. Nothing published changes: the rendered generation on disk, and
`_site/`, carry none of the decoration.
