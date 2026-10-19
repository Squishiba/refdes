"""Inline calc spans: ``name := rhs [| unit] = result`` in item prose.

docs/design/inline-calc.md section 1: a single-backtick Markdown code span
in a local item body, outside fenced code and outside an HTML comment,
whose content contains an unquoted ``:=``, is inline calc. Once triggered, a
span that fails the grammar is an error at its line -- it never falls back
to ordinary code. A span without ``:=`` stays ordinary code; multi-backtick
spans are the author's escape hatch and are never triggered.

This module is the grammar only: extraction, the trigger, the parse, and
the grammar-level discovery of what a parsed span's right-hand side names
(a cross-item reference, a `source()` call). Evaluation threads the parsed
span through the existing calc evaluator (`src/refdes/calc.py`) in
`build._run_item_calcs`; stored-result verification lives in
`compare_stored` here.
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

# An HTML comment runs from `<!--` to the first `-->` (CommonMark raw HTML).
# Inline spans inside one are inert, exactly as inside a fence (run-12
# F12-1). Comments do not nest: a `<!--` under an open comment is ordinary
# text, and the first `-->` closes it.
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"

# Mirrors `parse.UNCLOSED_FENCE_WARNING` for the comment analogue (run-12
# F12-1): an unclosed `<!--` does not silently swallow the rest of the body
# for span purposes -- it is reported once, at the opener's line.
UNCLOSED_COMMENT_WARNING = (
    "unclosed HTML comment: the rest of the body is comment text, so inline "
    "calc spans under this line are not checked; close the comment with '-->'"
)

# A whole calc name: letters, digits and underscores, starting with a letter
# or underscore (the same alphabet `NAME_ASSIGN_RE` captures). Used to tell a
# genuine `name :=` head from an ambiguous span whose `:=` is not preceded by
# a name (run-12 F12-2).
CALC_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


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


def first_trigger_index(text: str) -> int:
    """Index of the `:` in the first `:=` outside a quoted string, or -1.

    The span's head is everything before it, so its trailing text is the
    intended calc name (run-12 F12-2). `contains_trigger` is exactly
    `first_trigger_index(text) >= 0`; this variant returns the position so
    the parser can inspect what precedes the trigger."""
    quote = ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and text[i + 1:i + 2] == "=":
            return i
    return -1


def code_span_ranges(line: str) -> list[tuple[int, int]]:
    """The ``(start, end)`` content ranges of a line's single-backtick code
    spans, in order.

    Markdown code-span rules: a span opens on a run of N backticks and
    closes on the next run of exactly N. Only N == 1 runs produce spans
    here -- a multi-backtick span's content (including any single
    backticks inside it) is skipped untouched, which is exactly the
    author's escape hatch the design names. An unclosed backtick run is
    literal text; scanning resumes right after it.

    The ranges are what a rewriter needs to know where a span sits in the
    line (links._calc_ref_rewrites); `code_spans` is the content view.
    """
    spans: list[tuple[int, int]] = []
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
                    spans.append((i, close))
                i = run_end
                closed = True
                break
            close = run_end
        if not closed:
            pass
    return spans


def _result_equals_positions(text: str) -> list[int]:
    """Indices of every top-level result-separator candidate: a bare ` = `
    at any spacing, outside quotes and outside parentheses/brackets. The
    last such candidate whose tail is a quantity literal is the `= result`
    delimiter (run-12 F12-3 relaxed the flanking-space requirement, so
    `x := 1 V*4|V=4 V` is accepted).

    A `=` is excluded when it is part of a delimiter the grammar owns
    elsewhere and can therefore never be the result separator: the `=` of a
    `:=` (preceded by `:`), and every comparison operator the evaluator's
    Python AST parses (`==`, `<=`, `>=`, `!=`) -- i.e. a `=` adjacent to one
    of `: < > ! =` on the left, or followed by `=`. The calc language itself
    has no valid `=` in an expression (a bare `=` is a Python ``eval``
    syntax error, a comparison parses to ``ast.Compare`` which
    `calc._eval_node` rejects), so the only legitimate `=` in a head is the
    one in `:=`; every other top-level `=` is a separator candidate."""
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
        elif ch == "=" and depth == 0:
            prev = text[i - 1:i]
            nxt = text[i + 1:i + 2]
            if prev in (":", "<", ">", "!", "=") or nxt == "=":
                continue
            hits.append(i)
    return hits


def code_spans(line: str) -> list[str]:
    """The single-backtick code spans of one line, in order (the content
    view of `code_span_ranges`)."""
    return [line[start:end] for start, end in code_span_ranges(line)]


def _split_readings(text: str, positions: list[int]) -> list[tuple[int, str, str, str]]:
    """Every split of `text` at a result-separator candidate that parses as
    ``name := rhs [| unit] = result``: a ``(cut, name, rhs_unit, result)``
    for each candidate whose head matches `NAME_ASSIGN_RE` and whose tail is
    a quantity literal. ``len(...) > 1`` means the span is genuinely
    ambiguous -- more than one reading is a valid whole calc -- so the
    parser reports it instead of picking one (run-12 F12-3). For the current
    grammar this is structurally unreachable (a stored-result literal cannot
    itself contain a top-level `=`), so it is a defensive guard, not a
    reachable state; the multi-`=` spans a reader writes (``x := 1 = 2 = 3``)
    have exactly one literal tail and are not ambiguous."""
    readings: list[tuple[int, str, str, str]] = []
    for cut in positions:
        head = text[:cut].rstrip()
        tail = text[cut + 1:].strip()
        match = NAME_ASSIGN_RE.match(head)
        if match is not None and tail and LITERAL_RE.match(tail):
            readings.append((cut, match.group(1), match.group(2).strip(), tail))
    return readings


def span_cross_ref(span: InlineSpan) -> re.Match[str] | None:
    """The cross-item reference a parsed span's RHS is -- `TARGET.NAME` as
    the whole (unit-stripped) right-hand side, matched with the evaluator's
    own `CROSS_REF_RE`, so a span is a reference here exactly when it is one
    in `evaluate_block`. None for a malformed span and for every other RHS."""
    if span.error:
        return None
    return calc.CROSS_REF_RE.match(span.rhs.strip())


def span_source_call(span: InlineSpan) -> tuple[str, str] | None:
    """`(path, key)` for a parsed span whose RHS is a well-formed `source()`
    call, None otherwise -- the span counterpart of `calc.source_calls_in_block`
    (the pipe unit is already split off by `parse_span`, as the evaluator
    strips it for a fence line)."""
    if span.error:
        return None
    if not calc.SOURCE_START_RE.match(span.rhs.strip()):
        return None
    parsed = calc.parse_source_call(span.rhs)
    return (parsed[0], parsed[1]) if parsed else None


def parse_span(line_offset: int, content: str) -> InlineSpan:
    """Parse one triggered span's content against the design grammar.

    `content` is the text inside the backticks. The caller has already
    checked `contains_trigger`; a span without `:=` is ordinary code and
    never comes here.
    """
    span = InlineSpan(line_offset=line_offset, raw=content)
    text = content.strip()

    trigger = first_trigger_index(text)
    head_name = text[:trigger].rstrip() if trigger >= 0 else ""
    if trigger < 0 or not CALC_NAME_RE.match(head_name):
        # The span triggered on an unquoted `:=` but the text before it is
        # not a calc name (run-12 F12-2): the confusing reading is that this
        # is literal prose (`src=a:=b.csv`), the intended one that it is a
        # calc whose head the author typo'd. Keep it an error, name the
        # offending head, and tell the author both ways out.
        span.error = (
            f"{head_name!r} is not a calc name before `:=`; if this is "
            "literal text, use a double-backtick span; if it is a calc, "
            "write `name := expression = result`"
        )
        return span

    positions = _result_equals_positions(text)
    readings = _split_readings(text, positions)
    if len(readings) > 1:
        both = " and ".join(
            f"`{name} := {rhs_unit} = {result}`" for _c, name, rhs_unit, result in readings
        )
        span.error = (
            f"the result separator is ambiguous, it reads two ways: {both}; "
            "a calc has one ` = result` and its expression has no other `=` "
            "(there are no comparisons) -- write the expression without a "
            "second `=`"
        )
        return span

    if readings:
        # Exactly one reading is a complete, well-formed calc.
        _cut, name, rhs_unit, tail = readings[0]
    elif not positions:
        # The only `=` in the span is the one in `:=` -- declared intent
        # with no stored result (design open question 4, decided: error).
        span.error = "stored result missing; write '= <quantity>'"
        return span
    else:
        # There is a separator `=` but no reading is a whole calc: report
        # against the last candidate, the way the grammar reads a trailing
        # result slot (a trailing bare `=` has no tail -> missing result;
        # a non-literal tail -> not a quantity literal; a head without a
        # valid `name :=` -> not of the form).
        cut = positions[-1]
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


def _scan_comment_line(line: str, in_comment: bool) -> tuple[list[tuple[int, int]], bool, bool]:
    """Content ranges of the single-backtick code spans of one line that sit
    outside an HTML comment, given the comment state entering the line.

    Returns ``(ranges, in_comment_out, opened_on_this_line)``. Scanning is
    left-to-right and interleaves the two inline constructs, so each is
    literal text inside the other: a `<!--` inside a code span is ordinary
    span text, a backtick inside a comment never opens a span. A code span
    is captured with the same delimiter-run rule as `code_span_ranges` (only
    runs of exactly one backtick); an unclosed run is literal text and
    scanning resumes right after it."""
    spans: list[tuple[int, int]] = []
    n = len(line)
    i = 0
    opened = False
    while i < n:
        if in_comment:
            close = line.find(COMMENT_CLOSE, i)
            if close < 0:
                break  # the rest of the line is comment text
            in_comment = False
            i = close + len(COMMENT_CLOSE)
            continue
        if line.startswith(COMMENT_OPEN, i):
            in_comment = True
            opened = True
            i += len(COMMENT_OPEN)
            continue
        if line[i] == "`":
            start = i
            while i < n and line[i] == "`":
                i += 1
            run = i - start
            close = i
            while close < n:
                if line[close] != "`":
                    close += 1
                    continue
                run_end = close
                while run_end < n and line[run_end] == "`":
                    run_end += 1
                if run_end - close == run:
                    if run == 1:
                        spans.append((i, close))
                    i = run_end
                    break
                close = run_end
            # Whether closed by a matching run (i sits past it) or unclosed
            # (i sits right after the opening run), resume scanning there.
            continue
        i += 1
    return spans, in_comment, opened


def _scan_body(lines: list[str]) -> tuple[list[tuple[int, int, int, str]], int | None]:
    """The triggered inline-calc spans of the given lines (source order), as
    ``(line_offset, content_start, content_end, content)`` -- positions
    included, so a rewriter can replace a span's content in place (the
    link-target expansion of `links._calc_ref_rewrites`) -- and the 0-indexed
    line of an unclosed `<!--` opener (else None).

    Lines inside fenced code, indented code blocks, and HTML comments are
    skipped -- a span in any of them is inert (run-12 F12-1). A fence opened
    in ordinary text ignores comment markers (they are code); a comment
    opened in ordinary text ignores fence lines (they are comment text), so
    the two inert regions never open inside each other. A `<!--` with no
    `-->` treats the rest of the body as comment text and reports its line
    once, mirroring the unclosed-fence warning; it never swallows the body
    silently.

    Fences and comments are *assumed* self-contained within the slice handed
    in -- an item body satisfies this (and callers must not hand in front
    matter, where an unclosed fence marker in a block scalar is valid YAML),
    so a body slice needs no inert-region context from outside the slice."""
    found: list[tuple[int, int, int, str]] = []
    fence: str | None = None
    in_comment = False
    comment_open_line: int | None = None
    for offset, line in enumerate(lines):
        if fence is not None:
            close = FENCE_CLOSE_RE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = None
            continue
        if not in_comment:
            open_match = FENCE_OPEN_RE.match(line)
            if open_match:
                fence = open_match.group(1)[0] * len(open_match.group(1))
                continue
            if line.startswith("    ") or line.startswith("\t"):
                continue
        line_spans, in_comment, opened = _scan_comment_line(line, in_comment)
        if in_comment:
            # A `<!--` opened on this line is the comment open at the line's
            # end -- even when an earlier comment on the same line opened and
            # closed first -- so a comment closed mid-line and a second left
            # unclosed is attributed to the second opener. A comment carried
            # over from a previous line keeps the line that opened it.
            if opened or comment_open_line is None:
                comment_open_line = offset
        else:
            comment_open_line = None
        for start, end in line_spans:
            content = line[start:end]
            if contains_trigger(content):
                found.append((offset, start, end, content))
    return found, (comment_open_line if in_comment else None)


def iter_triggered_spans(lines: list[str]) -> list[tuple[int, int, int, str]]:
    """The triggered inline spans of the given lines, in source order, as
    ``(line_offset, content_start, content_end, content)`` -- the positioned
    view of `_scan_body` (its second return value, the unclosed-comment
    line, is the build's warning business, not the rewriter's).

    Fences and comments are *assumed* self-contained within the slice handed
    in -- see `_scan_body`."""
    return _scan_body(lines)[0]


def triggered_spans(body: str) -> list[InlineSpan]:
    """Every inline-calc span of one item body, in source order.

    Lines inside fenced code, indented code blocks and HTML comments are
    skipped; only single-backtick spans carrying an unquoted `:=` are parsed.
    """
    return [
        parse_span(line_offset, content)
        for line_offset, _start, _end, content in _scan_body(body.splitlines())[0]
    ]


def unclosed_comment_offset(body: str) -> int | None:
    """The 0-indexed line of an unclosed ``<!--`` in `body`, or None.

    The build warns there so a comment that never closes cannot silently
    stop the body's spans from being checked (run-12 F12-1)."""
    return _scan_body(body.splitlines())[1]


_PLAIN_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")


def _half_of_place(text: str) -> Decimal:
    """Half of one unit of a decimal text's last written place: `4.436`
    -> 0.0005, `4` -> 0.5, `1.235e+06` -> 500. This is the rounding
    interval a reader reads a displayed number with."""
    mantissa, _, exp_text = text.partition("e")
    if not exp_text:
        mantissa, _, exp_text = text.partition("E")
    whole, dot, frac = mantissa.lstrip("+-").partition(".")
    decimals = len(frac) if dot else 0
    exp = int(exp_text) if exp_text else 0
    return Decimal(5).scaleb(exp - decimals - 1)


def _stale_message(
    span: InlineSpan,
    computed_text: str,
    computed_dec: Decimal,
    stored_dec: Decimal,
    half: Decimal,
) -> str:
    """The stale-result warning. The displayed computed value must not
    read as accepted: when the rounded display lands inside the stored
    literal's window -- run-12 F12-4, a raw 3.4495 shown as `3.45 V`
    against stored `3.5 V`, which the author then reads as passing the
    3.5 +/- 0.05 window -- the raw value replaces it, and the gap is
    visible. What is *accepted* is the window rule above, decided on
    full values; this decides only what is *shown*."""
    text = computed_text.strip()
    number = _PLAIN_NUMBER_RE.match(text)
    if number is not None:
        shown = Decimal(number.group())
        shown_half = _half_of_place(number.group())
        inside_window = not (
            shown + shown_half < stored_dec - half
            or shown - shown_half > stored_dec + half
        )
        if inside_window:
            text = f"{computed_dec.normalize():f}{text[number.end():]}"
    return f"stored result says {span.result}, now computes {text}"


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
    quantity for the message only, widened to full precision whenever
    the rounded display would itself sit inside the window (see
    `_stale_message`); the window rule is unchanged.
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
        stored_dec = Decimal(mantissa.lstrip("+")).scaleb(exp)
        computed_dec = Decimal(str(computed.magnitude))
        half = Decimal(5).scaleb(exp - decimals - 1)
        diff = computed_dec - stored_dec
        if abs(diff) < half:
            return None
        if abs(diff) > half:
            return _stale_message(span, computed_text, computed_dec, stored_dec, half)
        # Boundary tie: round the computed nominal to the stored place,
        # halves away from zero, and accept only an exact match.
        rounded = computed_dec.quantize(
            Decimal(1).scaleb(exp - decimals), rounding=ROUND_HALF_UP
        )
        if rounded == stored_dec:
            return None
        return _stale_message(span, computed_text, computed_dec, stored_dec, half)
