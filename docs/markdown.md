# Markdown reference

Item bodies are markdown. Everything below is verified to render — in a `.md`
file's body, or in a `body:` block in a list file.

## Standard markdown

| You write | You get |
|---|---|
| `# H1` `## H2` `### H3` | Headings |
| `**bold**` | **bold** |
| `*italic*` | *italic* |
| `` `code` `` | inline code |
| `~~struck~~` | strikethrough |
| `[text](url)` | link |
| `![alt](path)` | image — see [images and other local files](#images-and-other-local-files) below for how a local path resolves, and [width and captions](#width-and-captions) for `{width=60% caption="..."}` |
| `- item` | bullet list, nesting by indent |
| `1. item` | numbered list |
| `> quoted` | blockquote |
| `---` | horizontal rule |
| ` ```lang ` | fenced code block |
| `\| a \| b \|` | table (see below) |

A `---` only reads as the start of a new item — see [several items in one
file](authoring.md#several-items-in-one-file) — when a YAML key immediately
follows it and a closing `---` exists later. Anything else, including an ordinary
`---` before a closing paragraph, renders as a horizontal rule.

Tables use the GitHub form:

```markdown
| Pin | Net  | Current |
|-----|------|---------|
| 1   | VIN  | 1.2 A   |
| 2   | GND  | —       |
```

Wide tables scroll inside their own box rather than pushing the page sideways.

## Refdes additions

### Calc blocks

````markdown
```calc
P : W = 3.3 V * 1.2 A
```
````

Evaluated at build time and rendered as a results table. See [math](math.md).

### Inline values

```markdown
The converter loses {{P_diss}} at full load.
```

Substitutes a calc value from the same item.

### Cross-references

```markdown
The budget in BND-THM-001 drives this.        <- bare ID, autolinked
See [[REQ-PWR-002|the input range]] instead.  <- explicit, custom text
See [[fig:fig-curve]] for the efficiency curve. <- figure reference
```

Item references get hover previews. See [links](links.md). A `fig:`-prefixed
id resolves to a numbered figure instead — see [width and
captions](#width-and-captions) below.

## Images and other local files

Standard syntax: `![alt text](path/to/image.png)`. A local (non-URL) `src` is
resolved relative to **your source file's own directory** — the same base a
browser would use to open the rendered page next to its markdown source —
copied into `_site/assets/`, and its `src` in the rendered page is rewritten
to point at that copy. `figures/pattern.png` written in
`items/decisions/dec-001.md` resolves against
`items/decisions/figures/pattern.png` on disk, and ends up at
`_site/assets/items/decisions/figures/pattern.<hash>.png` — same directory
structure, a short content hash spliced into the leaf filename. The hash
changes whenever the bytes do, so editing an image and rebuilding can never
serve stale content from a browser or CDN cache under the same URL; you never
write the hashed name yourself, since refdes both resolves the source and
writes the `src=` that points at the copy. This applies to `<img src>` only —
an ordinary `[text](file.pdf)` link to a local file, or a `site.assets:`
directory linked to by hand, is not rewritten; see [`[text](file.pdf)` and
other local links](#textfilepdf-and-other-local-links) below.

A `src` that does not resolve is a **build error**, not a warning — unlike a
dangling cross-reference there is no sensible way to render a missing image,
so a broken one stops the build:

```
ERROR items/decisions/dec-001.md:2 [DEC-001] — image src 'figures/nope.png' does not exist
```

### Width and captions

A Quarto-style attribute suffix directly after the image, on the same line,
wraps it in a real `<figure>`/`<figcaption>`:

```markdown
![TPS62913 efficiency vs. load current, half-load point marked](figures/curve.png){id="fig-curve" width=60% caption="Efficiency vs. load current"}
```

`width` becomes the `<figure>`'s CSS width; `caption` becomes the caption
text, falling back to the `alt` text when omitted. `alt` always stays on the
`<img>` itself, whether or not a caption is given. With no `{...}` suffix, the
image renders exactly as it always has: a bare `<img>`, no `<figure>`
wrapper.

`id` is optional, exactly like `width`/`caption`. Give a figure one and two
things follow automatically:

- Its caption is prefixed with a number — `Figure 1 — Efficiency vs. load
  current` — computed fresh for **each rendered document it appears on**
  (its own item page, `document.html`, a per-board/per-workspace document, a
  narrative page), in that document's own reading order. The same figure is
  "Figure 1" on its own item's page and might be "Figure 7" in the combined
  `document.html` — there is no single project-wide number, because there is
  no single document.
- `[[fig:fig-curve]]` anywhere in prose resolves to a link reading `Figure N`
  (or `[[fig:fig-curve|custom text]]` for custom link text), using *that
  document's own* number — see [cross-references](#cross-references) above.
  A same-item figure reference always resolves, since an item's own figures
  are always in the same document as its own body. A cross-item reference
  only resolves in a document that contains both items at once
  (`document.html` or a per-board/per-workspace document) — from inside one
  item's own standalone page, referencing another item's figure warns and
  renders as unresolved, naming exactly why.

An `id` must be unique across the whole project — one flat namespace, the
same posture item IDs already have — since a figure can be referenced from
any item or page, not just the one it's embedded in. A duplicate is a build
error naming both locations.

### `[text](file.pdf)` and other local links

Only `<img src>` goes through the resolve-and-copy pipeline above. An ordinary
`[text](file.pdf)` link to a local file is **not** touched — its `href` is
emitted into the output HTML exactly as written, and a missing or mistyped
target gets no warning at build time, at any point.

For a handful of local files linked to by hand (a schematic PDF, a BOM
spreadsheet) rather than embedded as an image, declare an opt-in
`site.assets:` directory in `refdes.yaml` and point the link at its
destination under `assets/`:

```yaml
site:
  assets: [figures]     # every file under figures/ is copied to assets/figures/
```

```markdown
[Full schematic (PDF)](assets/figures/schematic.pdf)
```

For a **datasheet** specifically, don't hand-link it at all — see [citing a
datasheet](#citing-a-datasheet) below, which gets you a hash-pinned reference
with optional vendoring instead of a link that can silently rot.

## Citing a datasheet

A structured `citations` field type, declared per item type:

```yaml
types:
  component:
    fields:
      datasheets: { type: citations, on_change: invalidate }
```

An item declares intent only — a url, and optionally a rev, page,
part_number, and whether the bytes should be vendored:

```yaml
- id: CMP-PWR-001
  title: TPS62913 synchronous buck converter
  datasheets:
    - url: https://www.ti.com/lit/ds/symlink/tps62913.pdf
      rev: E
      page: "14"
      part_number: TPS62913
      vendor: false
```

That is all authoring requires. Everything else — the sha256, when it was
fetched, whether it was vendored — is computed by `refdes fetch`, never
written by hand:

```bash
refdes fetch                     # every citation in the project
refdes fetch --item CMP-PWR-001  # just this item's
refdes fetch --url https://...   # just this url
refdes fetch --update            # re-fetch even if already pinned
```

`refdes fetch` is the **only** command that touches the network. `build` and
`check` read only the committed lockfile (`.refdes/citations.yaml`) and the
local vendor cache, so they stay completely offline.

**Pinning vs. vendoring.** Every fetched citation is pinned: its sha256 and
fetch time are recorded in `.refdes/citations.yaml`, keyed by url, and
committed. `vendor: true` additionally keeps a local copy of the bytes,
content-addressed at `.refdes/vendor/<sha256><ext>` — gitignored, not git
LFS, not committed. `vendor:` defaults to `false` on purpose: manufacturer
datasheets are generally copyrighted, so "pinned but not vendored" (hash-only)
is a complete mode on its own, not a fallback. Citing the same url with
inconsistent `vendor:` flags across items is a warning.

**Verification**, checked at every `build` and `check`, offline:

| Situation | Severity |
|---|---|
| No lockfile entry for a cited url | info (error with `--require-citations`) — routine until `refdes fetch` runs, so it's hidden unless `-v`/`--verbose` |
| `vendor: true`, but the local blob is missing | warning (error with `--require-citations`) |
| The local blob's hash no longer matches its recorded sha256 | **error, always** |

The hash-mismatch case is never soft-failed — a corrupted or tampered local
cache is not something `--require-citations` or its absence should decide.
`refdes check --refresh` is the read-only drift scanner: it re-fetches every
pinned citation to a scratch buffer, compares hashes, and reports which items
cite anything that drifted upstream — writing nothing, exiting nonzero on
drift.

An item's citations get their own table on its page instead of showing up in
the generic field table, and every citation in the project is listed once,
grouped by url, on `references.html` (and `references-<board>.html` per
[board](multi-board.md)). See [CLI reference](cli-reference.md#refdes-fetch)
and [output formats](output.md).

## Not supported

**Raw HTML is disabled**, deliberately. A document cannot inject markup, so a
malicious or careless source file cannot break the page or the build. There is no
option to turn this on.

**Definition lists** and **footnotes** do not render — they need
`mdit-py-plugins`, which is not currently a dependency.

**Callouts** (`::: {.warning}`) are not implemented.

## Where markdown is *not* used

Field values are plain text, not markdown. A requirement's `text`, a bound's
`rationale`, and an option's `because` all render literally. If you need
formatting, put it in the body.
