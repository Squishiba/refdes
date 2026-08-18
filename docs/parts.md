# Parts

"What changes if we drop the STM32G474" is a question refdes can answer with
one click instead of a grep, because part numbers already live in the
project — this indexes what's already there rather than adding a `part`
item type.

## Two sources, both already in the schema

1. **`component.part_number`** — a plain `text` field. Recognized by field
   name, the same way `limit`, `options`, and `checks` are — any field
   literally named `part_number`, on *any* item type, feeds the index. Most
   projects only ever put it on `component`, but a project that adds it to
   some other type (a connector spec, say) is picked up automatically, with
   no config change.
2. **The nested `part_number` inside a `citations:` entry** — the case for a
   part real enough to have a datasheet pinned but never (yet, or ever)
   promoted to its own `component` item:

   ```yaml
   datasheets:
     - url: https://www.ti.com/lit/ds/symlink/lm358.pdf
       part_number: LM358
   ```

## Exact string, deliberately

Indexed on the literal string. No normalization, no family grouping, no
guessing that `STM32G474` and `STM32G474RET6` are the same part or even
related — every normalization scheme is right for some manufacturer's
numbering convention and wrong for others, and a false grouping silently
answering "what uses this part" with the wrong set of items is worse than
answering "nothing, under this exact string" and leaving you to notice the
near match yourself.

If family grouping is ever wanted, it's a **declared field** — add
`family: STM32G4` to your own components and index on that field name
instead — not a heuristic the tool invents on your behalf.

## The parts page

`parts.html`, global, plus `parts-<board>.html` and `parts-<workspace>.html`
scoped, following the same shape as [references](markdown.md#citing-a-datasheet)
and every other generated report. Each row: the exact part number, which
components declare it directly, which citations name it, and (on the global
page) which boards it appears on.

A component's own fields table links straight to its part's section on
`parts.html` when something else also uses it — "also used elsewhere" —
rather than duplicating the full list on every page that happens to share a
part.

`refdes audit` gets a "Parts:" section, every part number, not filtered to
multiply-used ones — you skim for the multi-board rows yourself rather than
the tool pre-deciding what's interesting.

## Not a `{{index}}` block

`{{index by="part_number" type="component"}}` (see [generated
blocks](blocks.md)) already works and is a fine quick view of the component
half alone. It can't reach the nested citation half — a citation is a
structured record, not a groupable field, and `{{index}}`'s `type=` is
deliberately singular, so it can't reach an open-ended set of types the way
the parts page does. `parts.html` is a dedicated report for that reason, not
a gap in `{{index}}`.

## Boards, workspaces, and the cross-workspace lint

The parts page is a **derived view, not an authored link**. It stores
nothing on any item, declares no `links:`, and creates no edge a project
would ever write down — it's computed fresh, at build time, from field
values that already exist. Two boards in different workspaces using the
same microcontroller is a coincidence of the bill of materials, not a
claimed dependency between them — exactly the coincidence this page exists
to surface. The [cross-workspace lint](workspaces.md) walks only
`item.links`, so sharing a `part_number` across workspaces never trips it;
only an [`equivalent`/`alternate`](links.md#part-equivalence-equivalent-and-alternate)
link — a real authored claim — would.

## Part equivalence

Recording that a manufacturer says two parts are equivalent is parts data
and doesn't belong here. Recording that *you've decided* two parts are
interchangeable for *this design* is a reviewable claim, which is exactly
refdes's domain — see [links: `equivalent` and
`alternate`](links.md#part-equivalence-equivalent-and-alternate).
