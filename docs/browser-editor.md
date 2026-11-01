# The browser editor

`refdes serve` serves your built project as a static site *and* an editor
at `/edit/`. The editor is plain JavaScript and CSS shipped with refdes —
no Node, no build step — and every save goes through the same validation
the build runs, so the editor cannot put your project into a state the
build rejects. The command itself, the token-protected launch URL, and the
watch-and-rebuild behaviour are in the [CLI
reference](cli-reference.md#refdes-serve).

This page is the guide to the editing surface: the formatting bar, the
refdes insertion buttons, the live calc panel, the font setting, and what
the editor refuses to save.

## Opening an item

The launch URL from `refdes serve` opens the site; the editor lives at
`/edit/` on the same port. The item view is one page — a form for the open
item, with the body textarea, the formatting bar above it, and the Save /
Discard controls below it. The item list, the filters, and the **New item**
form (see [authoring](authoring.md) for what each field means) share the
page.

The create form has no formatting bar: the body there is a plain textarea.

## Formatting buttons

The bar sits directly above the body textarea. Eleven buttons cover the
markdown every body uses (all syntax is in the [markdown
reference](markdown.md)):

| Button | With a selection | With the caret only |
|---|---|---|
| **B** / **I** / **S** / **code** | wraps the selection in `**` / `*` / `~~` / `` ` `` | inserts the markers around a placeholder (`bold text`, `italic text`, `text`, `code`) with the placeholder selected, so you can type over it |
| **H** | cycles the line's heading level: none → `#` → `##` → … → six → none | same, on the caret's line |
| **•** / **1.** / **❝** | prefixes every line the selection touches with `- ` / `1. ` / `> `; pressing again removes it | same, on the caret's line |
| **Link** | wraps: `[selection](url)` with `url` selected; if the selection is itself an `http(s)://` URL, it becomes the target and `link text` is selected | inserts `[link text](url)` with `url` selected |
| **Table** | inserts a three-row skeleton (`| a | b |`, a separator row, an empty row) as its own block, with the first cell's `a` selected | same |
| **HR** | inserts `---` as its own block | same |

Wrapping is layer-aware: a selection (or caret pair) that already carries
the marker removes one layer instead of adding a second, so **B** on
`**word**` unwraps to `word`.

Inline buttons wrap the exact selection. Block inserts (Table, HR, the calc
fence skeleton) go in as their own paragraph, padded with blank lines — and
when the caret sits *inside* a fenced code block, a block insert lands
after the block's closing fence, so fences stay balanced.

Keyboard shortcuts, handled while the body textarea is focused:
**Ctrl/Cmd+B** (bold), **Ctrl/Cmd+I** (italic), **Ctrl/Cmd+K** (link),
**Alt+Shift+5** (strikethrough). There are no shortcuts for the heading,
list, quote, table, or rule buttons. Every insertion — button, shortcut, or
picker — goes into the textarea the way typing does, so the browser's own
**Ctrl+Z** undoes it as a single step.

## refdes buttons

Seven more buttons sit in the same bar, visually separated. They insert the
project's own syntax (the full syntax is in [markdown](markdown.md) and
[math](math.md)):

- **`[[ID]]`** opens a picker over every item in the project: a
  `filter items…` box, one row per item labelled `ID — title`. Type to
  filter, use arrow keys and Enter to pick (Escape closes; focus always
  returns to the textarea). A pick inserts `[[ID]]` at the caret, or
  `[[ID|your text]]` when text was selected — a labelled cross-reference,
  as in [links](links.md).
- **`[[fig:]]`** inserts a figure reference with the caret between the
  brackets, so you can type the image name.
- **`calc`** inserts a calc fence skeleton as its own block:

  ````text
  ```calc
  name = expr | V
  ```
  ````

  with `name` selected, so typing names it.
- **`:=`** inserts an inline calc span skeleton `` `name := 0 | V` `` with
  `name` selected.
- **`{{}}`** inserts a calc value reference with the caret inside the
  braces.
- **Image** and **Source** don't insert anything: they open and focus the
  images panel and the sources panel below the textarea — the image picker
  and uploader ([markdown](markdown.md#uploading-an-image-from-the-browser-editor))
  and the source-value composer
  ([markdown](markdown.md#picking-a-source-value-in-the-browser-editor)).

### The skeleton save gate

The calc skeletons are deliberately *invalid* until you fill them in, and
saving with them unfilled is refused — you cannot save a `name = expr`
calc into your project. Save shows the build's own message:

```text
blocked: the edit would leave 1 error(s): calc 'name': unknown name 'expr'
```

for the fence, and

```text
blocked: the edit would leave 1 error(s): inline calc name := 0 | V:
stored result missing; write '= <quantity>'
```

for the span, with the offending line listed. The status stays `unsaved`,
the file on disk keeps its old bytes, and filling in the name (and, for the
span, a stored result `= <value>`) makes the save go through.

## Live calc panel

An item body containing inline calc spans gets a **Live inline calc** panel
next to the textarea. As you type, the panel evaluates every span in the
draft and shows one row per span with the computed result:

- a green **ok** chip when the span's stored result matches,
- an **error** chip with the build message when the span can't be evaluated
  (an unfilled skeleton shows `stored result missing; write '= <quantity>'`),
- a **stale** chip — `stored result says 5 V, now computes 4 V` — when the
  stored result has fallen behind the expression.

The `update results while I type` checkbox is on by default: when a span
becomes stale, the panel rewrites the stored result in the textarea for
you, after you pause typing (~0.4 s). Turn the checkbox off and each stale
row grows a **Fill** button, which applies the same rewrite to that span
alone. Rows are display and drafts only — nothing reaches the file until
you press **Save**.

## Font setting

The **Font** button beside the bar opens the `Editor font setting` popover:
the body editor's **family** (Mono, Sans, Serif), **size** (11–20 px,
default 12), and **line height** (Compact 1.35, Normal 1.5, Loose 1.7).
The setting is personal, not project data: it lives in the browser's
`localStorage`, applies to every item you edit, and survives reloads. A
corrupted stored value falls back to the defaults.

## Draft, save, discard

The status beside Save reads `saved` or `unsaved`. Everything you type,
click, or insert accumulates as a draft; **Save** writes it through the
server (one save per item, per edit you made) and the status returns to
`saved`. A draft survives a page reload — it is kept in the browser tab's
session — and **Discard** restores the saved text.

Saves are refused, with the reason shown in the editor, when the project is
[sealed or imported](design-log.md), when the file changed on disk
underneath the open form (the conflict panel shows your draft against what
is there now), and when the edit would leave the build failing — including
the skeleton gate above.

## Read-only items

A sealed [design-log entry](design-log.md) opens with no editing surface at
all: no formatting bar, no textarea, no Font button, no Save. The body
renders as static text and the item carries a `sealed — read only` badge
with the reason: *a sealed entry is append-only: a correction is a new
entry, not this edit.*

## Where it is verified

The editor is exercised in automated checks on Chromium and Firefox; the
behaviours above were re-verified in both on a live `refdes serve`
instance, including the native-undo single-step insertions, the font
round-trip, the skeleton save gate, the live-calc panel, and the read-only
rendering.
