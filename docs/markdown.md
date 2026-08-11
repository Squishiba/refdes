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
The budget in CON-THM-001 drives this.        <- bare ID, autolinked
See [[REQ-PWR-002|the input range]] instead.  <- explicit, custom text
```

Both get hover previews. See [links](links.md).

## Images and other local files

Standard syntax: `![alt text](path/to/image.png)`. A local (non-URL) `src` is
resolved relative to **your source file's own directory** — the same base a
browser would use to open the rendered page next to its markdown source —
copied into `_site/assets/`, and its `src` in the rendered page is rewritten
to point at that copy. `figures/pattern.png` written in
`items/decisions/dec-001.md` resolves against
`items/decisions/figures/pattern.png` on disk, and ends up at
`_site/assets/items/decisions/figures/pattern.png`, mirroring the same path
under `assets/` — no manual copy step, and no mismatch between what the build
checked and what the browser requests.

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
![TPS62913 efficiency vs. load current, half-load point marked](figures/curve.png){width=60% caption="Figure 3 — efficiency vs. load current"}
```

`width` becomes the `<figure>`'s CSS width; `caption` becomes the caption
text, falling back to the `alt` text when omitted. `alt` always stays on the
`<img>` itself, whether or not a caption is given. Figure numbering is not
automatic — write `Figure 3 —` as literal caption text, same as you would in
prose. With no `{...}` suffix, the image renders exactly as it always has: a
bare `<img>`, no `<figure>` wrapper.

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
| No lockfile entry for a cited url | warning (error with `--require-citations`) |
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

**Callouts** (`::: {.warning}`) and **automatic figure numbering /
cross-references to figures** are not implemented. These are the most likely
next additions.

## Where markdown is *not* used

Field values are plain text, not markdown. A requirement's `text`, a constraint's
`rationale`, and an option's `because` all render literally. If you need
formatting, put it in the body.
