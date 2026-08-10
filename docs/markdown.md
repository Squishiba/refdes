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
| `- item` | bullet list, nesting by indent |
| `1. item` | numbered list |
| `> quoted` | blockquote |
| `---` | horizontal rule |
| ` ```lang ` | fenced code block |
| `\| a \| b \|` | table (see below) |

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
