# Themes

A site's look is a **theme**: two palettes of custom properties --
one for light mode, one for dark -- merged over the values the shipped
stylesheet declares. `site: theme:` selects a built-in by name;
`site: tokens:` overrides individual properties on top of it. Either
way the build writes one extra stylesheet, `assets/theme.css`, and the
pages link it after the main one.

## The built-in gallery

Every built-in below passes the WCAG AA contrast checks in **both**
palettes -- asserted by `tests/test_theme.py`, so a palette edit that
drops a pair below the minimum fails the suite instead of shipping an
unreadable site. The tables are the *effective* palettes (the theme's
overrides merged over the stylesheet's own values), written from
`refdes.theme.BUILTIN_THEME_LIST` by `python docs-site/gen_themes.py`.
Do not hand-edit them: `tests/test_themes_page.py` fails if this page
differs from what the generator produces today. The checks are a
4.5:1 contrast minimum on every semantic
pair, and between `--bad` and `--good` a
90-degree hue separation (or
4.5:1 contrast), so a colour-blind
reader can tell a pass from a fail at a glance.

## `default`

Today's look: the shipped stylesheet's own palette. Selecting it emits no stylesheet at all.

```yaml
site:
  theme: default
  # the shipped palette; selecting it emits no theme.css
```

This theme overrides nothing: the shipped stylesheet *is* the palette, so selecting it emits no `theme.css` at all.

## `high-contrast`

Maximum legibility: pure black on white and white on black, darkened verdict colours, and a strong visible line token.

```yaml
site:
  theme: high-contrast
```

| token | light | dark |
| --- | --- | --- |
| `--bg` | `#ffffff` | `#000000` |
| `--fg` | `#0a0a0a` | `#ffffff` |
| `--muted` | `#4f5358` | `#b6bec7` |
| `--line` | `#7d838b` | `#8a929c` |
| `--panel` | `#f2f2f2` | `#101214` |
| `--accent` | `#0b4a9e` | `#8ab8ff` |
| `--good` | `#056837` | `#4fd186` |
| `--bad` | `#a01510` | `#ff8a80` |
| `--warn` | `#6b4a00` | `#ffd166` |
| `--claim` | `#5b2ea6` | `#cdaaff` |

## `paper`

Warm ink-on-paper: cream surfaces, brown-black text, and earthen verdict colours that stay legible in both palettes.

```yaml
site:
  theme: paper
```

| token | light | dark |
| --- | --- | --- |
| `--bg` | `#faf6ee` | `#1c1814` |
| `--fg` | `#2b2620` | `#ece3d3` |
| `--muted` | `#6b5f4f` | `#b3a68f` |
| `--line` | `#ddd2bf` | `#4a4136` |
| `--panel` | `#f2ead9` | `#26211a` |
| `--accent` | `#9a4b1f` | `#e0a35c` |
| `--good` | `#3f6b2f` | `#8fc47e` |
| `--bad` | `#a02c1d` | `#f0806c` |
| `--warn` | `#7a5c00` | `#e6c260` |
| `--claim` | `#6f459e` | `#c9a6e8` |

## `slate`

Cool blue-grey: a blueprint feel, teal accent, and the verdict hues kept far apart so strips read at a glance.

```yaml
site:
  theme: slate
```

| token | light | dark |
| --- | --- | --- |
| `--bg` | `#f5f7fa` | `#101820` |
| `--fg` | `#1b2733` | `#dfe7ee` |
| `--muted` | `#5c6b7a` | `#93a5b5` |
| `--line` | `#ccd6e0` | `#2c3a48` |
| `--panel` | `#eaeff5` | `#17222c` |
| `--accent` | `#15616d` | `#64b6c4` |
| `--good` | `#166b52` | `#5fc99a` |
| `--bad` | `#b3261e` | `#ff8a7a` |
| `--warn` | `#8a5a00` | `#e8bd58` |
| `--claim` | `#5b4bc4` | `#a8a0f0` |

## Writing your own

`site: tokens:` takes the stylesheet's custom properties directly. A
bare `--token: value` pair applies to **both** palettes; nesting under
the `light:` and `dark:` headings targets one of them.

```yaml
site:
  theme: paper
  tokens:
    --accent: '#8a1010'   # both palettes
```

Or target one palette at a time, with the two headings and nothing
else in the block:

```yaml
site:
  theme: paper
  tokens:
    light:
      --bg: '#fffdf7'     # light mode only
    dark:
      --bg: '#17140f'     # dark mode only
```

Mixing the two forms in one `tokens:` block is a load-time error, so an
author never has to work out which of two equally valid-looking
overrides won.

A light-only override no longer bleeds into dark mode: the build
re-asserts the effective dark palette inside the dark blocks, so the
two palettes stay independent. Values are validated the same way in
both forms -- a bare token name, an empty value, a value over
200 characters, or one containing a brace,
a `</style>`, or a `url(`/`expression(` is a schema error.

### Contrast

Every semantic pair in a project's effective palettes is checked at
load time: foreground, muted, accent and the four verdict colours
against `--bg` and, where applicable, `--panel`, plus the `--bad` /
`--good` distinguishability rule. A failing pair is a **warning**, not
an error -- `refdes build` still produces the site -- because the
threshold is a floor, not a law, and an author may have a reason. What
it is not is silent: the warning names the pair, the two values, and
the ratio it measured.

Non-hex values (named colours, `rgb()`, another `var()`) are skipped:
guessing at a colour the checker cannot parse would warn about colours
that are fine, which is worse than not checking.

### Forcing a palette

The stylesheet follows the reader's OS preference. A host page that
wants to pin one -- the editor, or a project that ships a toggle --
sets `data-theme="light"` or `data-theme="dark"` on `<html>`; the
generated `theme.css` carries matching attribute blocks that win over
the media query in both directions.
