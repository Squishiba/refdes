Thread workbench W1 ("pin", docs/design/thread-workbench.md): preview pages
reload themselves when the project rebuilds, and the editor's item view links
to the item's own preview page. `server._decorate` injects a reload probe --
a `refdes-serial` meta naming the snapshot being served, a `refdes-token`
meta (the same meta the editor shell carries; the page is already
cookie-gated on that token), and a module script tag -- into every preview
HTML response, inside the same response-only boundary as the edit toolbar:
the rendered generation on disk stays free of serve affordances. The new
`static/preview.js` follows app.js's established posture: poll
`/api/revision` every 2 s over the shared api.js transport and
`location.reload()` when the serial moves past the one the page was rendered
from -- no push channel, no new endpoint, no client-side semantics. From
`/edit/`'s item view, an "Open preview" link opens the item's own
`/preview/<page>.html` in a new tab (the shell's "Rendered site" convention),
built from the server-provided `page` field. No decorations (D1-D5 stay in
W2/W3); the pane stays read-only, `_site/` untouched, security inherited.
