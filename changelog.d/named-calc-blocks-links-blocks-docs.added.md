- Document named calc blocks for authors:
  - `[[ID#calc:name]]` fragment links in links.md: point at a named calc
    block's table, link-only (never inlines), the required `calc:` prefix,
    and the warning-on-miss posture
  - The `{{calcblock item=... block=...}}` page directive in blocks.md:
    renders one named block's rows (never evaluates), local items only,
    strict failure modes, and the no-`all=` no-wildcard rule