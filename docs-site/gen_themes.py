"""Generate docs/themes.md, the built-in theme gallery.

Backlog finding 34 step 2b: three built-in themes besides `default`, each
passing the WCAG contrast checks in *both* palettes. A gallery page that
restates those palettes by hand is a page waiting to lie, so the tables here
are written from `refdes.theme.BUILTIN_THEME_LIST` itself -- the same objects
`site: theme:` resolves and the same palettes `tests/test_theme.py` audits.
Change a palette in `theme.py`, re-run this script, and the page changes with
it; leave it stale and `tests/test_themes_page.py` fails.

Run `python docs-site/gen_themes.py` to write the page, or with `--check` to
fail if the committed page differs from generator output.

The swatch tables list the *effective* palette -- the stylesheet's own value
merged with whatever the theme overrides -- because that is what a reader
would actually see on the page. Colour tokens only; type, spacing and radii
tokens are shared by every theme and restating them four times would be noise.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from refdes import theme as theme_mod  # noqa: E402
from refdes import contrast as contrast_mod  # noqa: E402

TARGET_DOC = os.path.join(ROOT, "docs", "themes.md")

# The colour tokens the gallery shows, in the order the stylesheet declares
# them. `color_token_names()` reads them out of style.css, so a token added to
# the stylesheet appears here without an edit -- and a token only some themes
# set still gets a row, filled with the stylesheet's own value.


def _effective(spec: theme_mod.ThemeSpec) -> dict[str, dict[str, str]]:
    """The theme's effective light and dark colour palettes."""
    names = theme_mod.color_token_names()
    base_light = theme_mod.default_tokens()
    base_dark = theme_mod.default_dark_tokens()
    return {
        "light": {name: spec.light.get(name, base_light.get(name, "")) for name in names},
        "dark": {name: spec.dark.get(name, base_dark.get(name, base_light.get(name, ""))) for name in names},
    }


def _snippet(spec: theme_mod.ThemeSpec) -> str:
    """The `site:` block a reader copies to select this theme."""
    lines = ["site:", f"  theme: {spec.name}"]
    if spec.name == theme_mod.DEFAULT_THEME:
        # `default` is the value a project gets by writing nothing, so the
        # snippet says so rather than implying a stylesheet is emitted.
        lines.append("  # the shipped palette; selecting it emits no theme.css")
    return "\n".join(lines)


def _table(effective: dict[str, dict[str, str]]) -> list[str]:
    lines = [
        "| token | light | dark |",
        "| --- | --- | --- |",
    ]
    for name in theme_mod.color_token_names():
        lines.append(
            f"| `{name}` | `{effective['light'][name]}` | `{effective['dark'][name]}` |"
        )
    return lines


def render_page() -> str:
    """The whole themes.md, generated."""
    problems = theme_mod.check_builtin_themes()
    if problems:
        # A built-in that fails its own contrast audit should stop the docs
        # generator, not print a gallery of unreadable palettes.
        detail = "; ".join(f"{theme}: {why}" for theme, why in problems)
        raise SystemExit(f"built-in themes fail the contrast checks -- {detail}")

    lines = [
        "# Themes",
        "",
        "A site's look is a **theme**: two palettes of custom properties --",
        "one for light mode, one for dark -- merged over the values the shipped",
        "stylesheet declares. `site: theme:` selects a built-in by name;",
        "`site: tokens:` overrides individual properties on top of it. Either",
        "way the build writes one extra stylesheet, `assets/theme.css`, and the",
        "pages link it after the main one.",
        "",
        "## The built-in gallery",
        "",
        "Every built-in below passes the WCAG AA contrast checks in **both**",
        "palettes -- asserted by `tests/test_theme.py`, so a palette edit that",
        "drops a pair below the minimum fails the suite instead of shipping an",
        "unreadable site. The tables are the *effective* palettes (the theme's",
        "overrides merged over the stylesheet's own values), written from",
        "`refdes.theme.BUILTIN_THEME_LIST` by `python docs-site/gen_themes.py`.",
        "Do not hand-edit them: `tests/test_themes_page.py` fails if this page",
        "differs from what the generator produces today. The checks are a",
        f"{contrast_mod.MIN_CONTRAST}:1 contrast minimum on every semantic",
        "pair, and between `--bad` and `--good` a",
        f"{contrast_mod.MIN_BAD_GOOD_HUE_DEGREES:.0f}-degree hue separation (or",
        f"{contrast_mod.MIN_BAD_GOOD_CONTRAST}:1 contrast), so a colour-blind",
        "reader can tell a pass from a fail at a glance.",
        "",
    ]
    for spec in theme_mod.BUILTIN_THEME_LIST:
        lines.append(f"## `{spec.name}`")
        lines.append("")
        if spec.description:
            lines.append(spec.description)
            lines.append("")
        lines.append("```yaml")
        lines.append(_snippet(spec))
        lines.append("```")
        lines.append("")
        if not spec.light and not spec.dark:
            lines.append(
                "This theme overrides nothing: the shipped stylesheet *is* the"
                " palette, so selecting it emits no `theme.css` at all."
            )
            lines.append("")
            continue
        lines.extend(_table(_effective(spec)))
        lines.append("")
    lines += [
        "## Writing your own",
        "",
        "`site: tokens:` takes the stylesheet's custom properties directly. A",
        "bare `--token: value` pair applies to **both** palettes; nesting under",
        "the `light:` and `dark:` headings targets one of them.",
        "",
        "```yaml",
        "site:",
        "  theme: paper",
        "  tokens:",
        "    --accent: '#8a1010'   # both palettes",
        "    light:",
        "      --bg: '#fffdf7'     # light mode only",
        "    dark:",
        "      --bg: '#17140f'     # dark mode only",
        "```",
        "",
        "A light-only override no longer bleeds into dark mode: the build",
        "re-asserts the effective dark palette inside the dark blocks, so the",
        "two palettes stay independent. Values are validated the same way in",
        "both forms -- a bare token name, an empty value, a value over",
        f"{theme_mod.MAX_VALUE_LENGTH} characters, or one containing a brace,",
        "a `</style>`, or a `url(`/`expression(` is a schema error.",
        "",
        "### Contrast",
        "",
        "Every semantic pair in a project's effective palettes is checked at",
        "load time: foreground, muted, accent and the four verdict colours",
        "against `--bg` and, where applicable, `--panel`, plus the `--bad` /",
        "`--good` distinguishability rule. A failing pair is a **warning**, not",
        "an error -- `refdes build` still produces the site -- because the",
        "threshold is a floor, not a law, and an author may have a reason. What",
        "it is not is silent: the warning names the pair, the two values, and",
        "the ratio it measured.",
        "",
        "Non-hex values (named colours, `rgb()`, another `var()`) are skipped:",
        "guessing at a colour the checker cannot parse would warn about colours",
        "that are fine, which is worse than not checking.",
        "",
        "### Forcing a palette",
        "",
        "The stylesheet follows the reader's OS preference. A host page that",
        "wants to pin one -- the editor, or a project that ships a toggle --",
        'sets `data-theme="light"` or `data-theme="dark"` on `<html>`; the',
        "generated `theme.css` carries matching attribute blocks that win over",
        "the media query in both directions.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the committed page is stale",
    )
    args = parser.parse_args(argv)
    page = render_page()
    if args.check:
        current = None
        if os.path.exists(TARGET_DOC):
            with open(TARGET_DOC, encoding="utf-8") as fh:
                current = fh.read()
        if current == page:
            print(f"{os.path.relpath(TARGET_DOC, ROOT)} is up to date.")
            return 0
        print(
            f"{os.path.relpath(TARGET_DOC, ROOT)} is stale -- run "
            "`python docs-site/gen_themes.py`.",
            file=sys.stderr,
        )
        return 1
    with open(TARGET_DOC, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {os.path.relpath(TARGET_DOC, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
