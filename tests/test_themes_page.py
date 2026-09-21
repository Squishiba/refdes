"""The generated built-in theme gallery page (finding 34 step 2b).

`docs/themes.md` is written by `docs-site/gen_themes.py` from
`refdes.theme.BUILTIN_THEME_LIST` -- the same objects `site: theme:` resolves
and `tests/test_theme.py` audits. These tests are the drift gate:

- the committed page equals generator output, byte for byte, so a palette edit
  that skips the regeneration fails here rather than shipping a page that
  describes colours nobody gets;
- every built-in theme is on the page with its `site:` snippet and a row per
  colour token, in both palettes;
- the page's stated thresholds are the ones `refdes.contrast` actually applies;
- the docs-site nav lists the page, so it is reachable in a built site.
"""

from __future__ import annotations

import importlib.util
import os

import yaml
from helpers import REPO

GEN_PATH = os.path.join(REPO, "docs-site", "gen_themes.py")
DOC_PATH = os.path.join(REPO, "docs", "themes.md")
SITE_CONFIG = os.path.join(REPO, "docs-site", "refdes-project.yaml")


def _gen():
    spec = importlib.util.spec_from_file_location("gen_themes_page", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _page_text():
    with open(DOC_PATH, encoding="utf-8") as fh:
        return fh.read()


def test_committed_page_matches_the_generator():
    assert _gen().render_page() == _page_text()


def test_check_accepts_the_committed_page():
    assert _gen().main(["--check"]) == 0


def test_every_builtin_theme_has_a_section_and_a_snippet():
    from refdes import theme as theme_mod

    page = _page_text()
    for spec in theme_mod.BUILTIN_THEME_LIST:
        assert f"## `{spec.name}`" in page
        assert f"theme: {spec.name}" in page


def test_colour_tokens_are_listed_for_both_palettes():
    """A theme that overrides a token shows its value; one that does not shows
    the stylesheet's own -- the table is what a reader would actually see."""
    from refdes import theme as theme_mod

    page = _page_text()
    section = page.split("## `paper`", 1)[1].split("\n## ", 1)[0]
    base_light = theme_mod.default_tokens()
    for name, value in theme_mod.BUILTIN_THEMES["paper"].light.items():
        assert f"| `{name}` | `{value}` |" in section
    for name in theme_mod.color_token_names():
        if name not in theme_mod.BUILTIN_THEMES["paper"].light:
            assert f"| `{name}` | `{base_light[name]}` |" in section


def test_the_page_states_the_thresholds_the_checker_uses():
    from refdes import contrast as contrast_mod

    page = _page_text()
    assert f"{contrast_mod.MIN_CONTRAST}:1" in page
    assert f"{contrast_mod.MIN_BAD_GOOD_HUE_DEGREES:.0f}-degree" in page


def test_the_page_documents_the_two_palette_token_format():
    page = _page_text()
    assert "both" in page and "light:" in page and "dark:" in page
    assert "data-theme" in page


def test_the_docs_site_nav_lists_the_page():
    with open(SITE_CONFIG, encoding="utf-8") as fh:
        nav = (yaml.safe_load(fh).get("site") or {}).get("nav") or []
    assert "themes" in nav
