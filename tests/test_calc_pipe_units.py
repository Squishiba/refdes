"""The Calcpad-style unit syntax: `name = expression | unit`.

The unit a result is presented in goes after the expression. The old
`name : unit = expression` spelling is retired: it is a build error naming
the exact fix, and `refdes calc-rewrite` migrates a whole project. Prose
references use the same form: `{{P_diss | mW}}`.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import calc, parse
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


# ------------------------------------------------------- the new spelling


def test_pipe_unit_converts_to_declared_unit():
    env = {}
    outcomes = calc.evaluate_block("P = 3.3 V * 1.2 A | mW", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["P"]) == "3960 mW"
    assert outcomes[0].annotation == "mW"
    assert outcomes[0].unit_style == "|"


def test_pipe_unit_converts_seconds_to_milliseconds():
    env = {}
    outcomes = calc.evaluate_block("t = 2.5 s | ms", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["t"]) == "2500 ms"


def test_pipe_unit_accepts_compound_units():
    env = {}
    outcomes = calc.evaluate_block(
        "D = 3.3 W / (1.4 inch * 0.9 inch) | W/in^2", env
    )
    assert outcomes[0].error is None
    assert calc.format_value(env["D"]) == "2.619 W/in²"


def test_pipe_unit_whitespace_is_optional():
    env = {}
    outcomes = calc.evaluate_block("P = 3.3 V*1.2 A|mW", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["P"]) == "3960 mW"


def test_pipe_unit_accepts_the_same_units_as_the_old_annotation():
    # Brackets are the escape hatch inside *expressions*; the old unit
    # annotation never accepted them, so neither does the new spelling --
    # what matters is that the accepted set is identical.
    outcome = calc.evaluate_block("t = 1800 s | [h]", {})[0]
    assert outcome.error == "unknown unit '[h]' in declaration"
    env = {}
    calc.evaluate_block("t = 1800 s | h", env)
    assert calc.format_value(env["t"]) == "0.5 h"


def test_pipe_unit_accepts_house_units():
    env = {}
    outcomes = calc.evaluate_block("w = 0.062 inch | mil", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["w"]) == "62 th"


def test_pipe_unit_asserts_dimension_like_the_old_spelling():
    outcomes = calc.evaluate_block("P = 3.3 V / 1.2 A | W", {})
    assert outcomes[0].error is not None
    assert "declared as W but the expression evaluates to V/A" in outcomes[0].error


def test_pipe_unit_with_tolerance_converts_the_whole_interval():
    env = {}
    outcomes = calc.evaluate_block("V = 12 V ± 5% | mV", env)
    assert outcomes[0].error is None
    assert calc.format_value(env["V"]) == "12000 mV"
    assert calc.format_bounds(env["V"]) == "11400 mV … 12600 mV"


def test_tolerance_after_the_pipe_unit_names_the_fix():
    outcomes = calc.evaluate_block("P = 3.3 V * 1.2 A | mW ± 10%", {})
    assert outcomes[0].error is not None
    assert "a tolerance belongs on the right-hand side" in outcomes[0].error
    assert "P = 3.3 V * 1.2 A ± 10% | mW" in outcomes[0].error


# ---------------------------------------------------------- both spellings


def test_both_spellings_on_one_line_name_each_other():
    outcomes = calc.evaluate_block("P : W = 3.3 V * 1.2 A | mW", {})
    assert outcomes[0].error is not None
    assert ": W" in outcomes[0].error
    assert "| mW" in outcomes[0].error


def test_unit_before_the_equals_is_rejected_with_the_fix():
    outcomes = calc.evaluate_block("P | mW = 3.3 V * 1.2 A", {})
    assert outcomes[0].error is not None
    assert "the unit goes after the expression" in outcomes[0].error


# ------------------------------------------------ the old spelling (guard)


def test_old_spelling_is_a_retired_error_naming_the_exact_fix():
    env = {}
    outcomes = calc.evaluate_block("P_mW : mW = 3.3 V * 1.2 A\nt : ms = 2.5 s", env)
    assert all(o.error is not None and o.retired for o in outcomes)
    assert "write `P_mW = 3.3 V * 1.2 A | mW`" in outcomes[0].error
    assert "write `t = 2.5 s | ms`" in outcomes[1].error
    assert all("refdes calc-rewrite" in o.error for o in outcomes)
    # The line still evaluates: a sealed entry (warning only) must render
    # its numbers, and calc-rewrite's value guard needs the before picture.
    assert calc.format_value(env["P_mW"]) == "3960 mW"
    assert calc.format_value(env["t"]) == "2500 ms"


def test_old_spelling_assertion_error_is_unchanged():
    outcomes = calc.evaluate_block("P : W = 3.3 V / 1.2 A", {})
    assert "declared as W but the expression evaluates to V/A" in outcomes[0].error


# ------------------------------------------------- `|` in other contexts


def test_pipe_inside_a_comment_does_not_confuse_the_parser():
    env = {}
    outcomes = calc.evaluate_block(
        "P = 3.3 V * 1.2 A  # compare | the datasheet table", env
    )
    assert outcomes[0].error is None
    assert calc.format_value(env["P"]) == "3.96 W"
    assert outcomes[0].comment == "compare | the datasheet table"


def test_comment_only_line_with_a_pipe_is_still_a_comment():
    outcomes = calc.evaluate_block("# a | b\nP = 3.3 V * 1.2 A", {})
    assert [o.error for o in outcomes] == [None]


# ------------------------------------------------------- build consumers


def test_rendered_table_shows_the_authors_own_marker(tmp_path):
    project = _build(
        tmp_path,
        "```calc\nV = 3.3 V\nI = 1.2 A\nP = V * I | mW\nQ = V * I | W\n```\n",
    )
    assert not project.errors
    html = project.item_by_id("DEC-001").body_html
    assert '<span class="calc-annotation">| mW</span>' in html
    assert '<span class="calc-annotation">| W</span>' in html


def test_items_json_export_carries_new_spelling_lines(tmp_path):
    from refdes import render

    project = _build(tmp_path, "```calc\nP = 3.3 V * 1.2 A | mW\n```\n")
    assert not project.errors
    payload = render.items_json(project)
    entry = next(i for i in payload["items"] if i["id"] == "DEC-001")
    line = entry["calcs"][0]
    assert line["name"] == "P"
    assert line["result"] == "3960 mW"
    assert line["error"] is None
    assert line["line"] == project.item_by_id("DEC-001").calcs[0].line


def test_calc_hash_survives_the_new_spelling_and_whitespace_reflow(tmp_path):
    project = _build(tmp_path, "```calc\nP = 3.3 V * 1.2 A | mW\n```\n")
    item = project.item_by_id("DEC-001")
    digest = build_mod.calc_hash_for(item)
    assert digest is not None
    item.body = "```calc\nP   =   3.3 V * 1.2 A   |   mW\n```\n"
    assert build_mod.calc_hash_for(item) == digest


# ------------------------------------------------------------ prose refs


def test_prose_reference_with_unit_converts(tmp_path):
    project = _build(
        tmp_path,
        "```calc\nP = 3.3 V * 1.2 A\n```\n\n"
        "The converter loses {{P | mW}}.\n",
    )
    assert not project.errors
    assert "3960 mW" in project.item_by_id("DEC-001").body_html


def test_prose_reference_without_unit_is_unchanged(tmp_path):
    project = _build(
        tmp_path,
        "```calc\nP = 3.3 V * 1.2 A\n```\n\n"
        "The converter loses {{P}}.\n",
    )
    assert not project.errors
    assert "3.96 W" in project.item_by_id("DEC-001").body_html


def test_prose_reference_with_wrong_dimension_errors_at_the_site(tmp_path):
    project = _build(
        tmp_path,
        "```calc\nP = 3.3 V * 1.2 A\n```\n\n"
        "The converter loses {{P | V}}.\n",
    )
    diagnostics = [d for d in project.errors if "{{P | V}}" in d.message]
    assert diagnostics, project.errors
    assert "declared as V" in diagnostics[0].message
    assert diagnostics[0].item_id == "DEC-001"
    # left as written, never silently shown in the calc's own unit
    assert "{{P | V}}" in project.item_by_id("DEC-001").body_html


def test_prose_reference_with_unit_to_an_unknown_name_still_warns(tmp_path):
    project = _build(tmp_path, "Nothing here: {{nope | mW}}.\n")
    assert any("does not name a calc value" in d.message for d in project.warnings)
    assert "{{nope | mW}}" in project.item_by_id("DEC-001").body_html


# ----------------------------------------------------------- checks: refs

TEMPERATURE_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    '  constrained_by: { inverse: constrains, label: "Constrained by" }\n'
    "types:\n"
    "  bound:\n"
    "    prefix: BND\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [bound]\n"
    "    body: {}\n"
)


@pytest.mark.parametrize(
    "expression",
    ["T_j = 313.15 K | degC", "T_j = 40 degC | degC"],
)
def test_checks_resolve_names_from_the_pipe_spelling(tmp_path, expression):
    """`checks: value:` refers to calc names, and the conversion the pipe
    spelling performs is what the check sees."""
    write_project_config(tmp_path, TEMPERATURE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "b.yaml").write_text(
        "items:\n"
        "  - id: BND-001\n    type: bound\n    text: Junction temperature\n"
        '    limit: "<= 85 degC"\n',
        encoding="utf-8",
    )
    (items / "d.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Thermal\n"
        "constrained_by: [BND-001]\n"
        "checks:\n"
        "  - value: T_j\n"
        "    against: BND-001\n"
        "---\n\n"
        f"```calc\n{expression}\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors
    result = project.item_by_id("DEC-001").checks[0]
    assert result.ok, result.detail
