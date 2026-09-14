- A citation entry can declare an optional `id:` (letters, digits, `-`, `_`
  only), unique across the whole project the same way a figure id already is
  — a duplicate is a build error naming both locations, and an invalid one is
  rejected at declaration. `[[cite:<id>]]` (or `[[cite:<id>|label]]` for
  custom text) links to that citation's own row on the page of the item that
  declared it; an unknown id warns and renders in red, and a `#field`
  fragment on a cite reference warns exactly as it does on a figure
  reference. The matching row on the item page carries `id="cite-<id>"`. A
  citation with no `id:` renders exactly as before. See [citing a
  datasheet](markdown.md#citing-a-datasheet).
- `revise` now also reports a stale `[[ID#field]]` fragment when the same
  rename mapping renamed that field on the id's own type, even when the id
  itself did not change.
