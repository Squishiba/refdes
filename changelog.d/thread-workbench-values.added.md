Thread workbench W3 ("values", docs/design/thread-workbench.md §7.1): served
preview pages now attribute inline calc values in prose, pane-only. The
published site already renders a `{{name}}` reference as its evaluated value
with the name destroyed; the workbench puts the name back beside the value —
a hover title (`name = value`, plus the owning block's name from
`CalcLine.block`) on the `<code>` span and a small visible label — from
`item.calc_values`, the strings the build already formatted. Nothing is
evaluated or re-evaluated: a `{{name | unit}}` reference keeps its plain
published form, because its converted text is stored nowhere and recomputing
it would be a second evaluator. Each calc table gains a response-only
**values** toggle (a `refdes-values-toggle` button in the caption, wired by
`preview.js` with a plain listener — CSP stays `script-src 'self'`) that
hides or shows the attributions page-wide. Identification is a parallel walk
of the body's `INLINE_VALUE_RE` references against the page's `<code>`
elements that advances only on an exact match of the build's formatted
value, so an author's own code spans are left untouched. Dotted `ITEM.NAME`
mentions in prose are deliberately *not* decorated — they are not prose
syntax, and showing a value there would imply meaning the site does not have
(recorded as an open question for Jared: whether prose dotted refs become
real site-side syntax first). Like every other workbench decoration the
change is response-only: the rendered generation on disk, and `_site/`, are
byte-identical with and without it.
