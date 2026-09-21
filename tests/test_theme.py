"""Theming steps 2a and 2b (finding 34): `site: theme:`, `site: tokens:`, palettes, contrast.

Five behaviours, each the failure mode the finding names:

* an unknown **theme name** is an error naming the themes that exist;
* an unknown **token name** is an error with a did-you-mean -- CSS's own answer
  to a mistyped custom property is "invalid at computed-value time", i.e. a
  half-themed site with no diagnostic anywhere;
* a token **value** is one plain CSS value. `;`, `}`, `url(`, `@import`, a
  comment opener: the value is written verbatim into a generated stylesheet,
  so this is the injection boundary and it is tested like one;
* a theme is **merged over** the default, so an omitted token keeps its default
  value rather than falling back to unset.

Step 2b adds three more guarantees:

* **two palettes**: a theme declares light and dark tokens, a bare
  `site: tokens:` pair applies to both, and a light-only override never
  bleeds into the dark palette (the generated stylesheet re-asserts the
  stylesheet's own dark values, and dark overrides land in both the media
  query and the explicit `[data-theme="dark"]` selector);
* **contrast**: every semantic pair clears WCAG AA in both palettes, and
  `--bad` and `--good` stay distinguishable -- error surface for built-ins
  (`check_builtin_themes`), `project.warn` for projects, never a block;
* the **gallery**: three built-ins besides `default`, each passing the
  contrast checks in both palettes.

Plus the two build-side guarantees: the resolved overrides really do reach the
built site (as `assets/theme.css`, tracked in the manifest and pruned when the
theme goes away), and with no theme configured the built output is byte-for-byte
what it was before theming existed -- pinned against hashes captured from
`origin/main` before any of this code.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from conftest import write_project_config
from helpers import COVERAGE_ITEMS, COVERAGE_SCHEMA, REPO

from refdes import build as build_mod
from refdes import parse, render, theme as theme_mod
from refdes.model import SchemaError
from refdes.schema import load_project

FIXTURE_HASHES = os.path.join(REPO, "tests", "fixtures", "no_theme_build_hashes.json")

SETTINGS = """\
site:
  title: T
  out: _site{site_extra}
id: {{width: 3}}
history: {{default: invalidate}}
units: {{preferred: []}}
"""

SCHEMA = """\
types:
  note:
    prefix: NTE
    fields:
      title: {type: text}
"""


def _write(tmp_path, site_extra: str = "") -> object:
    (tmp_path / "refdes-project.yaml").write_text(
        SETTINGS.format(site_extra=site_extra), encoding="utf-8"
    )
    (tmp_path / "refdes-schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "r.yaml").write_text(
        "defaults: { type: note, prefix: NTE }\n"
        "items:\n  - id: NTE-001\n    title: A valid item.\n",
        encoding="utf-8",
    )
    return tmp_path


def _error(tmp_path) -> str:
    with pytest.raises(SchemaError) as exc:
        load_project(start=str(tmp_path))
    return str(exc.value)


# ------------------------------------------------------- the built-in token list


def test_default_tokens_are_the_stylesheets_own_root_block():
    """The default theme is today's look, read out of style.css itself."""
    tokens = theme_mod.default_tokens()
    assert tokens["--bg"] == "#ffffff"
    assert tokens["--accent"] == "#1f5fbf"
    assert tokens["--text-base"] == "13px"


def test_default_dark_tokens_are_the_stylesheets_own_dark_block():
    """The stylesheet's dark palette is read out of the stylesheet too: it is
    the fallback a light-only override must not displace (2b), and 2a's
    exclusion of it is what this replaces."""
    dark = theme_mod.default_dark_tokens()
    assert dark["--bg"] == "#14171a"
    assert dark["--accent"] == "#7fb0ff"
    # Only colour tokens are redefined in dark mode; type and spacing are
    # palette-independent.
    assert "--text-base" not in dark
    assert set(dark) == set(theme_mod.color_token_names())


def test_every_default_token_name_is_a_valid_token_name():
    for name in theme_mod.default_tokens():
        assert theme_mod.TOKEN_NAME_RE.match(name), name


# ------------------------------------------------------------ theme name errors


def test_unknown_theme_name_is_an_error_naming_the_themes(tmp_path):
    message = _error(_write(tmp_path, "\n  theme: bronze"))
    assert "site.theme" in message
    assert "bronze" in message
    assert theme_mod.DEFAULT_THEME in message


def test_theme_typo_gets_a_did_you_mean(tmp_path):
    message = _error(_write(tmp_path, "\n  theme: defualt"))
    assert "Did you mean 'default'?" in message


def test_default_theme_is_accepted(tmp_path):
    project = load_project(start=str(_write(tmp_path, "\n  theme: default")))
    assert project.theme == "default"


# ------------------------------------------------------------- token name errors


def test_unknown_token_is_an_error(tmp_path):
    message = _error(
        _write(tmp_path, "\n  tokens:\n    --colour-blue: '#0000ff'\n")
    )
    assert "site.tokens.--colour-blue" in message
    assert "not a design token" in message


def test_token_typo_gets_a_did_you_mean(tmp_path):
    """`--accentt` is the exact case the finding calls out: CSS would render a
    half-themed site and say nothing at all."""
    message = _error(_write(tmp_path, "\n  tokens:\n    --accentt: '#b3541e'\n"))
    assert "Did you mean '--accent'?" in message


def test_a_token_name_without_the_dashes_is_an_error(tmp_path):
    message = _error(_write(tmp_path, "\n  tokens:\n    accent: '#b3541e'\n"))
    assert "not a token name" in message


def test_a_non_mapping_tokens_block_is_an_error(tmp_path):
    message = _error(_write(tmp_path, "\n  tokens: '#b3541e'\n"))
    assert "site.tokens" in message


# ------------------------------------------------------- injection in a value


@pytest.mark.parametrize(
    "value",
    [
        "url(javascript:alert(1))",
        "red; body { display: none }",
        "}",
        "red }",
        "{",
        "/*",
        "*/",
        "@import url(https://evil.example/x.css);",
        "@import evilty.css",
        "</style><script>alert(1)</script>",
        "expression(alert(1))",
        "red\\\n; --x: y",
        "a\tb\nc",
    ],
)
def test_a_token_value_cannot_be_a_rule_a_comment_or_a_fetch(tmp_path, value):
    message = _error(
        _write(tmp_path, f"\n  tokens:\n    --accent: {json.dumps(value)}\n")
    )
    assert "site.tokens.--accent" in message
    assert "plain CSS value" in message


def test_ordinary_css_values_are_accepted():
    palettes = theme_mod.validate_token_overrides(
        {
            "--accent": "#b3541e",
            "--sans": "Georgia, 'Iowan Old Style', serif",
            "--text-base": "14.5px",
            "--radius-pill": "999px",
            "--leading-body": "1.75",
            "--space-4": "0.25rem",
        }
    )
    assert palettes["light"]["--sans"] == "Georgia, 'Iowan Old Style', serif"
    assert palettes["dark"]["--accent"] == "#b3541e"


def test_an_empty_or_oversized_value_is_refused():
    with pytest.raises(SchemaError):
        theme_mod.validate_token_overrides({"--accent": "   "})
    with pytest.raises(SchemaError):
        theme_mod.validate_token_overrides({"--accent": "x" * 500})


# --------------------------------------------------------- semantic band tokens
#
# 2a refused `--good`/`--bad`/`--warn`/`--claim` outright; 2b allows them and
# checks them instead -- see the contrast section below. A band token set to a
# legible, hue-separated value loads with no diagnostic at all.


_LEGIBLE_BAND_VALUES = {
    # (light, dark) pairs that clear AA against both palettes' surfaces.
    "--good": ("#1a6b3c", "#5cc98a"),
    "--bad": ("#a01510", "#ff7b72"),
    "--warn": ("#7a5200", "#e3b341"),
    "--claim": ("#5b2ea6", "#c39bff"),
}


@pytest.mark.parametrize("name", sorted(theme_mod.SEMANTIC_BAND_TOKENS))
def test_a_verdict_colour_can_be_set_when_it_keeps_its_meaning(tmp_path, name):
    light_value, dark_value = _LEGIBLE_BAND_VALUES[name]
    project = load_project(
        start=str(
            _write(
                tmp_path,
                f"\n  tokens:\n    light:\n      {name}: '{light_value}'\n"
                f"    dark:\n      {name}: '{dark_value}'\n",
            )
        )
    )
    assert project.theme_tokens["light"][name] == light_value
    assert project.warnings == []


# --------------------------------------------------------------- the palettes


def test_a_flat_token_pair_applies_to_both_palettes():
    """The documented meaning of a bare `site: tokens:` pair (2b decision):
    the project's own statement about its look, in both modes."""
    palettes = theme_mod.validate_token_overrides({"--accent": "#b3541e"})
    assert palettes == {"light": {"--accent": "#b3541e"}, "dark": {"--accent": "#b3541e"}}


def test_light_and_dark_headings_narrow_a_pair_to_one_palette():
    palettes = theme_mod.validate_token_overrides(
        {"light": {"--bg": "#fffdf5"}, "dark": {"--bg": "#181410"}}
    )
    assert palettes["light"] == {"--bg": "#fffdf5"}
    assert palettes["dark"] == {"--bg": "#181410"}


def test_a_heading_block_cannot_carry_bare_pairs(tmp_path):
    """Mixing `light:` with a bare `--token` would make the bare pair's
    palette ambiguous, which is the accident 2b exists to remove."""
    message = _error(
        _write(
            tmp_path,
            "\n  tokens:\n    light:\n      --bg: '#ffffff'\n    --accent: '#b3541e'\n",
        )
    )
    assert "site.tokens.--accent" in message
    assert "headings" in message


def test_an_unknown_heading_is_an_error(tmp_path):
    message = _error(_write(tmp_path, "\n  tokens:\n    sepia:\n      --bg: '#fff'\n"))
    assert "site.tokens.sepia" in message


def test_a_light_only_override_does_not_bleed_into_dark(tmp_path):
    """The 2a accident, fixed: a light `--bg` used to win over the
    `prefers-color-scheme: dark` block, because a plain `:root` override
    emitted after the stylesheet beats it. The generated stylesheet now
    re-asserts the stylesheet's own dark value inside the dark blocks."""
    out = _build(
        _coverage_project(
            tmp_path,
            "\n  tokens:\n    light:\n      --bg: '#fffdf0'\n      --fg: '#20201a'\n",
        )
    )
    css = open(os.path.join(out, "assets", "theme.css"), encoding="utf-8").read()
    media = _media_block(css)
    assert "--bg: #14171a;" in media  # the stylesheet's own dark value
    assert "--bg: #fffdf0" not in media
    assert "--bg: #fffdf0;" in css.split("@media", 1)[0]  # light override intact


def test_dark_overrides_land_in_the_media_query_and_the_data_theme_selector(tmp_path):
    out = _build(
        _coverage_project(
            tmp_path,
            "\n  tokens:\n    dark:\n      --bg: '#101018'\n",
        )
    )
    css = open(os.path.join(out, "assets", "theme.css"), encoding="utf-8").read()
    media = _media_block(css)
    assert "--bg: #101018;" in media
    data_block = css.split('[data-theme="dark"] {', 1)[1]
    assert "--bg: #101018;" in data_block


def test_a_light_only_override_emits_a_data_theme_light_block(tmp_path):
    """`data-theme="light"` must be able to pin light against a dark system
    preference, which needs the full effective light palette re-asserted."""
    out = _build(
        _coverage_project(
            tmp_path,
            "\n  tokens:\n    light:\n      --accent: '#b3541e'\n",
        )
    )
    css = open(os.path.join(out, "assets", "theme.css"), encoding="utf-8").read()
    light_block = css.split('[data-theme="light"] {', 1)[1]
    assert "--accent: #b3541e;" in light_block
    # The whole effective palette, so the block does not depend on which other
    # blocks the browser applied: every colour token appears in it.
    for name in theme_mod.color_token_names():
        assert f"{name}:" in light_block


def test_a_shared_pair_does_not_emit_dark_blocks(tmp_path):
    """A flat pair means both palettes, so there is nothing to re-assert and
    no bleed to prevent: the stylesheet stays a plain `:root` of overrides."""
    out = _build(
        _coverage_project(tmp_path, "\n  tokens:\n    --accent: '#b3541e'\n")
    )
    css = open(os.path.join(out, "assets", "theme.css"), encoding="utf-8").read()
    assert css.startswith(":root {")
    assert "--accent: #b3541e;" in css
    assert "@media" not in css
    assert "data-theme" not in css


# ---------------------------------------------------------------- contrast


def test_the_shipped_default_palette_passes_the_contrast_checks():
    """Not a theme's problem -- the stylesheet's own. If style.css drifts to a
    pair below AA, this fails here rather than in someone's browser."""
    assert theme_mod.theme_contrast_problems(theme_mod.DEFAULT_THEME) == []


def test_no_builtin_theme_fails_contrast(tmp_path):
    """The error surface for built-ins (finding 34 §3): a built-in that fails
    is a bug in refdes, so it fails the suite, not a project's build."""
    assert theme_mod.check_builtin_themes() == []


def test_the_gallery_ships_three_builtins_besides_default():
    names = theme_mod.available_themes()
    assert theme_mod.DEFAULT_THEME in names
    extras = [name for name in names if name != theme_mod.DEFAULT_THEME]
    assert len(extras) >= 3
    for name in extras:
        spec = theme_mod.BUILTIN_THEMES[name]
        assert spec.light and spec.dark, f"{name} must declare both palettes"
        assert spec.description, f"{name} needs a description for the gallery"


def test_a_low_contrast_project_token_warns_but_loads(tmp_path):
    """The finding's friction rule: a warning naming the failing pair and the
    ratio, never a refused build."""
    project = load_project(
        start=str(_write(tmp_path, "\n  tokens:\n    --fg: '#eeeeee'\n"))
    )
    messages = [d.message for d in project.warnings]
    assert any("theme contrast" in m and "--fg" in m and "--bg" in m for m in messages)
    assert any("4.5" in m for m in messages)


def test_a_bad_good_pair_too_similar_warns(tmp_path):
    """§6: a verdict strip whose fail and pass read alike is a correctness
    problem. Same-ish reds for both hues: no separation by hue or lightness."""
    project = load_project(
        start=str(
            _write(
                tmp_path,
                "\n  tokens:\n    --bad: '#c33227'\n    --good: '#b3261e'\n",
            )
        )
    )
    messages = [d.message for d in project.warnings]
    assert any("--bad" in m and "--good" in m and "distinguishable" in m for m in messages)


def test_a_legible_theme_of_band_tokens_does_not_warn(tmp_path):
    project = load_project(
        start=str(
            _write(
                tmp_path,
                "\n  tokens:\n    light:\n      --bad: '#8a1010'\n"
                "      --good: '#0e6b3a'\n"
                "    dark:\n      --bad: '#ff7b72'\n      --good: '#5cc98a'\n",
            )
        )
    )
    assert project.warnings == []


def test_non_hex_values_are_skipped_not_guessed():
    """`red` has no computable ratio; the check says nothing rather than
    guessing what the author's named colour looks like."""
    from refdes import contrast as contrast_mod

    assert contrast_mod.contrast_ratio("red", "#ffffff") is None
    assert contrast_mod.palette_violations(
        {"--fg": "red", "--bg": "#ffffff"}
    ) == []


def test_contrast_math_matches_the_wcag_reference_pair():
    """The W3C worked example: #777777 on #ffffff is 4.48:1 (fails AA),
    #767676 on #ffffff is 4.54:1 (passes)."""
    from refdes import contrast as contrast_mod

    assert round(contrast_mod.contrast_ratio("#777777", "#ffffff"), 2) == 4.48
    assert round(contrast_mod.contrast_ratio("#767676", "#ffffff"), 2) == 4.54
    assert contrast_mod.contrast_ratio("#000000", "#ffffff") == 21.0


# ------------------------------------------------------------------- the merge


def test_overrides_merge_over_the_default_and_keep_the_rest():
    """A theme is merged OVER the default, never a replacement for it: the
    emitted `:root` carries only what the project actually said, so every
    omitted token keeps the value style.css already declares instead of going
    unset."""
    merged = theme_mod.resolve("default", {"--accent": "#b3541e"})
    assert merged == {"light": {"--accent": "#b3541e"}, "dark": {"--accent": "#b3541e"}}
    defaults = theme_mod.default_tokens()
    emitted = theme_mod.render_theme_css(merged)
    root_block = emitted.split("@media", 1)[0]
    # Every other token is absent from the override block, which is exactly the
    # condition for the default `:root` value to survive the cascade.
    for name in defaults:
        if name != "--accent":
            assert f"{name}:" not in root_block


def test_project_tokens_override_the_theme_of_the_same_name():
    """Theme first, project tokens second (finding 34 §2)."""
    theme_mod.BUILTIN_THEMES["_test-slate"] = theme_mod.ThemeSpec(
        name="_test-slate",
        light={"--accent": "#111111", "--bg": "#222222"},
        dark={"--bg": "#222222"},
    )
    try:
        merged = theme_mod.resolve("_test-slate", {"light": {"--accent": "#b3541e"}})
        assert merged["light"] == {"--accent": "#b3541e", "--bg": "#222222"}
        assert merged["dark"] == {"--bg": "#222222"}
    finally:
        del theme_mod.BUILTIN_THEMES["_test-slate"]


def test_emitted_css_redefines_only_the_overrides():
    css = theme_mod.render_theme_css(
        {"light": {"--accent": "#b3541e", "--bg": "#000000"}, "dark": {}}
    )
    root_block = css.split("@media", 1)[0]
    assert "--accent: #b3541e;" in root_block
    assert "--bg: #000000;" in root_block
    assert root_block.startswith(":root {")
    # The `:root` block carries only what was overridden: every other token
    # keeps the cascade value style.css already declares.
    for name in theme_mod.default_tokens():
        if name not in ("--accent", "--bg"):
            assert f"{name}:" not in root_block
    # The dark blocks re-assert the stylesheet's own dark values, not the
    # light overrides: no bleed.
    media = _media_block(css)
    assert "--bg: #14171a;" in media
    assert "--accent: #1f5fbf;" not in media


# ------------------------------------------------------------- the built site


def _media_block(css: str) -> str:
    """The body of the generated `@media (prefers-color-scheme: dark)` block,
    brace-matched -- the blocks nest, so a naive split on `}` stops early."""
    start = css.index("@media (prefers-color-scheme: dark) {")
    depth = 0
    for index in range(start + len("@media (prefers-color-scheme: dark) {") - 1, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[start:index]
    raise AssertionError("no balanced @media block in generated theme.css")


def _build(root):
    project = load_project(start=str(root))
    parse.load_items(project)
    build_mod.build(project)
    return render.render_site(project)


def _coverage_project(tmp_path, site_extra: str = ""):
    config = COVERAGE_SCHEMA
    if site_extra:
        config = config.replace(
            'site: {title: "Coverage Test", out: _site}',
            'site:\n  title: "Coverage Test"\n  out: _site' + site_extra,
        )
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


# Extensions whose bytes ARE the content: a newline conversion would be wrong
# for them, and accepting a converted variant would mask a real change.
BINARY_EXTENSIONS = {
    ".bmp", ".bz2", ".eot", ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".mp3",
    ".mp4", ".ogg", ".otf", ".pdf", ".png", ".svgz", ".tar", ".tif", ".tiff",
    ".ttf", ".webm", ".webp", ".woff", ".woff2", ".zip", "",
}


def _digests(path):
    """Every sha256 a built file's content hashes to under a line-ending
    convention: as-is, folded to LF, and expanded to CRLF.

    Which convention a pinned hash was captured under is a property of the
    machine, not of the build. Generated pages are written in text mode, so
    they are CRLF on Windows and LF on POSIX; static assets are copied
    byte-for-byte, so they carry whatever the checkout produced -- LF under this
    worktree's `.gitattributes`, CRLF in a `core.autocrlf=true` checkout where
    it is not in force. The fixture was captured on Windows, so it holds CRLF
    hashes for the generated files and LF hashes for the assets, and a single
    normalization would break one side or the other. Accepting the three
    line-ending variants of the same content is what makes the check measure the
    build instead of the checkout; any byte that is not a line ending still has
    to match exactly, and binaries are compared raw only.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    variants = {hashlib.sha256(data).hexdigest()}
    if os.path.splitext(path)[1].lower() not in BINARY_EXTENSIONS:
        variants.add(hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest())
        variants.add(hashlib.sha256(data.replace(b"\n", b"\r\n")).hexdigest())
    return variants


def test_no_theme_build_is_byte_identical_to_the_pinned_output(tmp_path):
    """The regression this whole step has to prove: with no theme configured,
    nothing about the built site changes -- not one file, not one byte beyond
    line endings, not one manifest entry. The hashes were captured from
    origin/main before any theming code existed, on this same fixture
    project."""
    pinned = json.loads(open(FIXTURE_HASHES, encoding="utf-8").read())
    out = _build(_coverage_project(tmp_path))
    built = {}
    for dirpath, _dirs, names in os.walk(out):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, out).replace("\\", "/")
            built[rel] = _digests(path)
    assert set(built) == set(pinned)
    assert {rel: pinned[rel] for rel in pinned if pinned[rel] not in built[rel]} == {}


def test_an_override_changes_the_emitted_css(tmp_path):
    out = _build(
        _coverage_project(tmp_path, "\n  tokens:\n    --accent: '#b3541e'\n")
    )
    theme_css = os.path.join(out, "assets", "theme.css")
    assert os.path.isfile(theme_css)
    css = open(theme_css, encoding="utf-8").read()
    assert "--accent: #b3541e;" in css
    # style.css itself is never edited: the override is a separate, later file.
    assert "--accent: #b3541e" not in open(
        os.path.join(out, "assets", "style.css"), encoding="utf-8"
    ).read()


def test_the_theme_stylesheet_is_linked_after_style_css(tmp_path):
    out = _build(
        _coverage_project(tmp_path, "\n  tokens:\n    --accent: '#b3541e'\n")
    )
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    style_at = html.index('href="assets/style.css"')
    theme_at = html.index('href="assets/theme.css"')
    assert style_at < theme_at


def test_no_theme_means_no_link_and_no_file(tmp_path):
    out = _build(_coverage_project(tmp_path))
    assert not os.path.exists(os.path.join(out, "assets", "theme.css"))
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert "theme.css" not in html


def test_the_theme_file_is_in_the_manifest(tmp_path):
    out = _build(
        _coverage_project(tmp_path, "\n  tokens:\n    --accent: '#b3541e'\n")
    )
    manifest = json.loads(
        open(os.path.join(out, ".refdes-manifest.json"), encoding="utf-8").read()
    )
    assert "assets/theme.css" in manifest


def test_removing_the_theme_prunes_the_generated_file(tmp_path):
    """A theme that goes away must not leave a live stylesheet behind: the
    manifest is what makes that automatic, provided the file is tracked."""
    project_dir = _coverage_project(tmp_path, "\n  tokens:\n    --accent: '#b3541e'\n")
    out = _build(project_dir)
    assert os.path.isfile(os.path.join(out, "assets", "theme.css"))

    write_project_config(project_dir, COVERAGE_SCHEMA)
    out = _build(project_dir)
    assert not os.path.exists(os.path.join(out, "assets", "theme.css"))
    manifest = json.loads(
        open(os.path.join(out, ".refdes-manifest.json"), encoding="utf-8").read()
    )
    assert "assets/theme.css" not in manifest


def test_a_project_asset_cannot_take_the_theme_stylesheets_name(tmp_path):
    """`assets/theme.css` is generated; a site.assets: directory of that name
    would otherwise land on top of it."""
    root = _coverage_project(tmp_path, "\n  assets: [theme.css]")
    (root / "theme.css").mkdir()
    (root / "theme.css" / "mine.css").write_text("--accent: red;\n", encoding="utf-8")
    project = load_project(start=str(root))
    parse.load_items(project)
    build_mod.build(project)
    render.render_site(project)
    assert any("assets/theme.css" in d.message for d in project.errors)
