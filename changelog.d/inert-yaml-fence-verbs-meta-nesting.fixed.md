- **The inert body-` ```yaml `-fence warning (added for `checks:`) now covers
  the keys it missed, and stops firing where it was wrong.** A body fence
  declaring a link verb the item's type declares (`satisfies:` beside the
  calc fence) is the same trap as a field — it lands in no `links:` and
  coverage silently stays open — and now warns as "a link of type …". So do
  `id:`/`type:`, front-matter keys the body never reads. A fence quoted in a
  blockquote (`> ` ```yaml) renders as a real code block and now warns too.
  A ` ```yaml ` example escaped inside an outer fence (e.g. a ` ```text `
  fence) is literal example code and no longer warns with the nonsense
  "move it to front matter" remedy.
