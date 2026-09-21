"""Theming step 2a (finding 34): `site: theme:` and `site: tokens:`.

Five behaviours, each the failure mode the finding names:

* an unknown **theme name** is an error naming the themes that exist;
* an unknown **token name** is an error with a did-you-mean -- CSS's own answer
  to a mistyped custom property is "invalid at computed-value time", i.e. a
  half-themed site with no diagnostic anywhere;
* a token **value** is one plain CSS value. `;`, `}`, `url(`, `@import`, a
  comment opener: the value is written verbatim into a generated stylesheet,
  so this is the injection boundary and it is tested like one;
* the **semantic-band** tokens (`--good`/`--bad`/`--warn`/`--claim`) are
  refused outright in 2a -- they carry verdicts, not taste;
* a theme is **merged over** the default, so an omitted token keeps its default
  value rather than falling back to unset.

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
    # The dark palette is not part of the themeable default set: overrides land
    # in one plain :root, and dark mode stays refdes's.
    assert "--bg" in tokens


def test_every_default_token_name_is_a_valid_token_name():
    for name in theme_mod.default_tokens():
        assert theme_mod.TOKEN_NAME_RE.match(name), name


# ------------------------------------------------------------ theme name errors


def test_unknown_theme_name_is_an_error_naming_the_themes(tmp_path):
    message = _error(_write(tmp_path, "\n  theme: slate"))
    assert "site.theme" in message
    assert "slate" in message
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
    tokens = theme_mod.validate_token_overrides(
        {
            "--accent": "#b3541e",
            "--sans": "Georgia, 'Iowan Old Style', serif",
            "--text-base": "14.5px",
            "--radius-pill": "999px",
            "--leading-body": "1.75",
            "--space-4": "0.25rem",
        }
    )
    assert tokens["--sans"] == "Georgia, 'Iowan Old Style', serif"


def test_an_empty_or_oversized_value_is_refused():
    with pytest.raises(SchemaError):
        theme_mod.validate_token_overrides({"--accent": "   "})
    with pytest.raises(SchemaError):
        theme_mod.validate_token_overrides({"--accent": "x" * 500})


# --------------------------------------------------------- semantic band tokens


@pytest.mark.parametrize("name", sorted(theme_mod.SEMANTIC_BAND_TOKENS))
def test_a_theme_cannot_reassign_a_verdict_colour(tmp_path, name):
    message = _error(_write(tmp_path, f"\n  tokens:\n    {name}: '#b3541e'\n"))
    assert f"site.tokens.{name}" in message
    assert "verdict" in message


# ------------------------------------------------------------------- the merge


def test_overrides_merge_over_the_default_and_keep_the_rest():
    """A theme is merged OVER the default, never a replacement for it: the
    emitted set carries only what the project actually said, so every omitted
    token keeps the value style.css already declares instead of going unset."""
    merged = theme_mod.resolve("default", {"--accent": "#b3541e"})
    assert merged == {"--accent": "#b3541e"}
    defaults = theme_mod.default_tokens()
    emitted = theme_mod.render_theme_css(merged)
    # Every other token is absent from the override block, which is exactly the
    # condition for the default `:root` value to survive the cascade.
    for name in defaults:
        if name != "--accent":
            assert f"{name}:" not in emitted


def test_project_tokens_override_the_theme_of_the_same_name():
    """Theme first, project tokens second (finding 34 §2)."""
    theme_mod.BUILTIN_THEMES["_test-slate"] = {"--accent": "#111111", "--bg": "#222222"}
    try:
        merged = theme_mod.resolve("_test-slate", {"--accent": "#b3541e"})
        assert merged == {"--accent": "#b3541e", "--bg": "#222222"}
    finally:
        del theme_mod.BUILTIN_THEMES["_test-slate"]


def test_emitted_css_redefines_only_the_overrides():
    css = theme_mod.render_theme_css({"--accent": "#b3541e", "--bg": "#000000"})
    assert "--accent: #b3541e;" in css
    assert "--bg: #000000;" in css
    assert "--good" not in css
    assert css.startswith(":root {")
    # Nothing but a :root block of token pairs: no selector, no at-rule.
    assert css.count("{") == 1 and css.count("}") == 1


# ------------------------------------------------------------- the built site


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


def test_no_theme_build_is_byte_identical_to_the_pinned_output(tmp_path):
    """The regression this whole step has to prove: with no theme configured,
    nothing about the built site changes -- not one byte, not one manifest
    entry. The hashes were captured from origin/main before any theming code
    existed, on this same fixture project."""
    pinned = json.loads(open(FIXTURE_HASHES, encoding="utf-8").read())
    out = _build(_coverage_project(tmp_path))
    built = {}
    for dirpath, _dirs, names in os.walk(out):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, out).replace("\\", "/")
            with open(path, "rb") as fh:
                built[rel] = hashlib.sha256(fh.read()).hexdigest()
    assert built == pinned


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
