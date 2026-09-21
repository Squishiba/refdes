"""Themes: a theme is a flat list of design-token pairs, and nothing else.

Finding 34 step 2a. Step 1 gave `style.css` a real token layer; this module is
the theming that sits on top of it:

* the **built-in default theme** is exactly today's look -- it *is* the `:root`
  token block of the shipped stylesheet, read back out of that file rather
  than copied here, so the two can never drift apart;
* a project selects a built-in theme with `site: theme: <name>` and layers its
  own `site: tokens:` over it;
* the merged overrides are emitted as one generated stylesheet,
  `assets/theme.css`, linked after `assets/style.css`, that only redefines
  tokens.

Two properties this module exists to protect, both from the finding:

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

The semantic-band tokens (`--good`/`--bad`/`--warn`/`--claim`) carry verdicts,
not taste, and step 2a refuses a theme that sets them at all; step 2b replaces
that flat refusal with the contrast and band checks.
"""

from __future__ import annotations

import difflib
import os
import re

from .model import SchemaError

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STYLESHEET = os.path.join(TEMPLATE_DIR, "assets", "style.css")

# The generated file's fixed name: not configurable, because the `<link>` in
# base.html.j2 is written by refdes and a project-chosen name could collide
# with a `site.assets:` directory.
THEME_CSS_NAME = "theme.css"

# The default theme's own name. It ships no overrides at all: the default
# theme *is* the stylesheet's `:root`, so selecting it emits no file.
DEFAULT_THEME = "default"

# Built-in themes: name -> token overrides. Step 2a ships the default only;
# the gallery and the extra built-ins are step 2b.
BUILTIN_THEMES: dict[str, dict[str, str]] = {DEFAULT_THEME: {}}

# Verdict colours, not decorative ones (finding 34 §4). 2a refuses them
# outright; 2b does bands and contrast.
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
    declares in a plain `:root` block, name -> default value.

    Read from the stylesheet itself, so "the default theme is today's look" is
    true by construction instead of by maintenance. The `@media
    (prefers-color-scheme: dark)` block is deliberately not part of this: a
    theme override lands in one plain `:root` after the stylesheet, and the
    dark palette stays refdes's (finding 34 §4).
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


def validate_token_overrides(tokens: object, *, where: str = "site.tokens") -> dict[str, str]:
    """Validate a theme's or a project's token block: a flat mapping of
    built-in `--token` names to plain CSS values.

    Unknown names are errors with a did-you-mean, because CSS's own answer to
    a mistyped custom property is silence. The semantic-band tokens are refused
    outright in step 2a.
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
        if name in SEMANTIC_BAND_TOKENS:
            raise SchemaError(
                f"{where}.{name} cannot be set by a theme. --good, --bad, "
                f"--warn and --claim are verdict colours -- they read as "
                f"pass/fail/at-risk/claimed on every strip and pill -- and "
                f"refdes does not yet check that a reassignment keeps that "
                f"meaning (finding 34 step 2b)."
            )
        if name not in defaults:
            raise SchemaError(
                f"{where}.{name} is not a design token{_hint(name, known)}"
            )
        out[name] = validate_token_value(name, value)
    return out


def theme_tokens(name: str) -> dict[str, str]:
    """A built-in theme's own overrides (empty for the default theme)."""
    return dict(BUILTIN_THEMES[validate_theme_name(name)])


def resolve(theme_name: str, overrides: dict[str, str]) -> dict[str, str]:
    """The merged override set to emit: built-in theme first, project tokens
    second. Only overrides -- an omitted token keeps the default value from
    `style.css` itself, which is the merge's whole point (finding 34 §6: a
    hand-written theme must not have to restate the world)."""
    merged = theme_tokens(theme_name)
    merged.update(overrides)
    return merged


def render_theme_css(overrides: dict[str, str]) -> str:
    """The generated stylesheet's text: one `:root` block, tokens in the
    built-in list's own order, and nothing else."""
    order = [name for name in default_tokens() if name in overrides]
    lines = [":root {"]
    for name in order:
        lines.append(f"  {name}: {overrides[name]};")
    lines.append("}")
    return "\n".join(lines) + "\n"
