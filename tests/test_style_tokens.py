"""Proof that the finding-34 token-layer refactor is a visual no-op.

Resolves every ``var(--token)`` reference in the shipped stylesheet back to
its literal (a small resolver over the ``:root`` token blocks, no browser)
and asserts the resolved declaration set of every rule equals the original
stylesheet committed as ``tests/fixtures/style_before_tokens.css`` -- taken
from ``git show HEAD:src/refdes/templates/assets/style.css`` before the
refactor. Also asserts every ``var(--x)`` used is declared.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "src" / "refdes" / "templates" / "assets" / "style.css"
FIXTURE = ROOT / "tests" / "fixtures" / "style_before_tokens.css"

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")


def _strip_comments(css: str) -> str:
    return COMMENT_RE.sub("", css)


def _match_brace(css: str, i: int) -> int:
    """Index of the '}' closing the '{' at position i."""
    depth = 0
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    raise AssertionError("unbalanced braces")


def parse(css: str) -> list[tuple[str, str, str]]:
    """[(selector_path, property, value)] in document order.

    Values keep their raw text (whitespace-normalised); declarations inside
    at-rules get the at-rule prelude prefixed to their selector path so a
    rule inside ``@media print`` never compares against the same rule outside.
    """
    css = _strip_comments(css)
    decls: list[tuple[str, str, str]] = []
    i, n = 0, len(css)
    prelude_start = 0
    while i < n:
        c = css[i]
        if c == "{":
            prelude = " ".join(css[prelude_start:i].split())
            j = _match_brace(css, i)
            body = css[i + 1 : j]
            if prelude.startswith("@"):
                for sel, prop, val in parse(body):
                    decls.append((f"{prelude} | {sel}", prop, val))
            else:
                for prop, val in _declarations(body):
                    decls.append((prelude, prop, val))
            i = prelude_start = j + 1
        else:
            i += 1
    return decls


def _declarations(body: str) -> list[tuple[str, str]]:
    out = []
    for piece in body.split(";"):
        if ":" not in piece:
            continue
        head, _, _ = piece.partition(":")
        prop = " ".join(head.split()).lower()
        value = " ".join(piece[len(head) + 1 :].split())
        out.append((prop, value))
    return out


def tokens_of(css: str) -> dict[str, str]:
    """Every custom-property declaration in the file, last definition wins."""
    return {prop: val for _, prop, val in parse(css) if prop.startswith("--")}


def expand(value: str, tokens: dict[str, str]) -> str:
    """Resolve every var(--x) to its token value, recursively."""
    for _ in range(50):
        m = VAR_RE.search(value)
        if not m:
            return value
        name = m.group(1)
        assert name in tokens, f"var({name}) used but never declared"
        value = value[: m.start()] + tokens[name] + value[m.end() :]
    raise AssertionError(f"var expansion did not settle: {value!r}")


@pytest.fixture(scope="module")
def before():
    return parse(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def after():
    return parse(CSS.read_text(encoding="utf-8"))


# Git blob hash of the pre-refactor stylesheet, captured from
# `git show HEAD:src/refdes/templates/assets/style.css` before any edit
# (dd21c22f884d5deb18aa0ed1b8c35e1f60e72edd). Pinning the hash keeps this
# test honest after the refactor is itself committed.
FIXTURE_BLOB_SHA = "dd21c22f884d5deb18aa0ed1b8c35e1f60e72edd"


def test_fixture_is_the_pre_refactor_stylesheet():
    raw = FIXTURE.read_bytes()
    blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
    assert blob == FIXTURE_BLOB_SHA, (
        "tests/fixtures/style_before_tokens.css no longer matches the "
        "pre-refactor stylesheet it was captured from"
    )


def test_every_var_reference_is_declared(after):
    tokens = tokens_of(CSS.read_text(encoding="utf-8"))
    used = {
        name
        for _, _, value in after
        for name in VAR_RE.findall(value)
    }
    missing = sorted(used - set(tokens))
    assert not missing, f"undeclared tokens used: {missing}"


def test_expansion_terminates_and_is_cycle_free(after):
    tokens = tokens_of(CSS.read_text(encoding="utf-8"))
    for sel, prop, value in after:
        expand(value, tokens)  # asserts declared + settles
        assert VAR_RE.search(expand(value, tokens)) is None


def test_resolved_declarations_equal_the_original(before, after):
    before_tokens = tokens_of(FIXTURE.read_text(encoding="utf-8"))
    after_tokens = tokens_of(CSS.read_text(encoding="utf-8"))

    resolved_before = [
        (sel, prop, expand(val, before_tokens)) for sel, prop, val in before
    ]
    resolved_after = [
        (sel, prop, expand(val, after_tokens)) for sel, prop, val in after
    ]

    # The refactor may only ADD declarations of brand-new custom properties,
    # inside a plain :root token block. Everything else must resolve 1:1,
    # in order, against the original.
    new_token_names = set(after_tokens) - set(before_tokens)
    filtered = [
        d
        for d in resolved_after
        if not (d[1] in new_token_names and d[0].endswith(":root"))
    ]

    assert filtered == resolved_before, _first_difference(filtered, resolved_before)


def test_original_colour_tokens_unchanged(before, after):
    before_tokens = tokens_of(FIXTURE.read_text(encoding="utf-8"))
    after_tokens = tokens_of(CSS.read_text(encoding="utf-8"))
    for name, value in before_tokens.items():
        assert after_tokens.get(name) == value, f"token {name} changed value"


def test_no_selectors_added_or_removed(before, after):
    assert {sel for sel, _, _ in after} == {sel for sel, _, _ in before}


def _first_difference(actual, expected) -> str:
    for a, e in zip(actual, expected):
        if a != e:
            return f"first difference:\n  expected (original): {e}\n  got (resolved):    {a}"
    return f"length differs: resolved {len(actual)} vs original {len(expected)}"
