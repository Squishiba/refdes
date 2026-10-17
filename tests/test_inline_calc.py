"""Inline calc spans: `name := rhs [| unit] = result` in item prose.

Slice 1 of docs/design/inline-calc.md: a single-backtick span with an
unquoted `:=` in a local item body is inline calc -- evaluated with the
existing calc evaluator in the item's environment, its stored result
verified numerically. `check` and `build` report the same diagnostics and
never rewrite the source. A triggered span that fails the grammar is an
error; a span without `:=` stays ordinary code, and multi-backtick spans
are the author's escape hatch.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import inline_calc, parse
from refdes.schema import load_project

BASIC_CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)


def _build(tmp_path, body, config=BASIC_CONFIG):
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{body}", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


# --------------------------------------------------------------- the trigger


def test_trigger_requires_unquoted_colon_equal():
    assert inline_calc.contains_trigger("Vout := 2 V = 2 V")
    assert not inline_calc.contains_trigger("V_cl = 0.8 V")
    assert not inline_calc.contains_trigger('source("f.csv", "a:=b")')
    assert inline_calc.contains_trigger('x := source("f.csv", "a:=b")')


def test_single_backtick_spans_are_extracted_from_a_line():
    assert inline_calc.code_spans("`a` mid `b := 1 = 1`") == ["a", "b := 1 = 1"]
    # Multi-backtick spans are skipped: their content is ordinary code.
    assert inline_calc.code_spans("``x := 1 = 1``") == []
    # A single backtick inside a multi-backtick span is literal text.
    assert inline_calc.code_spans("``a ` b := 1 = 1``") == []
    # An unclosed run is literal text.
    assert inline_calc.code_spans("`unclosed") == []


# ------------------------------------------------------- the span grammar


def test_parse_valid_span_with_unit():
    span = inline_calc.parse_span(0, "Vout := 0.8 V * (1 + Rtop/Rbot) | V = 4.436 V")
    assert span.error is None
    assert (span.name, span.unit, span.result) == ("Vout", "V", "4.436 V")
    assert span.rhs == "0.8 V * (1 + Rtop/Rbot)"


def test_parse_valid_span_without_unit():
    span = inline_calc.parse_span(0, "I_load := 1.2 A = 1.2 A")
    assert span.error is None
    assert (span.name, span.unit, span.rhs, span.result) == (
        "I_load", "", "1.2 A", "1.2 A",
    )


def test_missing_stored_result_is_a_malformed_span():
    span = inline_calc.parse_span(0, "Vout := 2 V * 2")
    assert span.error is not None
    assert "stored result missing" in span.error
    assert "= <quantity>" in span.error


def test_trailing_bare_equals_is_still_missing_result():
    # A bare `=` with nothing after it is not the ` = ` delimiter at all;
    # the span's only `=` is the `:=`, so it reads as a missing result.
    span = inline_calc.parse_span(0, "Vout := 2 V * 2 =")
    assert span.error is not None
    assert "stored result missing" in span.error


def test_span_with_result_whitespace_but_no_value_is_malformed():
    span = inline_calc.parse_span(0, "Vout := 2 V * 2 =   x")
    assert span.error is not None
    assert "not a quantity literal" in span.error


def test_invalid_name_is_malformed():
    span = inline_calc.parse_span(0, "1x := 2 V = 2 V")
    assert span.error is not None
    assert "name :=" in span.error


def test_name_without_space_before_colon_equal_is_malformed():
    # The grammar puts wsp around every delimiter; `x:=` is not it.
    span = inline_calc.parse_span(0, "x:= 1 V = 1 V")
    assert span.error is not None


def test_empty_rhs_is_malformed():
    span = inline_calc.parse_span(0, "x := = 1 V")
    assert span.error is not None


def test_stored_result_must_be_a_literal_not_an_expression():
    span = inline_calc.parse_span(0, "x := 1 V = 2 V * 2")
    assert span.error is not None
    assert "not a quantity literal" in span.error


def test_stored_result_accepts_signed_and_exponent_numbers():
    assert inline_calc.parse_span(0, "x := 1 V = -1.2 V").error is None
    assert inline_calc.parse_span(0, "x := 1 V = 1.2e3 V").error is None
    assert inline_calc.parse_span(0, "x := 1kohm = 1.2e3").error is None


def test_delimiter_ignores_equals_in_quotes_and_parentheses():
    span = inline_calc.parse_span(
        0, 'x := source("f.csv", "a = b") | W = 5 W'
    )
    assert span.error is None
    assert span.rhs == 'source("f.csv", "a = b")'
    assert span.result == "5 W"
    span = inline_calc.parse_span(0, "x := (2 = 3) = 6 V")
    assert span.error is None
    assert span.rhs == "(2 = 3)"
    assert span.result == "6 V"


def test_unit_slot_sits_between_rhs_and_result():
    # The design pins `| unit` before `= result`; a pipe-form spelling
    # (`x | V := ...`) is malformed -- the name must come first.
    assert inline_calc.parse_span(0, "x | V := 2 = 2 V").error is not None
    span = inline_calc.parse_span(0, "P := 3.3 V * 1.2 A | mW = 3960 mW")
    assert span.error is None
    assert (span.unit, span.result) == ("mW", "3960 mW")


# --------------------------------------------------- body-level extraction


def test_triggered_spans_skip_fences_and_ordinary_spans():
    body = "\n".join(
        [
            "Prose `V_cl = 0.8 V` stays code.",          # no := -> ordinary
            "`Vout := 2 V * 2 = 4 V` triggers.",         # span 0
            "```calc",
            "`V := 1 V = 9 V` inside a calc fence.",     # fenced: skipped
            "V = 1 V",
            "```",
            "```text",
            "`V := 1 V = 9 V` inside any fence.",        # fenced: skipped
            "```",
            "~~~",
            "`V := 1 V = 9 V` inside a tilde fence.",    # fenced: skipped
            "~~~",
            "    `V := 1 V = 9 V` in an indented block.",  # indented: skipped
            "``x := 2 V = 5 V`` escapes with two backticks.",  # multi: skipped
            "`a := 1 V = 1 V` and `b := 2 V = 2 V` are two spans.",
        ]
    )
    spans = inline_calc.triggered_spans(body)
    assert [(s.line_offset, s.name) for s in spans] == [
        (1, "Vout"),
        (14, "a"),
        (14, "b"),
    ]


def test_triggered_malformed_span_keeps_its_line_offset():
    body = "line one\n`Vout := 2 V * 2` is missing its result"
    spans = inline_calc.triggered_spans(body)
    assert len(spans) == 1
    assert spans[0].line_offset == 1
    assert spans[0].error is not None
