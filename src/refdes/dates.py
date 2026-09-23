"""Project date-format validation and strict calendar-date parsing."""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

DEFAULT_DATE_FORMAT = "YYYY-MM-DD"
_FORMAT_RE = re.compile(r"^(YYYY|MM|DD)([-/.])(YYYY|MM|DD)\2(YYYY|MM|DD)$")
_TOKEN_PATTERNS = {
    "YYYY": r"(?P<year>\d{4})",
    "MM": r"(?P<month>\d{2})",
    "DD": r"(?P<day>\d{2})",
}


def validate_format(value: object) -> str:
    """Return a supported format string or reject it."""
    if not isinstance(value, str):
        raise TypeError("must be a string using YYYY, MM, and DD placeholders")
    match = _FORMAT_RE.fullmatch(value)
    if match is None or {match.group(1), match.group(3), match.group(4)} != {
        "YYYY",
        "MM",
        "DD",
    }:
        raise ValueError(
            "must use YYYY, MM, and DD exactly once, separated by one repeated '-', '/', or '.'"
        )
    return value


@lru_cache(maxsize=6)
def _value_pattern(date_format: str) -> re.Pattern[str]:
    validated = validate_format(date_format)
    first, _separator, second, third = _FORMAT_RE.fullmatch(validated).groups()  # type: ignore[union-attr]
    return re.compile(
        "^"
        + _TOKEN_PATTERNS[first]
        + r"(?P<separator>[-/.])"
        + _TOKEN_PATTERNS[second]
        + r"(?P=separator)"
        + _TOKEN_PATTERNS[third]
        + "$"
    )


def format_date(value: date, date_format: str) -> str:
    """Render one calendar date in the project's configured format -- the
    write-side counterpart of `parse_date`, so a date the tool creates (a new
    log entry's `date:`, say) is spelled the way the project spells dates and
    reparses as the same day. The format is validated first, so this can only
    ever produce what `parse_date` accepts."""
    validated = validate_format(date_format)
    first, separator, second, third = _FORMAT_RE.fullmatch(validated).groups()  # type: ignore[union-attr]
    parts = {
        "YYYY": f"{value.year:04d}",
        "MM": f"{value.month:02d}",
        "DD": f"{value.day:02d}",
    }
    return separator.join((parts[first], parts[second], parts[third]))


def parse_date(value: object, date_format: str) -> date:
    """Parse one strict date, accepting ``-``, ``/``, or ``.`` separators."""
    match = _value_pattern(date_format).fullmatch(str(value))
    if match is None:
        raise ValueError(f"date does not match {date_format}")
    return date(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
    )
