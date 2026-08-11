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
| `![alt](path)` | image — see [images and other local files](#images-and-other-local-files) below before relying on this for a local file |
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
checked for existence at build time and warns if the file is missing:

```
WARNING items/decisions/dec-001.md:2 [DEC-001] — image src 'figures/nope.png' does not exist
```

That check is the only thing `refdes build` does with local images. It does not
copy them into `_site/`, rewrite their paths, or support width, caption, or
figure numbering — the `src` you write is emitted into the output HTML
unchanged, and the same is true of `href` on an ordinary `[text](file.pdf)` link
to a local PDF or any other local file.

**This means an image or PDF that passes validation can still 404 in the built
site**, because the existence check and the browser resolve the path against two
different locations. The check resolves `src` relative to **your source file's
own directory** — `figures/pattern.png` written in
`items/decisions/dec-001.md` is checked against
`items/decisions/figures/pattern.png`. But every page in `_site/` is flat
(`dec-001.html`, not `decisions/dec-001.html`), and a browser resolves a
relative `src` against the *page's* location, not your source tree — so unless
you separately arrange for a copy of the file to exist next to the HTML at that
same relative path, the browser request 404s even though the build was silent.

A `[text](file.pdf)` link never gets even that much: `_validate_images` only
matches `<img>` tags, so a missing or mistyped local file behind a plain link
gets no warning at all, at build time or otherwise.

### What actually works today

Copy the files into `_site/` yourself, after each build, at the path you used
in `src=`/`href=` — treat that path as relative to `_site/`, not to your source
file. The simplest way to keep this tractable is to write every image and PDF
path the same way regardless of which `items/` subfolder the markdown lives in
(say, `figures/whatever.png`), so one copy step covers every item:

```bash
refdes build && cp -r figures _site/figures
```

This survives repeated builds — `refdes build` only ever deletes output files it
wrote itself and tracked in its own manifest, never a folder it didn't write —
so the copy does not need to be redone unless the source files change.

There is no structured citation type for datasheets (revision, page, hash
fields). Cite one in prose with a normal link instead:
`[TPS62913 datasheet rev C, p.14](figures/tps62913.pdf)`.

## Not supported

**Raw HTML is disabled**, deliberately. A document cannot inject markup, so a
malicious or careless source file cannot break the page or the build. There is no
option to turn this on.

**Definition lists** and **footnotes** do not render — they need
`mdit-py-plugins`, which is not currently a dependency.

**Callouts** (`::: {.warning}`), **figures with numbered captions**, and
**cross-references to figures** are not implemented. These are the most likely
next additions.

## Where markdown is *not* used

Field values are plain text, not markdown. A requirement's `text`, a constraint's
`rationale`, and an option's `because` all render literally. If you need
formatting, put it in the body.
