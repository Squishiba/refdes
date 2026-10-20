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
from refdes import cli as cli_mod
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


# ------------------------------------------- evaluation in the item's env


def _item(project, item_id="DEC-001"):
    return project.item_by_id(item_id)


def _inline_errors(project):
    return [d for d in project.errors if d.message.startswith("inline calc ")]


def test_span_assigns_for_a_later_fence(tmp_path):
    project = _build(
        tmp_path,
        "`Rbot := 2.2 kohm = 2.2 kohm`\n\n```calc\nG = 10 kohm / Rbot | 1\n```\n",
    )
    assert project.errors == []
    assert _item(project).calc_values["G"] == "4.545"


def test_fence_value_used_by_a_later_span(tmp_path):
    project = _build(
        tmp_path, "```calc\nVin = 5 V\n```\n\n`Vout := Vin * 2 = 10 V`\n"
    )
    assert project.errors == []


def test_span_uses_an_earlier_span(tmp_path):
    project = _build(tmp_path, "`a := 2 V = 2 V`\n\n`b := a * 2 = 4 V`\n")
    assert project.errors == []
    assert _item(project).calc_values["b"] == "4 V"


def test_forward_use_of_a_later_fence_name_is_unknown_name(tmp_path):
    project = _build(
        tmp_path, "`Vout := Vin * 2 = 10 V`\n\n```calc\nVin = 5 V\n```\n"
    )
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "unknown name 'Vin'" in errs[0].message
    # The item file is `---\nid\ntype\n---\n` (4 lines), then a blank body
    # line, then the span: line 6 of the file.
    assert errs[0].line == 6
    assert errs[0].file.endswith("dec.md")
    assert errs[0].item_id == "DEC-001"


def test_duplicate_name_across_span_and_fence_cites_both_lines(tmp_path):
    project = _build(
        tmp_path, "```calc\nV = 1 V\n```\n\n`V := 2 V = 2 V`\n"
    )
    errs = _inline_errors(project)
    assert len(errs) == 1
    message = errs[0].message
    assert "assigned twice" in message
    assert "first at line 7" in message  # the fence's `V = 1 V` line
    assert "again at line 10" in message  # the span line


def test_duplicate_name_between_two_spans(tmp_path):
    project = _build(tmp_path, "`x := 1 V = 1 V`\n\n`x := 2 V = 2 V`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "assigned twice" in errs[0].message
    assert "first at line 6" in errs[0].message
    assert "again at line 8" in errs[0].message


def test_malformed_span_is_an_error_at_its_line(tmp_path):
    project = _build(tmp_path, "`Vout := 2 V * 2` has no stored result\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "stored result missing" in errs[0].message
    assert errs[0].line == 6
    assert errs[0].file.endswith("dec.md")
    assert errs[0].item_id == "DEC-001"


def test_span_without_trigger_stays_ordinary_code(tmp_path):
    project = _build(
        tmp_path,
        "`V_cl = 0.8 V` is ordinary code\n\n``V := 2 V = 9 V`` escapes too\n",
    )
    assert project.errors == []
    assert _inline_errors(project) == []
    assert "<code>V_cl = 0.8 V</code>" in _item(project).body_html
    assert "<code>V := 2 V = 9 V</code>" in _item(project).body_html


def test_span_value_renders_in_prose(tmp_path):
    project = _build(
        tmp_path, "`P := 3.3 V * 1.2 A | W = 3.96 W`\n\nDissipation: {{P}}\n"
    )
    assert project.errors == []
    assert "Dissipation: <code>3.96 W</code>" in _item(project).body_html
    assert "<code>P := 3.3 V * 1.2 A | W = 3.96 W</code>" in _item(project).body_html


# -------------------------------------------------- the severity table


def _inline_warnings(project):
    return [d for d in project.warnings if d.message.startswith("inline calc ")]


def test_the_design_probe_item_warns_and_check_stays_clean_of_errors(tmp_path):
    # The design's probe: a deliberately wrong stored result. It is a
    # warning, not a build failure (D1: report it, never rewrite it).
    project = _build(tmp_path, "`Vout := 2 V * 2 = 5 V`\n")
    assert project.errors == []
    warns = _inline_warnings(project)
    assert len(warns) == 1
    assert warns[0].message == (
        "inline calc Vout: stored result says 5 V, now computes 4 V"
    )


def test_the_design_example_message_shape(tmp_path):
    project = _build(
        tmp_path,
        "`Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.52 V`\n",
    )
    warns = _inline_warnings(project)
    assert len(warns) == 1
    assert warns[0].message == (
        "inline calc Vout: stored result says 4.52 V, now computes 4.436 V"
    )
    assert warns[0].line == 6
    assert project.errors == []


def test_coarse_literal_accepts_within_half_its_last_place(tmp_path):
    # Design: `4.4 V` accepts 4.436 V -- half-place is 0.05 V.
    project = _build(
        tmp_path,
        "`Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.4 V`\n",
    )
    assert project.errors == []
    assert _inline_warnings(project) == []


def test_fine_literal_rejects_the_same_drift(tmp_path):
    # Design: `4.436 V` rejects 4.52 V -- half-place is 0.0005 V.
    project = _build(tmp_path, "`x := 4.52 = 4.436`\n")
    warns = _inline_warnings(project)
    assert len(warns) == 1
    assert "stored result says 4.436, now computes 4.52" in warns[0].message


def test_window_edges_both_sides(tmp_path):
    project = _build(tmp_path, "`x := 4.449999 = 4.4`\n")  # 0.049999 < 0.05
    assert _inline_warnings(project) == []
    project = _build(tmp_path, "`x := 4.450001 = 4.4`\n")  # 0.050001 > 0.05
    assert len(_inline_warnings(project)) == 1


def test_boundary_tie_rounds_halves_away_from_zero(tmp_path):
    # computed 4.45 with stored 4.5: exactly half a place; rounding the
    # computed nominal to the stored place gives 4.5 == 4.5 -> accepted.
    project = _build(tmp_path, "`x := 4.45 = 4.5`\n")
    assert project.errors == [] and _inline_warnings(project) == []
    # stored 4.4: the rounded 4.5 is not 4.4 -> stale.
    project = _build(tmp_path, "`x := 4.45 = 4.4`\n")
    assert len(_inline_warnings(project)) == 1
    # Negative halves go away from zero as well: -4.5 rounds to -5.
    project = _build(tmp_path, "`x := -4.5 = -5`\n")
    assert _inline_warnings(project) == []
    project = _build(tmp_path, "`x := -4.5 = -4`\n")
    assert len(_inline_warnings(project)) == 1


def test_trailing_zeros_tighten_the_window(tmp_path):
    project = _build(tmp_path, "`x := 4.04 = 4.0`\n")  # half-place 0.05
    assert _inline_warnings(project) == []
    project = _build(tmp_path, "`x := 4.06 = 4.0`\n")
    assert len(_inline_warnings(project)) == 1


def test_decimal_exponent_scales_the_window(tmp_path):
    # `1.2e3`: last written place 100, half-window 50.
    project = _build(tmp_path, "`x := 1230 = 1.2e3`\n")
    assert _inline_warnings(project) == []
    project = _build(tmp_path, "`x := 1300 = 1.2e3`\n")
    assert len(_inline_warnings(project)) == 1


def test_dimensionless_results_use_the_same_rule(tmp_path):
    project = _build(tmp_path, "`k := 0.54 = 0.5`\n")
    assert _inline_warnings(project) == []
    project = _build(tmp_path, "`k := 0.56 = 0.5`\n")
    assert len(_inline_warnings(project)) == 1


def test_stored_literal_may_use_a_compatible_unit(tmp_path):
    # Not named `V` here: the fence evaluator's ambiguity warning fires
    # when a variable shares a unit symbol's name, span or fence.
    project = _build(tmp_path, "`Vout := 4.4 V = 4400 mV`\n")
    assert project.errors == []
    assert _inline_warnings(project) == []


def test_incompatible_unit_in_the_stored_literal_is_an_error(tmp_path):
    project = _build(tmp_path, "`I := 1.2 A = 1.2 V`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "not compatible with the calculated units" in errs[0].message
    assert errs[0].line == 6


def test_unit_assertion_mismatch_is_an_error(tmp_path):
    project = _build(tmp_path, "`V := 1.2 A | V = 1.2 V`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "declared as V" in errs[0].message


def test_evaluation_failure_is_an_error_at_the_span(tmp_path):
    project = _build(tmp_path, "`P := Rtop * 1 A = 1 W`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "unknown name 'Rtop'" in errs[0].message
    assert errs[0].line == 6


def test_nonfinite_stored_literal_is_an_error(tmp_path):
    project = _build(tmp_path, "`x := 1 V = 1e999 V`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "not a finite quantity" in errs[0].message


def test_unknown_unit_in_the_literal_is_an_error(tmp_path):
    project = _build(tmp_path, "`x := 1 V = 1 glorp`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "not a valid quantity" in errs[0].message


def test_source_untouched_after_check_and_build(tmp_path):
    project = _build(tmp_path, "`Vout := 2 V * 2 = 5 V`\n")
    item_file = tmp_path / "items" / "dec.md"
    before = item_file.read_bytes()
    # The check path: cmd_check calls build(seal_write=False).
    build_mod.build(project, seal_write=False, reseal=False)
    assert item_file.read_bytes() == before
    assert "5 V" in item_file.read_text()  # the stale value stays as authored


def test_check_and_build_report_the_same_thing(tmp_path):
    body = "`Vout := 2 V * 2 = 5 V`\n\n`I := 1.2 A = 1.2 V`\n"

    def diags(project):
        return sorted(
            (d.level, d.message, d.line)
            for d in project.diagnostics
            if d.message.startswith("inline calc ")
        )

    built = _build(tmp_path, body)  # the build path
    checked = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(checked)
    build_mod.build(checked, seal_write=False, reseal=False)  # the check path
    assert diags(checked) == diags(built)
    levels = [d[0] for d in diags(checked)]
    assert levels.count("error") == 1  # the incompatible stored unit
    assert levels.count("warning") == 1  # the stale value

# ------------------------------------------- the run-12 message defects
# (in-prog-logs/user-sim-release-gate-run12.md F12-4..F12-6): F12-4 pins
# the message a user-sim run found dishonest; F12-5 and F12-6, closed by
# slice 2, pin the fixed behaviour, with the fence form as the control.


def _build_items(tmp_path, files, config=BASIC_CONFIG):
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def _inline_messages(project):
    return [d.message for d in project.diagnostics if d.message.startswith("inline calc ")]


def test_stale_display_never_shows_a_value_that_looks_accepted(tmp_path):
    # F12-4: 6.899 V / 2 = 3.4495 V is outside the window of stored 3.5 V
    # (3.45..3.55), yet at 3 sigfigs it displayed as `3.45 V` -- a number
    # the author reads as passing the window. The warning shows the raw
    # value whenever the rounded display would itself fit the window.
    project = _build(
        tmp_path,
        "`x := 6.899 V / 2 = 3.5 V`\n",
        config=BASIC_CONFIG + "sigfigs: 3\n",
    )
    warns = _inline_warnings(project)
    assert len(warns) == 1
    assert warns[0].message == (
        "inline calc x: stored result says 3.5 V, now computes 3.4495 V"
    )


def test_span_only_cross_item_reference_creates_an_ordering_edge(tmp_path):
    # F12-5, closed by slice 2 (docs/design/inline-calc.md section 3): the
    # scheduler's edges come from fence lines and inline spans alike, so a
    # reference that lives only in a span runs after its target's calc and
    # resolves. The gap this test pinned -- the span running first, the old
    # message blaming the target ("it defines no calc values") for a name
    # its fence defines -- is now the scheduler's job.
    project = _build_items(
        tmp_path,
        {
            "a.md": "---\nid: DEC-001\ntype: decision\n---\n\n"
            "`v := DEC-002.V_in = 2 V`\n",
            "b.md": "---\nid: DEC-002\ntype: decision\n---\n\n"
            "```calc\nV_in = 2 V\n```\n",
        },
    )
    assert project.errors == []
    assert _inline_messages(project) == []
    # The span renders as literal code on the page -- the whole authored
    # text, result included (slice 1: a stored result is never
    # interpolated). The old `"2 V" in body_html` was a substring of the
    # span's own text, true whatever the build did.
    assert "<code>v := DEC-002.V_in = 2 V</code>" in _item(project).body_html
    # The resolved value is observable through the stale-result warning:
    # author a WRONG stored result, and the build quotes what the span
    # actually computed -- 2 V, the target's fence value -- which is only
    # computable if the scheduler ran the target first and the span's
    # reference resolved (a clean `errors == []` with a literal `<code>`
    # render is true even if the span were scanned but never evaluated).
    project = _build_items(
        tmp_path,
        {
            "a.md": "---\nid: DEC-001\ntype: decision\n---\n\n"
            "`v := DEC-002.V_in = 3 V`\n",
            "b.md": "---\nid: DEC-002\ntype: decision\n---\n\n"
            "```calc\nV_in = 2 V\n```\n",
        },
    )
    assert project.errors == []
    stale = [m for m in _inline_messages(project) if "stored result says" in m]
    assert len(stale) == 1, _inline_messages(project)
    assert "stored result says 3 V, now computes 2 V" in stale[0]
    # The fence form is the control: same reference, same clean result.
    project = _build_items(
        tmp_path,
        {
            "a.md": "---\nid: DEC-001\ntype: decision\n---\n\n"
            "```calc\nv = DEC-002.V_in\n```\n\nSpan v = {{v}}\n",
            "b.md": "---\nid: DEC-002\ntype: decision\n---\n\n"
            "```calc\nV_in = 2 V\n```\n",
        },
    )
    assert project.errors == []
    assert "2 V" in _item(project).body_html


def test_span_source_is_pinned_by_fetch(tmp_path):
    # F12-6, closed by slice 2 (docs/design/inline-calc.md section 3): key
    # discovery reads inline spans, so the span's own miss carries the
    # standard fetch advice, `refdes fetch` pins the key a span names, and
    # the span resolves -- the fence-form dead end this test pinned (fetch
    # hashed the file, extracted no key, the same error returned forever)
    # is gone.
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision:\n    prefix: DEC\n    fields:\n"
        "      citations: { type: citations, on_change: invalidate }\n",
    )
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text(
        "key,value\nk1,5.0\n", encoding="utf-8"
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    span_body = '`k1 := source("analysis/budget.csv", "k1") | V = 5 V`\n'
    (items / "a.md").write_text(
        "---\nid: DEC-001\ntype: decision\ncitations:\n"
        "  - path: analysis/budget.csv\n---\n\n" + span_body,
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")

    def build():
        project = load_project(config_path=config)
        parse.load_items(project)
        build_mod.build(project)
        return project

    # Before the fetch the span is just an unpinned use: the advice the
    # fence form gets, the fix the fence form gets.
    project = build()
    assert _inline_messages(project) == [
        "inline calc k1: source('analysis/budget.csv', 'k1') has no locked "
        "value -- run 'refdes fetch --path analysis/budget.csv' to extract "
        "and pin it"
    ]
    # The fence form is the control: fetch genuinely can pin it from there.
    (items / "a.md").write_text(
        "---\nid: DEC-001\ntype: decision\ncitations:\n"
        "  - path: analysis/budget.csv\n---\n\n"
        '```calc\nk1 = source("analysis/budget.csv", "k1") | V\n```\n',
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert (
        "calc 'k1': source('analysis/budget.csv', 'k1') has no locked value "
        "-- run 'refdes fetch --path analysis/budget.csv' to extract and "
        "pin it"
    ) in [d.message for d in project.diagnostics]

    # Discovery reads the span: the fetch pins the key, no fence needed.
    # The signal is the item's content hash moving -- the locked value is a
    # hash input -- not `body_html`, which carries the span's authored text
    # (including its literal `5 V`) pin or no pin.
    (items / "a.md").write_text(
        "---\nid: DEC-001\ntype: decision\ncitations:\n"
        "  - path: analysis/budget.csv\n---\n\n" + span_body,
        encoding="utf-8",
    )
    unpinned = build().item_by_id("DEC-001").content_hash
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    project = build()
    assert _inline_messages(project) == []
    assert project.item_by_id("DEC-001").content_hash != unpinned


# =================================================================== run-12
# F12-1..F12-3: the three span-recognition changes the owner decided. Each
# is pinned at the grammar level (inline_calc) and the build level (a real
# item body), with the run-12 repro as the anchor fixture.


def _comment_warnings(project):
    return [d for d in project.warnings if "unclosed HTML comment" in d.message]


def _build_list_file(tmp_path, text):
    write_project_config(tmp_path, BASIC_CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "logs.yaml").write_text(text, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


# --------------------------------------------------------- F12-1: HTML comments


def test_span_inside_html_comment_is_inert():
    body = "Text <!-- `Vout := 1 V * 2 = 99 V` --> tail"
    assert inline_calc.triggered_spans(body) == []


def test_spans_around_a_same_line_comment_fire_the_comment_body_is_inert():
    body = "`a := 1 V = 1 V` x <!-- `b := 1 V = 9 V` --> `c := 2 V = 2 V`"
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a", "c"]


def test_multi_line_comment_skips_the_span_it_wraps():
    body = "line0\n<!--\n`b := 1 V = 9 V`\n-->\nline4 `a := 1 V = 1 V`"
    assert [(s.line_offset, s.name) for s in inline_calc.triggered_spans(body)] == [
        (4, "a")
    ]
    assert inline_calc.unclosed_comment_offset(body) is None


def test_several_comments_in_one_body():
    body = (
        "`a := 1 V = 1 V`\n"
        "<!-- x `c := 1 V = 9 V` y -->\n"
        "`d := 1 V = 1 V`\n"
        "<!-- z `e := 1 V = 9 V` w -->\n"
    )
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a", "d"]


def test_comment_inside_a_fence_is_inert_the_fence_wins():
    # `<!--` inside fenced code is code text: it never opens a comment, so
    # the span after the fence fires and there is no unclosed-comment line.
    body = "```\n<!-- `b := 1 V = 9 V`\n```\nafter `a := 1 V = 1 V`"
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a"]
    assert inline_calc.unclosed_comment_offset(body) is None


def test_fence_inside_a_comment_is_inert_the_comment_wins():
    # A fence line under an open comment is comment text: it opens no fence,
    # so the calc fence content is inert and the span after the comment fires.
    body = "<!--\n```calc\nx = 1\n```\n-->\nafter `a := 1 V = 1 V`"
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a"]
    assert inline_calc.unclosed_comment_offset(body) is None


def test_unclosed_comment_reports_its_line_and_inertizes_the_rest():
    body = "`a := 1 V = 1 V`\n<!-- never closes\n`b := 1 V = 9 V`"
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a"]
    assert inline_calc.unclosed_comment_offset(body) == 1


def test_unclosed_comment_after_a_closed_one_points_to_the_second_opener():
    # A comment that closes mid-line and a second one opened on that line and
    # left unclosed: the warning names the second (the live opener), not the
    # first (which did close).
    body = (
        "text\n"
        "<!-- first\n"
        "--> x <!-- second never closes\n"
        "`a := 1 V = 1 V`\n"
    )
    assert inline_calc.unclosed_comment_offset(body) == 2
    assert inline_calc.triggered_spans(body) == []


def test_unclosed_comment_on_the_same_line_as_a_closed_one():
    body = "text <!-- first --> x <!-- second never closes\n`a := 1 V = 1 V`\n"
    assert inline_calc.unclosed_comment_offset(body) == 0
    assert inline_calc.triggered_spans(body) == []


def test_nested_looking_comment_closes_at_the_first_arrow():
    # Comments do not nest: the second `<!--` is text, the first `-->` closes.
    body = "<!-- <!-- `b := 1 V = 9 V` --> `a := 1 V = 1 V`"
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a"]
    assert inline_calc.unclosed_comment_offset(body) is None


def test_open_marker_inside_a_code_span_is_literal_span_text():
    # A `<!--` inside a code span is ordinary span content, not a comment
    # opener: the span is captured (and its eval is the author's problem).
    body = "`a := 1 V = 1 V` and `t := <!--1 = 1`"
    assert inline_calc.unclosed_comment_offset(body) is None
    spans = inline_calc.triggered_spans(body)
    assert spans[0].name == "a"
    assert spans[1].raw == "t := <!--1 = 1"


def test_close_marker_without_an_opener_is_literal_text():
    body = "plain --> text `a := 1 V = 1 V`"
    assert [s.name for s in inline_calc.triggered_spans(body)] == ["a"]
    assert inline_calc.unclosed_comment_offset(body) is None


def test_comment_in_a_list_and_blockquote_body_skips_the_span(tmp_path):
    project = _build(
        tmp_path,
        "- list `a := 1 V = 1 V` then <!-- `b := 1 V = 9 V` -->\n"
        "> blockquote `c := 2 V = 2 V` <!-- `d := 1 V = 9 V` -->\n",
    )
    assert project.errors == []
    assert _inline_warnings(project) == []  # the two commented spans are inert
    assert set(_item(project).calc_values) == {"a", "c"}


def test_comment_span_in_a_list_file_body_is_inert(tmp_path):
    project = _build_list_file(
        tmp_path,
        "defaults:\n  type: decision\n  prefix: DEC\n"
        "items:\n  - id: DEC-001\n    summary: s\n"
        "    body: |\n"
        "      Text <!-- `x := 1 V * 2 = 99 V` --> done\n"
        "      Live `y := 2 V = 2 V`\n",
    )
    assert _inline_messages(project) == []
    assert set(_item(project).calc_values) == {"y"}


def test_unclosed_comment_build_warns_once_at_its_line(tmp_path):
    project = _build(
        tmp_path,
        "`w := 1 V = 1 V`\n<!-- unclosed here\n`v := 2 V = 99 V`\n",
    )
    warns = _comment_warnings(project)
    assert len(warns) == 1
    assert warns[0].line == 7  # the `<!--` line (4 fm lines + blank + 2 body)
    assert "unclosed HTML comment" in warns[0].message
    assert warns[0].item_id == "DEC-001"
    # the span inside the comment is inert: only the live `w` is assigned
    assert set(_item(project).calc_values) == {"w"}


def test_closed_comment_no_warning(tmp_path):
    project = _build(tmp_path, "`w := 1 V = 1 V` <!-- `v := 2 V = 99 V` -->\n")
    assert _comment_warnings(project) == []
    assert project.errors == []
    assert set(_item(project).calc_values) == {"w"}


# --------------------------------------------------- F12-2: bad name before :=


def _not_a_name(span):
    return span.error is not None and "is not a calc name before `:=`" in span.error


def test_filename_with_colon_equal_is_flagged_not_result_missing():
    span = inline_calc.parse_span(0, "src=a:=b.csv")
    assert _not_a_name(span)
    assert "src=a" in span.error


def test_ambiguity_message_names_both_ways_out():
    span = inline_calc.parse_span(0, "src=a:=b.csv")
    assert "double-backtick span" in span.error
    assert "name := expression = result" in span.error


def test_digit_leading_name_is_flagged():
    assert _not_a_name(inline_calc.parse_span(0, "1x := 2 V = 2 V"))


def test_space_in_head_is_flagged():
    assert _not_a_name(inline_calc.parse_span(0, "a b := 1 = 1"))


def test_hyphen_in_head_is_flagged():
    assert _not_a_name(inline_calc.parse_span(0, "a-b := 1 = 1"))


def test_pipe_before_trigger_is_flagged():
    assert _not_a_name(inline_calc.parse_span(0, "x | V := 2 = 2 V"))


def test_empty_head_is_flagged():
    span = inline_calc.parse_span(0, " := 1 = 1")
    assert _not_a_name(span)
    assert "'' is not a calc name" in span.error


def test_valid_calc_names_are_not_flagged():
    assert inline_calc.parse_span(0, "x := 1 = 1").error is None
    assert inline_calc.parse_span(0, "v_in := 1 = 1").error is None
    assert inline_calc.parse_span(0, "_top := 1 = 1").error is None


def test_missing_space_before_trigger_is_not_the_name_message():
    # `x` is a valid name; the span is malformed for a different reason (no
    # wsp around `:=`), so it keeps the "not of the form" message, not the
    # F12-2 name message.
    span = inline_calc.parse_span(0, "x:= 1 V = 1 V")
    assert span.error is not None
    assert not _not_a_name(span)
    assert "not of the form" in span.error


def test_quoted_colon_equal_stays_inert():
    # The trigger honors quoting: `:=` inside quotes is not a trigger, so the
    # span never reaches the parser and stays ordinary code.
    assert not inline_calc.contains_trigger('t = "q:=1"')


def test_build_reports_the_split_name_message(tmp_path):
    project = _build(tmp_path, "See `src=a:=b.csv` for inputs.\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "is not a calc name before `:=`" in errs[0].message
    assert "double-backtick span" in errs[0].message
    assert errs[0].line == 6


# --------------------------------------------- F12-3: tight result separator


def _valid(span):
    return span.error is None and (span.name, span.rhs, span.unit, span.result)


def test_finding_repro_tight_pipe_and_separator():
    assert _valid(inline_calc.parse_span(0, "x := 1 V*4|V=4 V")) == (
        "x", "1 V*4", "V", "4 V"
    )


def test_tight_left_of_separator():
    assert _valid(inline_calc.parse_span(0, "y := 2V=4 V")) == ("y", "2V", "", "4 V")


def test_tight_right_of_separator():
    assert _valid(inline_calc.parse_span(0, "z := 3 V =4 V")) == ("z", "3 V", "", "4 V")
    assert _valid(inline_calc.parse_span(0, "z := 3 V= 4 V")) == ("z", "3 V", "", "4 V")


def test_tight_separator_exponent_no_unit():
    assert _valid(inline_calc.parse_span(0, "x := 1000=1e3")) == ("x", "1000", "", "1e3")


def test_tight_separator_compatible_unit():
    assert _valid(inline_calc.parse_span(0, "x := 2 A=2000 mA")) == (
        "x", "2 A", "", "2000 mA"
    )


def test_comparison_operators_are_never_the_separator():
    # The separator is the last `=`; the comparison stays in the expression
    # (where the evaluator rejects it), and its `=` is never split off.
    for op in ("==", "<=", ">=", "!="):
        span = inline_calc.parse_span(0, f"x := 1 {op} 2 = 4 V")
        assert span.error is None, op
        assert span.rhs == f"1 {op} 2", op
        assert span.result == "4 V", op


def test_equals_in_parentheses_is_never_the_separator():
    span = inline_calc.parse_span(0, "x := (1 = 2) = 4 V")
    assert span.error is None
    assert span.rhs == "(1 = 2)"
    assert span.result == "4 V"


def test_equals_in_quotes_is_never_the_separator():
    span = inline_calc.parse_span(0, 'x := source("f.csv","a=b") | W = 5 W')
    assert span.error is None
    assert span.rhs == 'source("f.csv","a=b")'
    assert span.result == "5 W"


def test_multi_equals_is_one_reading_not_ambiguous():
    # More than one `=` is not automatically ambiguous: only the last `=`
    # leaves a stored-result literal, so there is a single reading.
    span = inline_calc.parse_span(0, "x := 1 = 2 = 3")
    assert span.error is None
    assert (span.rhs, span.result) == ("1 = 2", "3")


def test_spaced_control_still_valid():
    assert _valid(inline_calc.parse_span(0, "w := 2 V = 2 V")) == ("w", "2 V", "", "2 V")


def test_comparison_rhs_is_an_eval_error_at_the_span(tmp_path):
    # The separator split is right; the expression `1 == 2` is not a calc
    # expression, so it is an ordinary evaluator error, not a grammar miss.
    project = _build(tmp_path, "`x := 1 == 2 = 4 V`\n")
    errs = _inline_errors(project)
    assert len(errs) == 1
    assert "not allowed in an expression" in errs[0].message


def test_tight_span_evaluates_clean_in_build(tmp_path):
    project = _build(tmp_path, "`x := 1 V*4|V=4 V`\n")
    assert project.errors == []
    assert _inline_warnings(project) == []
    assert _item(project).calc_values["x"] == "4 V"


def test_tight_span_stale_warns(tmp_path):
    project = _build(tmp_path, "`x := 1 V*4|V=9 V`\n")
    warns = _inline_warnings(project)
    assert len(warns) == 1
    assert "stored result says 9 V, now computes 4 V" in warns[0].message


def test_result_separators_helper_finds_tight_and_skips_delimiters():
    # Tight `=` is a candidate; the `:=`, a comparison and a quoted `=` are not.
    assert inline_calc._result_equals_positions("x := 2V=4 V") == [7]
    assert inline_calc._result_equals_positions("x := 1 == 2 = 4 V") == [12]
    assert inline_calc._result_equals_positions("x := 1 <= 2 = 4 V") == [12]
    assert inline_calc._result_equals_positions("x := 1 >= 2 = 4 V") == [12]
    assert inline_calc._result_equals_positions("x := 1 != 2 = 4 V") == [12]
    assert inline_calc._result_equals_positions("x := (1 = 2) = 4 V") == [13]
    assert inline_calc._result_equals_positions('x := source("f","a=b") = 4 V') == [23]


def test_ambiguous_span_is_reported_not_resolved(monkeypatch):
    # Defensive: more than one split that is a whole calc is reported naming
    # both readings rather than silently picking one. (Unreachable from real
    # spans -- see _split_readings -- so the seam is exercised directly.)
    monkeypatch.setattr(
        inline_calc,
        "_split_readings",
        lambda text, positions: [
            (5, "a", "1", "2 V"),
            (11, "a", "1 = 2", "3 V"),
        ],
    )
    span = inline_calc.parse_span(0, "a := 1 = 2 V = 3 V")
    assert span.error is not None
    assert "ambiguous" in span.error
    assert "a := 1 = 2 V" in span.error and "a := 1 = 2 V = 3 V" not in span.error
