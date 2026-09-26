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
```calc id="losses"
P = 3.3 V * 1.2 A | W
```
````

Evaluated at build time and rendered as a results table. See [math](math.md).

The fence info string — everything between ```` ```calc ```` and the newline —
is meaningful: `id="..."` names the block (see [naming a calc
block](math.md#naming-a-calc-block)). Anything else there is a **build error**
at the fence line, not text that is quietly ignored: a bare word, an unquoted
value, an unknown attribute, or a name outside the lowercase grammar each gets
a message naming the fix (see [troubleshooting](troubleshooting.md)).

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
See [[CMP-001#part_number]] for the MPN.       <- explicit, one field on that page
See [[cite:tps62913-ds]] for the datasheet.    <- citation reference
```

Item references get hover previews. See [links](links.md). A `fig:`-prefixed
id resolves to a numbered figure instead, and a `cite:`-prefixed id resolves
to a citation — see [width and captions](#width-and-captions) and [citing a
datasheet](#citing-a-datasheet) below.

A `#field` fragment links to **one field's row** on the target item's page. It
is a link, not a substitution: the field's value is never copied into your
prose, so it cannot go stale under you. The link text is `ID#field` unless you
give a `|label`. The field must be declared on the target item's type — one
that isn't is a warning naming the item, the field, and the type, and renders
in red like any other unresolved reference. A field that is declared but empty
on that item links fine — you land on a collapsed empty row where the row would
have been. And a field whose content is shown in its own section rather than a
table row (`options`, `checks`, a citations field) links to **that section**, so
the fragment lands on the content, not on the table.

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
other local links](#text-file-pdf-and-other-local-links) below.

An image's bytes are content, not just cache material: since hash format 5 the
file behind every local image an **item body** references contributes its path
and content digest to that item's [content hash](change-tracking.md). Swapping
the bytes of `pattern.png` moves the hash of every item that references it, so
sealed entries and baselines notice an image swap instead of quietly displaying
a different figure. URL images contribute nothing, and an item that references
no image hashes exactly as before.

A `src` that does not resolve is a **build error**, not a warning — unlike a
dangling cross-reference there is no sensible way to render a missing image,
so a broken one stops the build:

```
ERROR items/decisions/dec-001.md:2 [DEC-001] — image src 'figures/nope.png' does not exist
```

### A bare filename, found on the search path

A `src` written as a **bare filename** — no `/` in it — that does not resolve
beside its own source file is looked up in the directories your
`site.assets:` list already declares:

```yaml
site:
  assets: [figures, photos/shared]
```

```markdown
![Thermal curve](curve.png)     # found at figures/curve.png
```

The rule is `#include <foo.h>` in C++: only the declared directories are
searched, never the project tree as it happens to be arranged. Three things
follow from that, and all three are deliberate:

- **A path that resolves relative to your source file always wins.** The
  search runs only after that lookup fails, so every image that works today
  keeps working identically — even if the same filename also sits on the
  search path.
- **Only a bare filename is searched.** `figures/curve.png` was written as a
  specific location; if it does not exist you get the plain does-not-exist
  error above, never a leaf-name match on some unrelated file elsewhere.
- **Two matches is a build error, not a tie-break.** A name found in more
  than one declared directory refuses, naming every candidate:

  ```
  ERROR items/decisions/dec-001.md:4 [DEC-001] — image src 'curve.png' is ambiguous: it exists in more than one site.assets directory (figures/curve.png, photos/shared/curve.png). Write the path relative to items/decisions/dec-001.md instead of the bare filename, or rename one of them
  ```

  There is no first-declared, newest-file, or alphabetical winner, because
  every such rule is invisible to whoever reads the document. Two same-named
  files that no image actually references are not an error — the refusal
  happens at the reference, not at the collision.

A searched image is copied into `_site/assets/` and rewritten like any other
(see above — including the `site.assets:` rule that a file inside a declared
asset directory is copied verbatim rather than content-hashed), and it takes
`{width=... caption="..."}` attributes exactly as a relative-path image does.
What the search does *not* buy you: an asset identity. The lookup happens on
every build, so adding a second file with the same name under a declared
directory turns an existing, unmodified document's image into the ambiguity
error above — which is the point of erroring rather than picking. If you want
the reference pinned so it can never drift, write the relative path.

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

A `<figure>` needs a paragraph of its own. Where the same suffix lands on an
image that is **not** alone in its paragraph — inline with a sentence, in a
list item, in a table cell — there is nothing to wrap, so the suffix is never
left on the page as literal text: `width` is applied to the `<img>` itself,
and `caption`/`id`, which only mean something on a `<figure>`, are dropped
with a warning naming file:line and item id and telling you to put the image
in a paragraph of its own. An unknown attribute name warns the same way.
Braces that aren't an attribute suffix at all — `the set {a, b}` — are
ordinary prose and are never touched.

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
`site.assets:` directory in `refdes-project.yaml` and point the link at its
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
with an optional local copy instead of a link that can silently rot.

## Citing a datasheet

A structured `citations` field type, declared per item type:

```yaml
types:
  component:
    fields:
      citations: { type: citations, on_change: invalidate }
```

An item declares intent only — a path, and optionally a rev, page,
part_number, id, and kept locally:

```yaml
- id: CMP-PWR-001
  title: TPS62913 synchronous buck converter
  citations:
    - path: https://www.ti.com/lit/ds/symlink/tps62913.pdf
      rev: E
      page: "14"
      part_number: TPS62913
      keep_copy: false
      id: tps62913-ds
```

`path:` is one field dispatched on scheme. `http:`/`https:` means remote —
fetched, hashed, optionally kept, exactly as before. Anything else means
**a file inside the project**, relative to the project root (the directory
holding `refdes-project.yaml`), slash-separated:

```yaml
- id: CMP-MECH-001
  title: Board outline
  citations:
    - path: docs/mech/board-outline.pdf
      rev: "2"
```

The file itself is the artifact: `refdes fetch` reads it from disk (no
network), every build re-hashes it against the pin, and the pinned bytes are
published with the site as `assets/citations/<sha256><ext>` so the rendered
link survives a Linux CI checkout — absolute paths, drive letters,
backslashes, `..` escapes, symlinks pointing out of the project, and
`keep_copy:` on a local path are all refused, never guessed. A local file that
changed since it was pinned is a warning naming every citer (review, then
`refdes fetch --update --path <path>`), an error with `--require-citations`;
a cited file that doesn't exist is an error, always.

### Citing a section by name

`page:` is a number you looked up by hand and re-check every revision.
`section:` is the same citation written the way you actually think about it —
the title of a heading in the document:

```yaml
- id: CMP-PWR-001
  title: TPS62913 synchronous buck converter
  citations:
    - path: https://www.ti.com/lit/ds/symlink/tps62913.pdf
      section: Application and Implementation
      keep_copy: true
      id: tps62913-ds
```

`refdes fetch` reads the PDF's own outline (its bookmarks) and records which
page that title points at, in the lockfile alongside the sha256. Builds never
open a PDF — they read the recorded page — so `build` and `check` stay offline
and hermetic exactly as before. The resolved page fills the same two places
`page:` does: the `#page=N` fragment on the link, and the Page column of the
citations table.

Titles are matched exactly and case-sensitively, after whitespace is collapsed
(a heading the outline stored across two lines is one title). Nothing is fuzzy:
a title that isn't in the outline is an error, not a guess. Resolution needs the
bytes, so `section:` is allowed on a local `path:` citation and on a remote one
with `keep_copy: true`; on a hash-only remote citation it is refused at build time,
because those bytes are not guaranteed to be there next time.

Resolving is never silent. `refdes fetch` prints a `FAILED` line and exits
nonzero — naming the path, the section, and every item that cites it — when:

| Situation | What the line says |
|---|---|
| The PDF has no outline at all | `has no outline (bookmarks); section: cannot be resolved` — cite `page:` instead |
| No entry has that title | `no outline entry titled '…'`, plus the closest titles it did find |
| Two entries have that title | every page it is on — the document is ambiguous, and taking the first would be a guess |
| The PDF extra isn't installed | `section: needs the optional PDF extra: pip install refdes[pdf]` |
| pypdf can't parse the file | the file and pypdf's own message, never a traceback |
| `--update`, and the title is gone from the new revision | `the section you cited no longer exists in the new revision (was page N)` |
| the local file moved since it was pinned, and `--update` was not given | `the file on disk changed since it was pinned; run 'refdes fetch --update --path …'` |

A failed lookup does not undo the pin — the fetch succeeded, the lookup didn't.
A section that fails to resolve is dropped from the lockfile rather than left
pointing at a page the new bytes may not have.

**A page belongs to the bytes it was read out of.** The lockfile records the
sha256 the pages were resolved against (`sections_sha256`) next to the pages
themselves, and `build` uses a page only while that still matches the sha256 now
pinned. If it does not — a hand-edited lockfile, a record from before a re-pin —
the build warns and links the document with no page, because a page number from
another revision is a wrong link, not a near miss. The same rule is why a
re-pin re-resolves **every** section any item cites for that path, including
sections belonging to items outside the run's `--item`/`--path` scope: scoping a
fetch narrows which paths are re-pinned, it cannot narrow what re-pinning them
means. Carrying an old page across a sha change is the one thing that would let
`refdes fetch --update --item CMP-PWR-001` silently leave some other item's
citation pointing into the wrong page of the file it just replaced. A section
that stopped being cited stops being recorded — it is a derived value, not a
ledger entry.

`page:` and `section:` on one citation are not an error, but they have to agree:
if both are present and the resolved page differs, `build` warns naming both and
**`page:` wins** — an explicit page is a decision, a resolved title is an
inference.

`id` is optional, exactly like a figure's `id=` — give a citation one and
`[[cite:tps62913-ds]]` anywhere in prose (or `[[cite:tps62913-ds|the
datasheet]]` for custom text) links straight to **that citation's row** on
`CMP-PWR-001`'s own page, the item that declared it — never to
`references.html`, which groups by path across every citer instead of naming
one entry. It must be unique across the whole project — one flat namespace,
the same posture figure ids and item ids already have — since it can be
referenced from any item or page, not just the one that declared it. A
duplicate is a build error naming both locations; an id outside
letters/digits/`-`/`_` is rejected at declaration, since it could never be
addressed by `[[cite:...]]` anyway; an unresolved `[[cite:...]]` is a warning
and renders in red, same as any other unresolved reference.

That is all authoring requires. Everything else — the sha256, when it was
fetched, whether it was kept — is computed by `refdes fetch`, never
written by hand:

```bash
refdes fetch                     # every citation in the project
refdes fetch --item CMP-PWR-001  # just this item's
refdes fetch --path docs/sch.pdf   # just this one cited path
refdes fetch --update            # re-fetch even if already pinned
```

`refdes fetch` is the **only** command that touches the network. `build` and
`check` read only the committed lockfile (`.refdes/citations.yaml`) and the
local copies, so they stay completely offline.

**Pinning vs. keeping a copy.** Every fetched citation is pinned: its sha256 and
fetch time are recorded in `.refdes/citations.yaml`, keyed by path, and
committed. `keep_copy: true` additionally keeps a local copy of the bytes,
content-addressed at `.refdes/copies/<sha256><ext>` — gitignored, not git
LFS, not committed. `keep_copy:` defaults to `false` on purpose: manufacturer
datasheets are generally copyrighted, so "pinned but not kept" (hash-only)
is a complete mode on its own, not a fallback. Citing the same remote path with
inconsistent `keep_copy:` flags across items is a warning.

**Verification**, checked at every `build` and `check`, offline:

| Situation | Severity |
|---|---|
| No lockfile entry for a cited path | info (error with `--require-citations`) — routine until `refdes fetch` runs, so it's hidden unless `-v`/`--verbose` |
| `keep_copy: true`, but the local blob is missing | warning (error with `--require-citations`) |
| The local blob's hash no longer matches its recorded sha256 | **error, always** |
| A cited local file doesn't exist | **error, always** |
| A cited local file changed since it was pinned | warning naming every citer (error with `--require-citations`) |
| A `section:` with no resolved page in the lockfile — never fetched, or fetched without `refdes[pdf]` installed | warning naming every citer (error with `--require-citations`) |

The hash-mismatch case is never soft-failed — a corrupted or tampered local
cache is not something `--require-citations` or its absence should decide.
`refdes check --refresh` is the read-only drift scanner: it re-fetches every
pinned citation to a scratch buffer, compares hashes, and reports which items
cite anything that drifted upstream — writing nothing, exiting nonzero on
drift.

An item's citations get their own table on its page instead of showing up in
the generic field table, and every citation in the project is listed once,
grouped by path, on `references.html` (and `references-<board>.html` per
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

Field values are plain text, not markdown. A requirement's `body`, a bound's
`rationale`, and an option's `because` all render literally. If you need
formatting, put it in the body.
