"""Themes: a theme is a pair of flat design-token lists -- light and dark -- and nothing else.

Finding 34 step 2b (on top of 2a's `site: theme:` / `site: tokens:` plumbing).
Step 1 gave `style.css` a real token layer; this module is the theming that
sits on top of it:

* the **built-in default theme** is exactly today's look -- it *is* the token
  blocks of the shipped stylesheet, read back out of that file rather than
  copied here, so the two can never drift apart;
* a project selects a built-in theme with `site: theme: <name>` and layers its
  own `site: tokens:` over it;
* the merged overrides are emitted as one generated stylesheet,
  `assets/theme.css`, linked after `assets/style.css`, that only redefines
  tokens.

Three properties this module exists to protect, all from the finding:

**A theme is data, not a program.** Keys must be `--token` names from the
built-in list; values must be plain CSS values. Anything that could turn a
theme into markup or a second stylesheet -- `;`, braces, `<`, `url(`,
`@import`, a comment opener, a backslash, a control character -- is a build
error. There is no selector, no nesting, no file, and no remote URL in the
format, so a theme cannot change layout, hide a section, or fetch anything.

**A typo must not fall back silently.** CSS treats an undefined custom property
as "invalid at computed-value time", which renders as *unset*, not as the
earlier cascade value -- so `--accent: #f00` would leave a site half-themed
with no diagnostic anywhere. Every token name is therefore validated against
the built-in list with the same difflib did-you-mean treatment unknown settings
already get (`schema.py`), and an unknown theme name is an error naming the
themes that do exist.

**Both palettes are real.** Section 4's decision: the `prefers-color-scheme`
mechanism stays refdes's, and a theme declares light tokens and dark tokens
under two documented headings. A bare `site: tokens:` pair applies to **both**
palettes (it is the project's own statement, not a theme's partial palette);
a `light:` / `dark:` subsection narrows it to one. The generated stylesheet
routes light overrides to `:root`, dark overrides into a
`prefers-color-scheme: dark` block *and* an explicit `[data-theme="dark"]`
selector, and re-asserts the stylesheet's own dark values for any light-only
override -- which is what stops a light override bleeding into the dark
palette, the accident 2a flagged.

The semantic-band tokens (`--good`/`--bad`/`--warn`/`--claim`) carry verdicts,
not taste. 2a refused them outright; 2b allows them under the checks sections
3 and 6 name: every semantic pair (text on background, each verdict colour on
both surfaces, the accent on both surfaces) must clear WCAG AA 4.5:1 in both
palettes, and `--bad` and `--good` must be distinguishable from each other.
A built-in theme that violated a check would be a bug in refdes, so built-ins
are checked as errors (`check_builtin_themes()`, asserted by the test suite);
a project's own choices are a `project.warn` -- loud, actionable, never
blocking, because refusing to build a project because its author likes a pale
accent is the kind of friction that makes people delete the feature.
"""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field

from . import contrast as contrast_mod
from .model import SchemaError

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STYLESHEET = os.path.join(TEMPLATE_DIR, "assets", "style.css")

# The generated file's fixed name: not configurable, because the `<link>` in
# base.html.j2 is written by refdes and a project-chosen name could collide
# with a `site.assets:` directory.
THEME_CSS_NAME = "theme.css"

# The default theme's own name. It ships no overrides at all: the default
# theme *is* the stylesheet's token blocks, so selecting it emits no file.
DEFAULT_THEME = "default"

# Verdict colours, not decorative ones (finding 34 section 4). Settable in
# 2b, but only under the contrast and bad/good-distinguishability checks.
SEMANTIC_BAND_TOKENS = frozenset({"--good", "--bad", "--warn", "--claim"})

# A token name as it must appear in a theme.
TOKEN_NAME_RE = re.compile(r"^--[a-z][a-z0-9]*(-[a-z0-9]+)*$")

# Everything a plain CSS *value* must not contain. Each entry is a substring a
# value is refused for: statement terminators and block delimiters (the end of
# "a value" and the start of "a rule"), markup, at-rules, comment delimiters,
# escapes, and anything that reaches off the machine.
FORBIDDEN_VALUE_PARTS = (
    ";",
    "{",
    "}",
    "<",
    ">",
    "@",
    "\\",
    "/*",
    "*/",
    "url(",
    "javascript:",
    "expression(",
)

MAX_VALUE_LENGTH = 200


@dataclass(frozen=True)
class ThemeSpec:
    """One built-in theme: two flat token lists, light and dark.

    A theme overrides only what gives it character -- colours. Unmentioned
    tokens (type, spacing, radii) keep the stylesheet's values, which is the
    merge's point (section 6): a theme must not restate the world.
    """

    name: str
    description: str = ""
    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)


# The gallery. Each built-in passes the contrast checks in both palettes --
# asserted by tests/test_theme.py, so a palette edit that drops a pair below
# AA fails the suite instead of shipping an unreadable site.
BUILTIN_THEME_LIST: tuple[ThemeSpec, ...] = (
    ThemeSpec(
        name=DEFAULT_THEME,
        description=(
            "Today's look: the shipped stylesheet's own palette. Selecting "
            "it emits no stylesheet at all."
        ),
    ),
    ThemeSpec(
        name="high-contrast",
        description=(
            "Maximum legibility: pure black on white and white on black, "
            "darkened verdict colours, and a strong visible line token."
        ),
        light={
            "--bg": "#ffffff",
            "--fg": "#0a0a0a",
            "--muted": "#4f5358",
            "--line": "#7d838b",
            "--panel": "#f2f2f2",
            "--accent": "#0b4a9e",
            "--good": "#056837",
            "--bad": "#a01510",
            "--warn": "#6b4a00",
            "--claim": "#5b2ea6",
        },
        dark={
            "--bg": "#000000",
            "--fg": "#ffffff",
            "--muted": "#b6bec7",
            "--line": "#8a929c",
            "--panel": "#101214",
            "--accent": "#8ab8ff",
            "--good": "#4fd186",
            "--bad": "#ff8a80",
            "--warn": "#ffd166",
            "--claim": "#cdaaff",
        },
    ),
    ThemeSpec(
        name="paper",
        description=(
            "Warm ink-on-paper: cream surfaces, brown-black text, and "
            "earthen verdict colours that stay legible in both palettes."
        ),
        light={
            "--bg": "#faf6ee",
            "--fg": "#2b2620",
            "--muted": "#6b5f4f",
            "--line": "#ddd2bf",
            "--panel": "#f2ead9",
            "--accent": "#9a4b1f",
            "--good": "#3f6b2f",
            "--bad": "#a02c1d",
            "--warn": "#7a5c00",
            "--claim": "#6f459e",
        },
        dark={
            "--bg": "#1c1814",
            "--fg": "#ece3d3",
            "--muted": "#b3a68f",
            "--line": "#4a4136",
            "--panel": "#26211a",
            "--accent": "#e0a35c",
            "--good": "#8fc47e",
            "--bad": "#f0806c",
            "--warn": "#e6c260",
            "--claim": "#c9a6e8",
        },
    ),
    ThemeSpec(
        name="slate",
        description=(
            "Cool blue-grey: a blueprint feel, teal accent, and the verdict "
            "hues kept far apart so strips read at a glance."
        ),
        light={
            "--bg": "#f5f7fa",
            "--fg": "#1b2733",
            "--muted": "#5c6b7a",
            "--line": "#ccd6e0",
            "--panel": "#eaeff5",
            "--accent": "#15616d",
            "--good": "#166b52",
            "--bad": "#b3261e",
            "--warn": "#8a5a00",
            "--claim": "#5b4bc4",
        },
        dark={
            "--bg": "#101820",
            "--fg": "#dfe7ee",
            "--muted": "#93a5b5",
            "--line": "#2c3a48",
            "--panel": "#17222c",
            "--accent": "#64b6c4",
            "--good": "#5fc99a",
            "--bad": "#ff8a7a",
            "--warn": "#e8bd58",
            "--claim": "#a8a0f0",
        },
    ),
)

BUILTIN_THEMES: dict[str, ThemeSpec] = {spec.name: spec for spec in BUILTIN_THEME_LIST}

# The palette headings a `site: tokens:` block may nest under.
PALETTE_HEADINGS = ("light", "dark")

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(css: str) -> str:
    return _COMMENT_RE.sub("", css)


def _top_level_rules(css: str) -> list[tuple[str, str]]:
    """(prelude, body) for every depth-0 rule; at-rules are skipped whole."""
    rules: list[tuple[str, str]] = []
    i, n = 0, len(css)
    prelude_start = 0
    while i < n:
        if css[i] == "{":
            prelude = " ".join(css[prelude_start:i].split())
            depth = 0
            j = i
            while j < n:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if not prelude.startswith("@"):
                rules.append((prelude, css[i + 1 : j]))
            i = prelude_start = j + 1
        else:
            i += 1
    return rules


def _media_blocks(css: str) -> list[tuple[str, str]]:
    """(at-rule prelude, inner :root body) for every @media block that
    contains a :root rule -- the dark palette's home."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(css)
    prelude_start = 0
    while i < n:
        if css[i] == "{":
            prelude = " ".join(css[prelude_start:i].split())
            depth = 0
            j = i
            while j < n:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if prelude.startswith("@"):
                body = css[i + 1 : j]
                for inner_prelude, inner_body in _top_level_rules(body):
                    if inner_prelude == ":root":
                        out.append((prelude, inner_body))
            i = prelude_start = j + 1
        else:
            i += 1
    return out


def _declarations(body: str) -> list[tuple[str, str]]:
    out = []
    for piece in body.split(";"):
        if ":" not in piece:
            continue
        head, _, value = piece.partition(":")
        out.append((" ".join(head.split()).lower(), " ".join(value.split())))
    return out


def default_tokens() -> dict[str, str]:
    """The built-in token list: every custom property the shipped stylesheet
    declares in a plain `:root` block, name -> default (light) value.

    Read from the stylesheet itself, so "the default theme is today's look" is
    true by construction instead of by maintenance.
    """
    with open(STYLESHEET, "r", encoding="utf-8") as fh:
        css = _strip_comments(fh.read())
    tokens: dict[str, str] = {}
    for prelude, body in _top_level_rules(css):
        if prelude != ":root":
            continue
        for prop, value in _declarations(body):
            if prop.startswith("--"):
                tokens[prop] = value
    return tokens


def default_dark_tokens() -> dict[str, str]:
    """The stylesheet's own dark palette: every custom property declared on
    `:root` inside a `prefers-color-scheme: dark` block.

    Part of the themeable set since 2b -- a theme may override the dark
    palette under its `dark:` heading -- and the fallback for it: a token a
    theme overrides for light only gets *this* value re-asserted inside the
    dark block, which is what stops the light value bleeding into dark mode.
    """
    with open(STYLESHEET, "r", encoding="utf-8") as fh:
        css = _strip_comments(fh.read())
    tokens: dict[str, str] = {}
    for prelude, body in _media_blocks(css):
        if "prefers-color-scheme" not in prelude or "dark" not in prelude:
            continue
        for prop, value in _declarations(body):
            if prop.startswith("--"):
                tokens[prop] = value
    return tokens


def color_token_names() -> list[str]:
    """The token names that carry a palette: the ones the stylesheet's dark
    block redefines. Everything else (type, spacing, radii) is palette-
    independent and is emitted once, not per palette."""
    return [name for name in default_tokens() if name in default_dark_tokens()]


def available_themes() -> list[str]:
    return sorted(BUILTIN_THEMES)


def _hint(name: str, known: list[str]) -> str:
    close = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
    return f". Did you mean {close[0]!r}?" if close else ""


def validate_theme_name(name: str) -> str:
    """`site: theme:` must name a built-in theme, never fall back quietly."""
    if not isinstance(name, str) or not name.strip():
        raise SchemaError("site.theme must be a theme name, got an empty value")
    if name not in BUILTIN_THEMES:
        raise SchemaError(
            f"site.theme {name!r} is not a theme. Available themes: "
            f"{', '.join(available_themes())}{_hint(name, available_themes())}"
        )
    return name


def validate_token_value(name: str, value: object) -> str:
    """A token value must be one plain CSS value, not a rule, a comment, or a
    fetch. This is the injection boundary: the value is written verbatim into
    the generated stylesheet, so anything that could end the declaration and
    start something else is refused here."""
    if not isinstance(value, str):
        raise SchemaError(
            f"site.tokens.{name} must be a CSS value string, got {value!r}"
        )
    text = value.strip()
    if not text:
        raise SchemaError(f"site.tokens.{name} must not be empty")
    if len(text) > MAX_VALUE_LENGTH:
        raise SchemaError(
            f"site.tokens.{name} must be at most {MAX_VALUE_LENGTH} characters"
        )
    lowered = text.lower()
    for part in FORBIDDEN_VALUE_PARTS:
        if part in lowered:
            raise SchemaError(
                f"site.tokens.{name} is not a plain CSS value: {part!r} is not "
                f"allowed. A theme token takes one value, like #b3541e or "
                f"Georgia, serif -- not a rule, a comment, or a URL."
            )
    if any(ord(ch) < 0x20 for ch in text):
        raise SchemaError(
            f"site.tokens.{name} is not a plain CSS value: it contains a "
            f"control character"
        )
    return text


def validate_token_map(tokens: object, *, where: str) -> dict[str, str]:
    """Validate one flat `--token: value` mapping: names must be built-in
    tokens (unknown -> did-you-mean), values must be plain CSS values.

    The semantic-band tokens are *not* refused here any more (2a refused
    them): step 2b lets them be set and checks them instead -- see
    `palette_contrast_problems` and `check_builtin_themes`.
    """
    if tokens is None:
        return {}
    if not isinstance(tokens, dict):
        raise SchemaError(
            f"{where} must be a mapping of --token to value, got {tokens!r}"
        )
    defaults = default_tokens()
    known = sorted(defaults)
    out: dict[str, str] = {}
    for name, value in tokens.items():
        if not isinstance(name, str) or not TOKEN_NAME_RE.match(name):
            raise SchemaError(
                f"{where}.{name!r} is not a token name. A token name is a "
                f"built-in custom property like --accent or --text-base."
            )
        if name not in defaults:
            raise SchemaError(
                f"{where}.{name} is not a design token{_hint(name, known)}"
            )
        out[name] = validate_token_value(name, value)
    return out


def validate_token_overrides(tokens: object, *, where: str = "site.tokens") -> dict[str, dict[str, str]]:
    """Validate a project's `site: tokens:` block into per-palette overrides.

    Two accepted shapes (section 4's two headings):

    * a **flat** `--token: value` mapping -- applies to **both** palettes.
      This is 2a's shape and stays the documented meaning: a bare pair is the
      project's own statement about its look, not a theme's partial palette,
      and "my accent is rust, in both modes" is the overwhelmingly common
      intent;
    * a nested block with `light:` and/or `dark:` subsections -- each applies
      to one palette only. A token named in a subsection overrides a flat
      entry of the same name *for that palette*.

    The return is `{"light": {...}, "dark": {...}}`; a flat pair lands in
    both.
    """
    if tokens is None:
        return {"light": {}, "dark": {}}
    if not isinstance(tokens, dict):
        raise SchemaError(
            f"{where} must be a mapping of --token to value, got {tokens!r}"
        )
    nested = any(
        isinstance(key, str) and key in PALETTE_HEADINGS for key in tokens
    )
    if not nested:
        # A `sepia:` block is a heading misspelled, not a token name: say so
        # rather than filing it under "not a token name".
        for key, value in tokens.items():
            # Only a mapping-valued key reads as a mis-named heading; a bare
            # `accent: red` is the mistyped token name validate_token_map
            # already reports well.
            if isinstance(value, dict) and not (
                isinstance(key, str) and key.startswith("--")
            ):
                raise SchemaError(
                    f"{where}.{key} is not valid here. The palette headings "
                    f"are {' and '.join(PALETTE_HEADINGS)}; anything else must "
                    f"be a bare --token pair, which applies to both palettes."
                )
        flat = validate_token_map(tokens, where=where)
        return {"light": dict(flat), "dark": dict(flat)}
    for key in tokens:
        if not isinstance(key, str) or key not in PALETTE_HEADINGS:
            raise SchemaError(
                f"{where}.{key} is not valid here. A tokens: block that uses "
                f"the {' and '.join(PALETTE_HEADINGS)} headings may contain "
                f"only them; a bare --token pair applies to both palettes."
            )
    return {
        heading: validate_token_map(tokens.get(heading), where=f"{where}.{heading}")
        for heading in PALETTE_HEADINGS
    }


def theme_palettes(name: str) -> dict[str, dict[str, str]]:
    """A built-in theme's own overrides, per palette (both empty for default)."""
    spec = BUILTIN_THEMES[validate_theme_name(name)]
    return {"light": dict(spec.light), "dark": dict(spec.dark)}


def resolve(theme_name: str, overrides: object) -> dict[str, dict[str, str]]:
    """The merged per-palette override sets to emit: built-in theme first,
    project tokens second. Only overrides -- an omitted token keeps the default
    value from `style.css` itself, which is the merge's whole point (finding 34
    section 6: a hand-written theme must not have to restate the world).

    `overrides` is the per-palette mapping from `validate_token_overrides`; a
    flat `--token` mapping is accepted too and treated as both palettes.
    """
    if (
        isinstance(overrides, dict)
        and set(overrides) <= {"light", "dark"}
        and all(isinstance(v, dict) for v in overrides.values())
    ):
        per_palette = {h: dict(overrides.get(h, {})) for h in PALETTE_HEADINGS}
    else:
        flat = dict(overrides or {})
        per_palette = {"light": dict(flat), "dark": dict(flat)}
    merged = theme_palettes(theme_name)
    for heading in PALETTE_HEADINGS:
        merged[heading].update(per_palette[heading])
    return merged


def effective_palettes(palettes: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """The override sets completed with the stylesheet's defaults: palette ->
    every token's effective value. This is what the contrast checks read."""
    light_default = default_tokens()
    dark_default = {**light_default, **default_dark_tokens()}
    defaults = {"light": light_default, "dark": dark_default}
    return {
        heading: {**defaults[heading], **palettes.get(heading, {})}
        for heading in PALETTE_HEADINGS
    }


def palette_contrast_problems(
    theme_name: str, palettes: dict[str, dict[str, str]]
) -> list[tuple[str, str]]:
    """(palette, problem) for every contrast failure of the resolved palettes.

    Empty for a well-behaved theme. Called at project load as a warning for
    projects (`warn_project_theme`) and asserted error-free for built-ins
    (`check_builtin_themes`).
    """
    problems: list[tuple[str, str]] = []
    for heading, palette in effective_palettes(palettes).items():
        for problem in contrast_mod.palette_violations(palette):
            problems.append((heading, f"theme {theme_name!r} ({heading}): {problem}"))
    return problems


def theme_contrast_problems(theme_name: str) -> list[tuple[str, str]]:
    """Contrast failures of a built-in theme on its own."""
    return palette_contrast_problems(theme_name, theme_palettes(theme_name))


def check_builtin_themes() -> list[tuple[str, str]]:
    """Contrast failures across every built-in theme, both palettes.

    A built-in that fails is a bug in refdes, not a taste question, so this is
    the error surface the finding asks for ("check the built-ins at build
    (hard error)"): the test suite calls it and fails on any entry, and no
    project can be configured into it.
    """
    problems: list[tuple[str, str]] = []
    for name in available_themes():
        problems.extend(theme_contrast_problems(name))
    return problems


def warn_project_theme(project, theme_name: str, palettes: dict[str, dict[str, str]]) -> None:
    """Warn -- never block -- on a project's resolved theme failing contrast.

    The finding's reasoning, kept: a warning naming the failing pair and the
    ratio is actionable; refusing to build because an author likes a pale
    accent is friction that gets the feature deleted.
    """
    for _palette, problem in palette_contrast_problems(theme_name, palettes):
        project.warn(f"theme contrast: {problem}")


def render_theme_css(palettes: dict[str, dict[str, str]]) -> str:
    """The generated stylesheet's text: token redefinitions and nothing else.

    The routing is the whole point (section 4: dark mode stays refdes's):

    * palette-independent tokens (type, spacing, radii) and any colour token
      whose light and dark overrides agree (a flat `site: tokens:` pair) go in
      one plain `:root` block -- that pair means "both palettes", so it may
      win over the media query; it is meant to;
    * light-only colour overrides go in `:root` too, and the effective dark
      value of every colour token is re-asserted inside
      `@media (prefers-color-scheme: dark)` -- without that, a light `--bg`
      would win over the stylesheet's dark block and bleed into dark mode,
      the 2a accident;
    * dark overrides go inside that media block *and* an explicit
      `[data-theme="dark"]` selector, so a host page (the future editor, or
      an author who wants to force a mode) can pin dark by setting the
      attribute on `<html>` regardless of the OS preference;
    * when anything is light-only, `[data-theme="light"]` re-asserts the full
      effective light palette, which is what lets the same attribute pin
      *light* mode against a dark system preference.

    Every media/data block lists the palette's complete effective colour set,
    so the result never depends on which of the blocks the browser happens to
    apply. A theme with only flat pairs emits exactly one `:root` block -- no
    media query, no attribute selectors -- because there is nothing to route.
    """
    light = palettes.get("light", {})
    dark = palettes.get("dark", {})
    if not light and not dark:
        return ""
    color_names = color_token_names()
    default_light = default_tokens()
    default_dark = default_dark_tokens()

    light_effective = {**default_light, **light}
    # Dark starts from the stylesheet's own dark palette, NOT from the light
    # overrides: a light-only token falls back to the stylesheet's dark value
    # here, which is the bleed fix. (Flat pairs are in `dark` too, so they
    # still reach both palettes.)
    dark_effective = {**default_light, **default_dark, **dark}

    def _differs_in_dark(name: str) -> bool:
        return name in dark and (name not in light or dark[name] != light[name])

    # A colour token in both palettes with equal values (a flat pair) needs no
    # routing at all: the `:root` override is meant to win in both modes.
    light_only = [name for name in color_names if name in light and name not in dark]
    dark_overridden = [name for name in color_names if _differs_in_dark(name)]
    # The media block exists when the two palettes end up disagreeing: either
    # a dark override to apply, or a light-only override to keep out.
    needs_dark_block = bool(light_only or dark_overridden)

    def _lines_for(values: dict[str, str], names: list[str]) -> list[str]:
        return [f"  {name}: {values[name]};" for name in names if name in values]

    lines: list[str] = []

    # :root: every override that is not dark-only.
    root_names = [
        name
        for name in default_light
        if name in light and (name not in color_names or not _differs_in_dark(name))
    ]
    lines.append(":root {")
    lines.extend(_lines_for(light, root_names))
    lines.append("}")

    if needs_dark_block:
        lines.append("")
        lines.append("@media (prefers-color-scheme: dark) {")
        lines.append(":root {")
        lines.extend(_lines_for(dark_effective, color_names))
        lines.append("}")
        lines.append("}")

    if light_only:
        lines.append("")
        lines.append('[data-theme="light"] {')
        lines.extend(_lines_for(light_effective, color_names))
        lines.append("}")

    if dark_overridden:
        lines.append("")
        lines.append('[data-theme="dark"] {')
        lines.extend(_lines_for(dark_effective, color_names))
        lines.append("}")

    return "\n".join(lines) + "\n"
