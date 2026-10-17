"""Inline calc spans: ``name := rhs [| unit] = result`` in item prose.

docs/design/inline-calc.md section 1: a single-backtick Markdown code span
in a local item body, outside fenced code, whose content contains an
unquoted ``:=``, is inline calc. Once triggered, a span that fails the
grammar is an error at its line -- it never falls back to ordinary code.
A span without ``:=`` stays ordinary code; multi-backtick spans are the
author's escape hatch and are never triggered.

This module is the grammar only: extraction, the trigger, and the parse.
Evaluation threads the parsed span through the existing calc evaluator
(`src/refdes/calc.py`) in `build._run_item_calcs`; stored-result
verification lives in `compare_stored` here.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from . import calc

# The assigned name, `:=`, and everything after it (the RHS, optional
# `| unit`, delimiter and stored result are split out below). The grammar
# (design section 1) puts `wsp` (spaces/tabs) around every delimiter.
NAME_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]+:=[ \t]+(.*)$")

# The stored result: one numeric quantity literal, optionally with a unit.
# The number is exactly the calc lexer's number; the unit is exactly one
# unit run (or the bracketed escape hatch), so `2 V * 2` -- an expression,
# not a literal -- cannot match.
LITERAL_RE = re.compile(
    rf"^([+-]?(?:{calc._NUMBER}))(?:[ \t]*(?:\[[^\]]+\]|{calc._UNIT_RUN}))?$"
)

# A fence line: opens on ``` / ~~~ (CommonMark allows up to three leading
# spaces); a fence closes on a line of at least as many of the same
# character, with nothing after it. Inline spans are only recognized
# outside fences, and a line indented as an indented code block carries
# none either.
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


@dataclass
class InlineSpan:
    """One triggered span: parsed, with a parse-stage error if malformed.

    `line_offset` is the 0-indexed line of the span within the item body
    (add `Item.body_line` for the absolute source line, exactly like a
    calc fence's offset). `raw` is the span content as written, inside
    the backticks. When `error` is set the span is malformed: the build
    reports it at the line and the name/rhs/unit/result fields are
    meaningless.
    """

    line_offset: int
    raw: str
    name: str = ""
    rhs: str = ""
    unit: str = ""
    result: str = ""
    error: str | None = None


def contains_trigger(text: str) -> bool:
    """True when `text` contains a `:=` outside a quoted string."""
    quote = ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and text[i + 1:i + 2] == "=":
            return True
    return False


def code_spans(line: str) -> list[str]:
    """The single-backtick code spans of one line, in order.

    Markdown code-span rules: a span opens on a run of N backticks and
    closes on the next run of exactly N. Only N == 1 runs produce spans
    here -- a multi-backtick span's content (including any single
    backticks inside it) is skipped untouched, which is exactly the
    author's escape hatch the design names.
    """
    spans: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] != "`":
            i += 1
            continue
        start = i
        while i < n and line[i] == "`":
            i += 1
        run = i - start
        close = i
        closed = False
        while close < n:
            if line[close] != "`":
                close += 1
                continue
            run_end = close
            while run_end < n and line[run_end] == "`":
                run_end += 1
            if run_end - close == run:
                if run == 1:
                    spans.append(line[i:close])
                i = run_end
                closed = True
                break
            close = run_end
        if not closed:
            # An unclosed backtick run is literal text; `i` already sits
            # right after it, so scanning resumes from there.
            pass
    return spans


def _top_level_equals(text: str) -> list[int]:
    """Indices of every top-level ` = ` delimiter: a `=` flanked by spaces
    or tabs, outside quotes and outside parentheses/brackets. The final
    one is the `= result` delimiter, so an `=` inside a quoted `source()`
    argument or a parenthesized expression is never mistaken for it."""
    hits: list[int] = []
    quote = ""
    depth = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif (
            ch == "="
            and depth == 0
            and text[i - 1:i] in (" ", "\t")
            and text[i + 1:i + 2] in (" ", "\t")
        ):
            hits.append(i)
    return hits


def parse_span(line_offset: int, content: str) -> InlineSpan:
    """Parse one triggered span's content against the design grammar.

    `content` is the text inside the backticks. The caller has already
    checked `contains_trigger`; a span without `:=` is ordinary code and
    never comes here.
    """
    span = InlineSpan(line_offset=line_offset, raw=content)
    text = content.strip()

    hits = _top_level_equals(text)
    if not hits:
        # The only `=` in the span is the one in `:=` -- declared intent
        # with no stored result (design open question 4, decided: error).
        span.error = "stored result missing; write '= <quantity>'"
        return span

    cut = hits[-1]
    head = text[:cut].rstrip()
    tail = text[cut + 1:].strip()

    match = NAME_ASSIGN_RE.match(head)
    if match is None:
        span.error = (
            f"span {content.strip()!r} is not of the form "
            "`name := expression = result`; a calc name is letters, digits "
            "and underscores, starting with a letter or underscore"
        )
        return span
    name, rhs_unit = match.group(1), match.group(2).strip()

    span.name = name
    pipe = calc.PIPE_UNIT_RE.match(rhs_unit)
    if pipe:
        span.rhs = pipe.group("lhs").strip()
        span.unit = pipe.group("unit").strip()
    else:
        span.rhs = rhs_unit
        span.unit = ""
    span.result = tail

    if not span.rhs:
        span.error = f"nothing to evaluate: write `{name} := <expression> = <quantity>`"
        return span
    if not tail:
        # ` = ` flanked by whitespace with nothing after it (a trailing
        # bare `=` has no flanking whitespace and reads as no delimiter).
        span.error = "stored result missing; write '= <quantity>'"
        return span
    if not LITERAL_RE.match(tail):
        span.error = (
            f"stored result {tail!r} is not a quantity literal; write a "
            "number with an optional unit, e.g. '4.4 V' -- not an expression"
        )
        return span
    return span


def triggered_spans(body: str) -> list[InlineSpan]:
    """Every inline-calc span of one item body, in source order.

    Lines inside fenced code and indented code blocks are skipped; only
    single-backtick spans carrying an unquoted `:=` are parsed.
    """
    spans: list[InlineSpan] = []
    fence: str | None = None
    for offset, line in enumerate(body.splitlines()):
        if fence is None:
            open_match = FENCE_OPEN_RE.match(line)
            if open_match:
                fence = open_match.group(1)[0] * len(open_match.group(1))
                continue
            if line.startswith("    ") or line.startswith("\t"):
                continue
        else:
            close = FENCE_CLOSE_RE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = None
            continue
        for content in code_spans(line):
            if contains_trigger(content):
                spans.append(parse_span(offset, content))
    return spans


def compare_stored(value: calc.Value, span: InlineSpan, computed_text: str) -> str | None:
    """Verify a span's stored literal against the evaluated value.

    Returns None when the stored nominal is inside its precision window,
    a warning message when it is stale, and raises `calc.CalcError` for
    a malformed, nonfinite or unit-incompatible stored literal.

    The window (design section 2, recommended default accepted): the
    stored literal's last written place, including trailing zeros and
    any decimal exponent; a computed nominal within half of one unit of
    that place is accepted. At a boundary tie, round the computed
    nominal to that place on the decimal text, halves away from zero,
    and accept only when the rounded value equals the stored literal.
    Comparison is numeric -- `project.sigfigs` formats the recomputed
    quantity for the message only.
    """
    literal = LITERAL_RE.match(span.result)
    num = literal.group(1)
    try:
        stored = calc.parse_quantity(span.result)
    except calc.CalcError as exc:
        raise calc.CalcError(f"stored result {span.result!r} is not a valid quantity: {exc}")
    if not math.isfinite(stored.nom.magnitude):
        raise calc.CalcError(f"stored result {span.result!r} is not a finite quantity")
    try:
        computed = value.nom.to(stored.nom.units)
    except Exception as exc:  # noqa: BLE001 -- pint raises several types
        raise calc.CalcError(
            f"stored result {span.result!r} is not compatible with the "
            f"calculated units ({calc._display_units(value.nom.units)})"
        ) from exc
    if not math.isfinite(computed.magnitude):
        raise calc.CalcError("the calculated value is not a finite quantity")

    # The literal's place, on the decimal text as written: `4.4` has
    # place 0.1, `4.4e3` has place 100, `4 V` has place 1.
    mantissa, _, exp_text = num.partition("e")
    if not exp_text:
        mantissa, _, exp_text = num.partition("E")
    whole, dot, frac = mantissa.lstrip("+-").partition(".")
    decimals = len(frac) if dot else 0
    exp = int(exp_text) if exp_text else 0
    with localcontext() as ctx:
        ctx.prec = 60
        stored_dec = Decimal(num.lstrip("+")).scaleb(exp)
        computed_dec = Decimal(str(computed.magnitude))
        half = Decimal(5).scaleb(exp - decimals - 1)
        diff = computed_dec - stored_dec
        if abs(diff) < half:
            return None
        if abs(diff) > half:
            return f"stored result says {span.result}, now computes {computed_text}"
        # Boundary tie: round the computed nominal to the stored place,
        # halves away from zero, and accept only an exact match.
        rounded = computed_dec.quantize(
            Decimal(1).scaleb(exp - decimals), rounding=ROUND_HALF_UP
        )
        if rounded == stored_dec:
            return None
        return f"stored result says {span.result}, now computes {computed_text}"
