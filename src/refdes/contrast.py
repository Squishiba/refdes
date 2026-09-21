"""WCAG contrast arithmetic for theme palettes (finding 34 step 2b).

Pure Python, no browser: the tokens are hex literals in data refdes already
parses, and the ratio is the relative-luminance arithmetic W3C defines in
"Understanding SC 1.4.3" — sRGB linearisation, a weighted sum, and the
(L1 + 0.05) / (L2 + 0.05) ratio. WCAG AA is 4.5:1 for normal text and 3:1
for large text; refdes checks the stricter 4.5:1 against every semantic pair,
because the pairs below are all read as text or as small graphic marks.

What this can and cannot see: it checks token against token — `--fg` on
`--bg`, `--good` on `--panel` — not real rendered contrast through the
stylesheet's `color-mix()` tints. That catches the gross cases, which the
finding says is most of them, and it is honest about the rest: a value that
is not a plain hex colour (`red`, `rgb(...)`, `hsl(...)`, a `var()` or a font
stack) is skipped, never guessed at.

The semantic pairs are the point. The finding's failure mode is "a theme
makes a diagnostic invisible — `--bad` close to `--bg`", so the verdict
colours are checked against both surfaces they render on, and `--bad` and
`--good` are additionally checked against *each other*: the coverage strip's
whole promise is a verdict readable at a glance, and a red and a green of
equal luminance are the same grey to a colour-blind reader. Contrast ratio
alone cannot express that (the shipped default's red-on-green is 1.3:1 and
perfectly fine), so the rule is hue separation — the two hues must sit far
apart on the colour wheel — with a large contrast ratio as the alternative
for palettes that separate by lightness instead of hue.
"""

from __future__ import annotations

import colorsys
import re

# WCAG AA for normal text.
MIN_CONTRAST = 4.5

# `--bad` against `--good`: enough hue separation that the pair survives
# colour-blindness and greyscale, or enough contrast ratio to separate by
# lightness alone.
MIN_BAD_GOOD_HUE_DEGREES = 90.0
MIN_BAD_GOOD_CONTRAST = 4.5

# The semantic pairs, (foreground token, background token). Every verdict
# colour is checked against both surfaces, because strips and pills render on
# `--bg` while panels and notices render on `--panel`.
SEMANTIC_PAIRS: tuple[tuple[str, str], ...] = (
    ("--fg", "--bg"),
    ("--muted", "--bg"),
    ("--muted", "--panel"),
    ("--accent", "--bg"),
    ("--accent", "--panel"),
    ("--good", "--bg"),
    ("--good", "--panel"),
    ("--bad", "--bg"),
    ("--bad", "--panel"),
    ("--warn", "--bg"),
    ("--warn", "--panel"),
    ("--claim", "--bg"),
    ("--claim", "--panel"),
)

# The pair that must be distinguishable *from each other*, not just legible.
BAD_GOOD_PAIR = ("--bad", "--good")

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex(value: str) -> tuple[float, float, float] | None:
    """(r, g, b) in 0..1 for a plain hex colour, else None.

    Only `#rgb` and `#rrggbb` are parseable, which is exactly the set of token
    values the check deems safe to judge. Anything else — a named colour,
    `rgb()`, `color-mix()`, a font stack — returns None and the pair naming it
    is skipped rather than guessed.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _HEX_RE.match(text):
        return None
    text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG relative luminance of a linearised sRGB triple."""
    linear = [
        channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in rgb
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(value_a: str, value_b: str) -> float | None:
    """The WCAG contrast ratio of two colours, or None if either is not a
    plain hex colour (and the pair is therefore not checkable)."""
    a, b = parse_hex(value_a), parse_hex(value_b)
    if a is None or b is None:
        return None
    lum_a, lum_b = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def hue_degrees(value: str) -> float | None:
    """The hue of a plain hex colour in degrees, or None (achromatic colours
    and unparseable values have no hue to separate by)."""
    rgb = parse_hex(value)
    if rgb is None:
        return None
    hue = colorsys.rgb_to_hsv(*rgb)[0] * 360.0
    if colorsys.rgb_to_hsv(*rgb)[1] == 0.0:
        return None
    return hue


def hue_separation(value_a: str, value_b: str) -> float | None:
    """Degrees apart on the colour wheel (0..180), or None if either colour
    has no hue."""
    a, b = hue_degrees(value_a), hue_degrees(value_b)
    if a is None or b is None:
        return None
    delta = abs(a - b) % 360.0
    return min(delta, 360.0 - delta)


def palette_violations(palette: dict[str, str]) -> list[str]:
    """Every semantic-pair failure in one palette, as human-readable strings
    naming the pair and the measured ratio.

    `palette` is the palette's *effective* token map — defaults merged with
    whatever the theme and the project overrode — so a token nobody redefined
    is checked too: the default palette passing its own check is a property of
    the stylesheet, and a violation of it is a real one.
    """
    problems: list[str] = []
    for fg, bg in SEMANTIC_PAIRS:
        if fg not in palette or bg not in palette:
            continue
        ratio = contrast_ratio(palette[fg], palette[bg])
        if ratio is not None and ratio < MIN_CONTRAST:
            problems.append(
                f"{fg} on {bg} is {ratio:.2f}:1, below the {MIN_CONTRAST}:1 "
                f"WCAG AA minimum"
            )
    bad, good = BAD_GOOD_PAIR
    if bad in palette and good in palette:
        bad_value, good_value = palette[bad], palette[good]
        ratio = contrast_ratio(bad_value, good_value)
        separation = hue_separation(bad_value, good_value)
        separated_by_hue = separation is not None and separation >= MIN_BAD_GOOD_HUE_DEGREES
        separated_by_lightness = ratio is not None and ratio >= MIN_BAD_GOOD_CONTRAST
        if not separated_by_hue and not separated_by_lightness:
            hue_part = (
                f"{separation:.0f} degrees apart"
                if separation is not None
                else "not separable by hue"
            )
            ratio_part = f"{ratio:.2f}:1" if ratio is not None else "no measurable ratio"
            problems.append(
                f"{bad} ({bad_value}) and {good} ({good_value}) are not "
                f"distinguishable: {hue_part}, below "
                f"{MIN_BAD_GOOD_HUE_DEGREES:.0f} degrees, and {ratio_part} "
                f"against each other -- a verdict strip whose fail and pass "
                f"read alike is a correctness problem, not a taste one"
            )
    return problems
