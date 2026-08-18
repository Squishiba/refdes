# Pages

Narrative markdown that sits alongside your items: a board overview, an
architecture note, a "how to read this" primer.

A page is **not** an item. It has no ID, no fields, no links, no coverage, and no
traceability section. It is prose. What it does get is the same theme, the same
navigation, and — the useful part — the same cross-references, so an overview page
can mention `REQ-PWR-002` and readers get a hover preview with its current status
and check state.

## Writing one

Drop markdown in `pages/`:

```
my-board/
  refdes.yaml
  items/
  pages/
    index.md
    power-architecture.md
```

No front-matter is required. The title comes from the first `# heading`, and the
filename becomes the URL — `power-architecture.md` renders to
`power-architecture.html`.

Add front-matter only when you want to override something:

```markdown
---
title: Power architecture
order: 10
nav: true
---

# Power architecture

The 3V3 rail is the binding design problem — see REQ-PWR-002 and CON-THM-001.
```

| Key | Default | Purpose |
|---|---|---|
| `title` | first `# heading`, else filename | Nav label and page title |
| `order` | `100` | Sort position; lower comes first |
| `nav` | `true` | Set `false` to render but keep out of the nav bar |
| `board` | *(none)* | Group this page under that board's nav entry instead of the top level |

## Ordering the nav

Front-matter `order` is enough for a handful of pages. For a documentation set,
list them explicitly:

```yaml
site:
  pages: pages
  nav:
    - index
    - getting-started
    - concepts
```

Names are page slugs (the filename without `.md`). Anything unlisted follows,
sorted by `order` then title.

## Grouping a page under a board

If the project has a `boards:` registry (see [multi-board](multi-board.md)), the
nav bar already gets one group per board, listing that board's own reports —
summary, coverage, design log, references, full record. Tag a page's front-matter
`board:` with a board name and it joins that group too, instead of sitting in the
top-level list:

```markdown
---
title: Power board overview
board: power
---
```

This is what replaces a hand-written row of links at the top of a board overview
page: the nav bar already gets you there. `order` and `nav: false` still work the
same way inside a board's group as they do at the top level.

## What pages can do

- **Reference items.** Bare IDs and `[[REQ-PWR-002]]` both work, with hover
  previews, exactly as in an item body.
- **Link to each other.** Write the link as it is on disk — `[Math](math.md)` — and
  it is rewritten to `math.html` at build time. Your markdown stays readable in the
  repo and on the site.
- **All the usual markdown.** See the [markdown reference](markdown.md), including
  tables and fenced code.
- **Get an on-page contents list.** Any page with more than two `##` headings gets
  a sticky sidebar built from its headings, each with a stable anchor.

Pages do **not** get `calc` blocks evaluated — arithmetic belongs to items, where
it can be checked against a constraint.

## A pages-only project

A project with no items at all is just a website. That is how this documentation is
built:

```yaml
site:
  title: "Refdes"
  out: ../_docs
  pages: ../docs
  nav: [index, getting-started, concepts]

types:
  note:
    prefix: NOTE
    label: Note
```

With no items, the coverage page, design log, full record, and `items.json` are all
skipped, and the nav shows only your pages. A page called `index` becomes
`index.html`; if you have both pages and items, the item dashboard moves to
`items.html` so your landing page can be prose.

A schema block is still required by the config format, even when nothing uses it.

## Building it

```bash
cd docs-site && refdes build
```
