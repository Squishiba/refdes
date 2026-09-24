# Thread workbench W2 ("squiggles") — notes

Scope per docs/design/thread-workbench.md §8: D3 inline diagnostics + D2
image provenance, both reading data the build already produces. Response-only
decoration per §4, exactly as W1 established.

## Decided locally (not blocking, recorded for review)

- **D2 data retention (the question the task flagged).** `_search_image_src`'s
  result was indeed used once to rewrite the HTML and discarded: the rendered
  page cannot distinguish a failed `<img>` (src passes the rewrite untouched)
  from an external one, and carries no back-pointer from a rewritten
  `assets/...` src to its source path. Minimal threading done:
  `_process_images.swap` now records `{"src", "ok", "rel", "dest"}` per item
  into a new `Project.image_results` dict — pure bookkeeping over values the
  pass already computes, no second search, no new evaluation. Pages
  (`where_id is None`) are not recorded; W2 decorates item previews only.
  The decorator (`serve/server.py::_decorate_images`) reads it and never
  resolves anything.
- **Content hash is shown only when the build computed one.** Images that
  resolve out of a `site.assets:` directory are identity-mapped in
  `project.assets` by design ("those never hash", model.py), so their
  provenance title is the source path alone; images resolved relative to the
  source file get `path · <16-hex digest>` (the digest the build already put
  in the hashed leaf — parsed back out of the rewritten src, not rehashed).
  Showing a hash for identity-mapped assets would mean hashing, which W2
  forbids; this is stated as the finding rather than papered over.
- **D3 placement.** The rendered HTML has no line-addressable structure, so
  per the task's fallback the diagnostics render as a summary panel at the
  foot of the page, in `templates/index.html.j2`'s exact diagnostic markup
  (`level — file:line [id]: message`, `ul.tight.mono.small`, `li.bad`/`li.warn`)
  — all classes already exist in the theme. D2's failure marker is the truly
  inline half: it sits directly after the unresolved `<img>`.
- **Filter rule.** A diagnostic belongs to the page if `d.item_id == item.id`
  or `d.file == item.source_file`. Two items sharing one source file see that
  file's diagnostics on both pages — the file is the unit diagnostics are
  emitted against, and hiding one item's own error would be worse.
- **No `?workbench=1` gate.** §7.5 allows "a `?workbench=1` or a toggle";
  W1 shipped its probe ungated on every item preview, and W2 follows the
  same precedent — decorations are harmless on a preview and gating would
  fork the decoration path for no v1 benefit. If a gate is wanted later it
  is one `if` in `_decorate`.
- **Item scoping of the decoration.** `_decorate` already resolved
  filename -> item for the "Edit this item" link; the same lookup now yields
  the `Item` used for both D2 and D3. Non-item pages (index, coverage) get
  neither, pinned by test.

## W4 observation (per §7.4, stated plainly)

Nothing cheap and obvious was visible in the W2 touch path; no speculative
optimizations were made.
