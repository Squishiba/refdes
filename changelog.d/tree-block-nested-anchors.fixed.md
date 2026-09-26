- `{{tree}}` on a narrative page emitted an anchor inside an anchor. The block
  renders `tree.html`'s markup, where every item ID is already the text of an
  `<a class="ref">`, and the page linkifier swept over the whole page, found
  those IDs again and wrapped them a second time:
  `<a class="ref" href="grp-001.html" data-ref="<a class="ref" href="grp-001.html" data-ref="GRP-001">GRP-001</a>` —
  a start tag inside another start tag, a `data-ref` carrying a fragment of
  markup, and a stray `ref` attribute. A tag-depth scan misses it, because the
  inner `>` closes the outer tag first. `_linkify` already refused to touch
  `<pre>` and `<code>` for the same reason — code is already-marked-up text too
  — and now skips `<a>` regions as well, so a row is one link. An ID in the
  tree's own plain text (an item title mentioning another item, the
  `(expanded under ...)` hint) is still linked, as is every other block: a full
  before/after site build of a project using `{{tree}}`, `{{index}}`,
  `{{cascade}}` and `{{compare}}` on one page differs in the tree block's line
  and nowhere else, and this repository's own site build is byte-identical.
