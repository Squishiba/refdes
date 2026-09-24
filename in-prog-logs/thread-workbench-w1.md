# Thread workbench W1 ("pin") — notes

Scope per docs/design/thread-workbench.md §8: preview auto-reload on
revision change + "open this item's preview page" from /edit/. No
decorations (D1–D5 are W2/W3).

## Decided locally (not blocking, recorded for review)

- **How the preview page authenticates its `/api/revision` polls.** The
  existing `/api/revision` endpoint was sufficient (its `serial` is exactly
  the "did the built project change" signal), so no new endpoint was added.
  But `/api/*` demands the `X-Refdes-Token` header, and a preview page has
  no token of its own. Resolution: `_decorate` injects a `refdes-token`
  meta into the preview HTML response — the identical pattern the editor
  shell (`index.html`'s `__REFDES_TOKEN__`) already uses, inside the same
  response-only decoration boundary as the toolbar. Not a new
  unauthenticated surface: the page itself is already gated on a cookie
  whose value *is* the token, so anything that can load the page already
  holds the credential. Alternative (a cookie-authed revision endpoint)
  would have widened the auth surface instead of reusing it.
- **Reload granularity.** The probe reloads on any `serial` move, not only
  when this item's own page changed. Matches the doc's W1 framing
  ("auto-reload on revision change"); per-item staleness tracking would be
  a new API surface for no W1 benefit. Side effect: the `/edit/` item view's
  preview iframe self-reloads too, for free.
- **`preview.js` as an import-graph entry.** `test_serve_static`'s graph
  walk starts at index.html; preview.js is an entry loaded from preview
  pages instead, so it was added to the walk's seed set explicitly.

## W4 observation (per §7.4, stated plainly)

Nothing cheap and obvious was visible in the W1 touch path; no speculative
optimizations were made.
