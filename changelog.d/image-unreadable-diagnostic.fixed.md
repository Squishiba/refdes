- Images: a local `<img src>` that resolves to a file the build cannot read
  (mode 000, EACCES from any cause) used to die as a raw `PermissionError`
  traceback from the render pass's digest read — `refdes check` and
  `refdes build` exited with the image named nowhere, and no reference after
  the unreadable one was ever checked. It is now a build error at the
  reference, naming the src, the resolved file and the OS's reason, next to
  its own sentence distinct from "does not exist"; the reference stays
  unrewritten, the hash pass keeps its deterministic `None`-digest sentinel,
  and the preview record marks the reference failed (IMAGE-ASSET-007). A
  mode-000 file inside a declared `site.assets:` directory — registered for
  bulk-copy with no reference gating it — used to escape `render_site` into
  `refdes build`'s "cannot write the site to _site" refusal, which names the
  output directory and sends the user to make it writable; the copy now
  names the asset and its reason, publishes the rest of the site, and leaves
  that file out. A `site.assets:` file is refused *at registration*:
  `refdes check` names it (a command that renders, never publishes, cannot
  leave an unreadable declared asset unreported), the build publishes the
  site without it, and a referenced one is additionally gated at the
  reference, where the preview record marks it failed.
