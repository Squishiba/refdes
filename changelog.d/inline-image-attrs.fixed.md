- An image attribute suffix (`{width=50%}`) on an image that is not alone in
  its paragraph — inline with a sentence, in a list item, in a table cell — is
  no longer rendered as literal text on the page. `width=` is applied to the
  `<img>` itself; `caption=` and `id=`, which only mean something on a
  `<figure>`, are dropped with a warning naming file:line and item id and
  telling you to put the image in a paragraph of its own to get them. An
  unknown attribute name warns the same way rather than passing in silence.
  Paragraph-only figures — `<figure class="md-figure">`, the caption fallback
  to `alt`, figure ids and numbering — are unchanged, and braces that are not
  an attribute suffix at all (`the set {a, b}`) are still ordinary prose.
