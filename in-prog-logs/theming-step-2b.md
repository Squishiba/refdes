# Theming step 2b — two palettes, contrast checks, a built-in gallery

Backlog finding 34, sections 3, 4 and 6 plus the v1 scope line. Step 2a gave
`site: theme:` / `site: tokens:` a validated path from settings to a generated
`assets/theme.css`; it also left two known wrongs: every override landed in one
`:root` block, so a light-mode `--bg` beat the stylesheet's
`prefers-color-scheme: dark` block and painted dark mode too, and the four
verdict colours were refused outright because nothing could tell a re-theme
from a lie.

## What changed

**Two palettes, one file.** `theme.ThemeSpec` now carries `light` and `dark`
token dicts. `resolve()` returns `{"light": {...}, "dark": {...}}` instead of a
flat map, and `render_theme_css()` routes them:

- `:root` gets every override that is not dark-only — including a bare pair,
  which means "both palettes" and is *meant* to beat the media query;
- when the palettes disagree, `@media (prefers-color-scheme: dark) { :root {…} }`
  re-asserts the **effective dark palette** — the stylesheet's own dark values
  with the dark overrides applied — which is the bleed fix. A light-only token
  is simply absent from that map, so the stylesheet's dark value wins again;
- `[data-theme="dark"]` carries the same effective dark palette, and
  `[data-theme="light"]` the effective light one, so a host page can pin a mode
  against the OS preference in either direction;
- a theme whose overrides are all flat pairs emits exactly one `:root` block —
  no media query, no attribute selectors — because there is nothing to route.

**`data-theme` is new, not pre-existing.** The task brief expected the site to
already use a `data-theme="dark"` selector. It does not: `style.css` has only
the media query, and nothing in the repo ever set the attribute. So the
selector is introduced here as an *emitted convention* — refdes itself never
writes the attribute onto `<html>` — documented in `docs/output.md` and
`docs/themes.md` as the hook a host page (the future editor, a reader toggle)
sets. Emitting blocks nobody can trigger is deliberate: they cost nothing when
unused and the alternative is re-cutting the stylesheet when the editor lands.

**Bare tokens apply to both palettes.** The open question from the brief. Kept
as-is: `--bg: "#fffdf0"` means both, which is what 2a authors wrote and what
"override the token" reads like. Targeting one palette requires the `light:` /
`dark:` headings, and a block that uses a heading may contain nothing else —
mixing them is an error rather than a precedence puzzle.

**Contrast checking** lives in `refdes/contrast.py`: WCAG relative luminance,
the ratio, an HSL hue, and `palette_violations()` over the semantic pairs —
`--fg`, `--muted`, `--accent`, `--good`, `--bad`, `--warn`, `--claim` against
`--bg`, and the verdict/accent colours against `--panel` as well. Plus the
`--bad`/`--good` rule: 90 degrees of hue separation, or 4.5:1 between them.
Both thresholds are module constants and the docs page quotes them from the
module, so the page cannot drift from the checker.

Non-hex values are skipped silently. A named colour, an `rgb()`, a `var()`
chain — parsing those would mean guessing, and a warning about a colour the
checker invented is worse than no check.

**Severity.** A *built-in* theme that fails is a test failure
(`check_builtin_themes()` asserted in `tests/test_theme.py`), not a runtime
crash: the built-ins ship, so their legibility is refdes's responsibility. A
*project's* overrides failing is `project.warn` — the site still builds. The
threshold is a floor, not a law, and an author with a reason should be able to
proceed while knowing exactly which pair and what ratio.

**Three built-ins**: `high-contrast` (pure black/white, darkened verdicts, a
line token you can actually see), `paper` (cream, brown-black ink, earthen
verdicts), `slate` (blue-grey, teal accent). All four themes including
`default` pass all thirteen pairs at 4.5:1 in both palettes and the bad/good
rule; the colours were picked by computing ratios before writing them down, and
the test re-computes them on every run.

**The gallery** is `docs/themes.md`, written whole by
`docs-site/gen_themes.py` from `BUILTIN_THEME_LIST` — the same objects
`site: theme:` resolves. `tests/test_themes_page.py` asserts the committed page
equals generator output, lists every built-in, and checks the thresholds quoted
in prose are the ones `refdes.contrast` uses. It is tables of hex values, not
live swatches: the docs renderer runs markdown-it with `html: False`, so
inline style chips are escaped and data-URI images are rejected by the link
validator. A real swatch would mean generating image files into
`docs-site/images/`, which is a step-3 idea, not a reason to hand-write a page
that can lie.

## Deliberate non-goals

No theme files, no `@theme` format, no remote themes, no per-page themes, no
selector or nesting in a token value — the 2a containment rules are unchanged
and the new headings are the only nesting that exists. `default` still emits
no `theme.css` at all, and the byte-identity test for an un-themed build is
untouched and still green.

## Verification

`python -m pytest -q` — 1792 passed. `ruff --select E9,F src/ docs-site/
tests/` clean.
